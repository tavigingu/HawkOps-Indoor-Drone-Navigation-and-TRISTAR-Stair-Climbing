"""
Thread-urile worker de inferență: pose (YOLO-Pose), hazard (foc/fum), live overlay.
Depinde de: state, posture, tracking, snapshots
"""

import os
import time
from queue import Empty

import cv2
import numpy as np
from ultralytics import YOLO

import ai_analyzer.state as state
import ai_analyzer.posture as posture
import ai_analyzer.tracking as tracking
import ai_analyzer.snapshots as snapshots


# ---------------------------------------------------------------------------
# Dispatching frame-uri dinspre pipeline spre cozi
# ---------------------------------------------------------------------------

def process_frame(frame):
    """Trimite un frame la ambii workers dacă scanarea e activă."""
    if not state.is_scanning or frame is None:
        return
    with state.lock:
        state.session_data["frames_processed"] += 1
    if not state.pose_queue.full():
        state.pose_queue.put_nowait(frame.copy())
    if not state.hazard_queue.full():
        state.hazard_queue.put_nowait(frame.copy())


def set_person_capture_active(is_active):
    """Activează/dezactivează salvarea detecțiilor de persoane. Golește cozile existente."""
    with state.lock:
        state.person_capture_active = bool(is_active)
    while not state.pose_queue.empty():
        try:
            state.pose_queue.get_nowait()
        except Empty:
            break
    while not state.hazard_queue.empty():
        try:
            state.hazard_queue.get_nowait()
        except Empty:
            break


# ---------------------------------------------------------------------------
# Worker POSE (YOLO-Pose + ByteTrack)
# ---------------------------------------------------------------------------

def pose_worker_loop():
    """
    Thread background: detectează persoane și keypoints pe fiecare frame din pose_queue.
    Actualizează session_data["persons"] și salvează snapshot-uri.
    """
    print("🚀 Worker Thread POSE inițializat.")
    pose_model = YOLO(os.path.join(state.models_dir, 'yolo11n-pose.pt'))

    while state.thread_active:
        try:
            frame = state.pose_queue.get(timeout=0.5)
        except Empty:
            continue

        if frame is None or not state.is_scanning:
            continue

        try:
            with state.lock:
                capture_active = bool(state.person_capture_active)

            visible_track_ids = set()

            pose_results = pose_model.track(
                source=frame,
                persist=True,
                tracker=state.tracker_config,
                conf=state.person_conf_threshold,
                verbose=False,
            )

            if hasattr(pose_results[0], 'boxes') and pose_results[0].boxes is not None:
                boxes = pose_results[0].boxes
                keypoints = pose_results[0].keypoints
                xyxy = boxes.xyxy.cpu().numpy()

                track_ids = None
                if getattr(boxes, 'id', None) is not None:
                    try:
                        track_ids = boxes.id.int().cpu().tolist()
                    except Exception:
                        track_ids = None

                confs = boxes.conf.cpu().tolist()
                frame_h, frame_w = frame.shape[:2]

                if keypoints is not None:
                    kpts_data = keypoints.data.cpu().numpy()

                    for i in range(len(xyxy)):
                        person_kpts = kpts_data[i]
                        person_posture = posture.classify_posture(person_kpts)
                        x1, y1, x2, y2 = xyxy[i].astype(int).tolist()
                        bbox_xyxy = (int(x1), int(y1), int(x2), int(y2))
                        center_x = int((x1 + x2) / 2)
                        center_y = int((y1 + y2) / 2)

                        if center_x < frame_w * 0.33:
                            horizontal_region = "left"
                        elif center_x > frame_w * 0.66:
                            horizontal_region = "right"
                        else:
                            horizontal_region = "center"

                        position_payload = {
                            "bbox": [int(x1), int(y1), int(x2), int(y2)],
                            "center": [int(center_x), int(center_y)],
                            "region": horizontal_region,
                            "frame_size": [int(frame_w), int(frame_h)],
                        }

                        visible_keypoints = int(np.sum(person_kpts[:, 2] > 0.3))
                        now_ts = time.time()

                        # Rezolvă track_id canonic (YOLO tracker sau fallback IoU)
                        with state.lock:
                            canonical_track_id = None
                            if track_ids is not None and i < len(track_ids):
                                try:
                                    canonical_track_id = int(track_ids[i])
                                except Exception:
                                    canonical_track_id = None

                            if canonical_track_id is None:
                                matched = tracking.find_matching_person_track(bbox_xyxy, now_ts)
                                if matched is not None:
                                    canonical_track_id = int(matched)
                                else:
                                    canonical_track_id = int(state.fallback_track_seq)
                                    state.fallback_track_seq += 1
                            elif canonical_track_id not in state.session_data["persons"]:
                                matched = tracking.find_matching_person_track(bbox_xyxy, now_ts)
                                if matched is not None:
                                    canonical_track_id = int(matched)

                        visible_track_ids.add(canonical_track_id)

                        if not capture_active:
                            continue

                        with state.lock:
                            if canonical_track_id not in state.session_data["persons"]:
                                state.session_data["persons"][canonical_track_id] = {
                                    "conf": confs[i],
                                    "posture": person_posture,
                                    "hits": 1,
                                    "position": position_payload,
                                    "best_keypoints": -1,
                                    "best_image_path": None,
                                    "last_bbox": bbox_xyxy,
                                    "last_seen_ts": now_ts,
                                    "in_frame": True,
                                    "medical_dispatched": False,
                                    "medical_analysis": None,
                                }
                            else:
                                p = state.session_data["persons"][canonical_track_id]
                                p["hits"] += 1
                                p["position"] = position_payload
                                p["last_bbox"] = bbox_xyxy
                                p["last_seen_ts"] = now_ts
                                p["in_frame"] = True
                                if confs[i] > p["conf"]:
                                    p["conf"] = confs[i]
                                    p["posture"] = person_posture

                        snapshots.save_best_person_snapshot(
                            frame,
                            canonical_track_id,
                            bbox=(x1, y1, x2, y2),
                            keypoint_count=visible_keypoints,
                        )

                    if len(xyxy) > 0 and capture_active:
                        snapshot_track_ids = track_ids if track_ids is not None else list(visible_track_ids)
                        snapshots.save_person_frame_snapshot(frame, snapshot_track_ids, confs)

            if capture_active:
                tracking.handle_person_track_exits(visible_track_ids)

        except Exception:
            pass


# ---------------------------------------------------------------------------
# Worker HAZARD (foc / fum)
# ---------------------------------------------------------------------------

def hazard_worker_loop():
    """Thread background: detectează foc și fum pe fiecare frame din hazard_queue."""
    print("🚀 Worker Thread HAZARD inițializat.")
    fire_smoke_model = YOLO(os.path.join(state.models_dir, 'yolo8-fire-smoke.pt'))

    while state.thread_active:
        try:
            frame = state.hazard_queue.get(timeout=0.5)
        except Empty:
            continue

        if frame is None or not state.is_scanning:
            continue

        try:
            hazard_results = fire_smoke_model.predict(
                source=frame, conf=state.hazard_conf_threshold, verbose=False
            )
            if hasattr(hazard_results[0], 'boxes') and len(hazard_results[0].boxes) > 0:
                for box in hazard_results[0].boxes:
                    cls_id = int(box.cls[0])
                    label = fire_smoke_model.names.get(cls_id, "").lower()
                    with state.lock:
                        if "fire" in label:
                            state.session_data["hazards"]["fire"] += 1
                        if "smoke" in label:
                            state.session_data["hazards"]["smoke"] += 1
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Worker LIVE overlay (stream continuu, independent de sesiunea de scan)
# ---------------------------------------------------------------------------

def _ensure_live_models():
    """Lazy-load modelele live (o singură dată per proces)."""
    import os
    if state.live_pose_model is None:
        state.live_pose_model = YOLO(os.path.join(state.models_dir, 'yolo11n-pose.pt'))
    if state.live_hazard_model is None:
        state.live_hazard_model = YOLO(os.path.join(state.models_dir, 'yolo8-fire-smoke.pt'))


def _run_live_inference(frame):
    """Rulează inferența pose + hazard pe un frame și returnează (persons, hazards)."""
    _ensure_live_models()

    persons = []
    hazards = []

    try:
        pose_results = state.live_pose_model.track(
            source=frame,
            persist=True,
            tracker=state.tracker_config,
            conf=state.person_conf_threshold,
            verbose=False,
        )
        if pose_results and hasattr(pose_results[0], 'boxes') and pose_results[0].boxes is not None:
            boxes = pose_results[0].boxes
            keypoints_obj = getattr(pose_results[0], 'keypoints', None)
            if len(boxes) > 0 and keypoints_obj is not None and keypoints_obj.data is not None:
                xyxy = boxes.xyxy.cpu().numpy()
                confs = boxes.conf.cpu().numpy()
                kpts_data = keypoints_obj.data.cpu().numpy()
                track_ids = None
                if getattr(boxes, 'id', None) is not None:
                    try:
                        track_ids = boxes.id.int().cpu().tolist()
                    except Exception:
                        track_ids = None
                for i in range(len(xyxy)):
                    x1, y1, x2, y2 = xyxy[i].astype(int).tolist()
                    person_kpts = kpts_data[i]
                    person_posture = posture.classify_posture(person_kpts)
                    track_id = None
                    if track_ids is not None and i < len(track_ids):
                        try:
                            track_id = int(track_ids[i])
                        except Exception:
                            track_id = None
                    persons.append({
                        "bbox": (x1, y1, x2, y2),
                        "conf": float(confs[i]),
                        "posture": person_posture,
                        "keypoints": person_kpts,
                        "track_id": track_id,
                    })
    except Exception:
        pass

    try:
        hazard_results = state.live_hazard_model.predict(
            source=frame, conf=state.hazard_conf_threshold, verbose=False
        )
        if hazard_results and hasattr(hazard_results[0], 'boxes') and hazard_results[0].boxes is not None:
            for box in hazard_results[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].int().cpu().tolist()
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                label = state.live_hazard_model.names.get(cls_id, "hazard").lower()
                hazards.append((x1, y1, x2, y2, conf, label))
    except Exception:
        pass

    return persons, hazards


def _render_live_overlay(frame, person_dets, hazard_dets):
    """Desenează bounding boxes, skeleton și labels pe un frame copie."""
    annotated = frame.copy()

    skeleton_edges = [
        (0, 1), (0, 2), (1, 3), (2, 4),
        (5, 6),
        (5, 7), (7, 9),
        (6, 8), (8, 10),
        (5, 11), (6, 12),
        (11, 12),
        (11, 13), (13, 15),
        (12, 14), (14, 16),
    ]

    for det in person_dets:
        x1, y1, x2, y2 = det["bbox"]
        conf = det["conf"]
        person_posture = det["posture"]
        keypoints = det["keypoints"]
        track_id = det.get("track_id")

        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 220, 0), 2)
        label = f"YOLO PERSON {person_posture.upper()} {conf:.2f}"
        cv2.putText(annotated, label, (x1, max(24, y1 - 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.78, (0, 220, 0), 3)

        if track_id is not None:
            cv2.putText(annotated, f"TRACKING ID {track_id}", (x1, max(44, y1 + 24)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 235, 255), 2)

        for p1, p2 in skeleton_edges:
            if p1 >= len(keypoints) or p2 >= len(keypoints):
                continue
            xk1, yk1, ck1 = keypoints[p1]
            xk2, yk2, ck2 = keypoints[p2]
            if ck1 > 0.3 and ck2 > 0.3:
                cv2.line(annotated, (int(xk1), int(yk1)), (int(xk2), int(yk2)), (255, 220, 0), 2)

        for xk, yk, ck in keypoints:
            if ck > 0.3:
                cv2.circle(annotated, (int(xk), int(yk)), 3, (0, 255, 255), -1)

    for x1, y1, x2, y2, conf, label in hazard_dets:
        is_fire = "fire" in label
        color = (0, 0, 255) if is_fire else (0, 165, 255)
        tag = "FIRE" if is_fire else "SMOKE"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated, f"YOLO {tag} {conf:.2f}", (x1, max(24, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.78, color, 3)

    return annotated


def live_worker_loop():
    """Thread background: procesează frame-uri din live_queue și actualizează overlay-ul."""
    while state.thread_active:
        try:
            frame = state.live_queue.get(timeout=0.25)
        except Empty:
            continue

        if frame is None:
            continue

        persons, hazards = _run_live_inference(frame)
        annotated = _render_live_overlay(frame, persons, hazards)

        with state.lock:
            state.live_person_detections = persons
            state.live_hazard_detections = hazards
            state.live_annotated_frame = annotated
            state.live_overlay_updated_ts = time.time()

def apply_latest_annotations(frame):
    """Aplică ultimele bounding box-uri detectate pe un frame independent (ex: depth)."""
    if frame is None:
        return frame
    with state.lock:
        persons = state.live_person_detections[:]
        hazards = state.live_hazard_detections[:]
    return _render_live_overlay(frame, persons, hazards)

def annotate_live_frame(frame):
    """
    Adaugă overlay-ul live (persoane + hazarduri) pe un frame.
    Dacă overlay-ul e mai vechi de live_max_overlay_age_s, returnează frame-ul original.
    """
    if frame is None:
        return frame
    if not state.live_enabled:
        return frame

    now = time.time()
    if (now - state.last_live_infer_ts) >= state.live_infer_interval_s:
        try:
            if state.live_queue.full():
                try:
                    state.live_queue.get_nowait()
                except Empty:
                    pass
            state.live_queue.put_nowait(frame.copy())
            state.last_live_infer_ts = now
        except Exception:
            pass

    with state.lock:
        overlay_updated_ts = float(state.live_overlay_updated_ts)
        annotated_frame = None if state.live_annotated_frame is None else state.live_annotated_frame.copy()

    if (now - overlay_updated_ts) > state.live_max_overlay_age_s:
        return frame
    if annotated_frame is None:
        return frame
    return annotated_frame
