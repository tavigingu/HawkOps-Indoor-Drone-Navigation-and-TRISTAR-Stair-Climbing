"""
Tracking persoane: IoU matching, calificare pentru raport, gestionare ieșiri.
Depinde de: state, medical
"""

import os
import time

import ai_analyzer.state as state


def bbox_iou_xyxy(box_a, box_b):
    """Calculează IoU (Intersection over Union) între două bounding boxes [x1,y1,x2,y2]."""
    try:
        ax1, ay1, ax2, ay2 = [float(v) for v in box_a]
        bx1, by1, bx2, by2 = [float(v) for v in box_b]

        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0.0, inter_x2 - inter_x1)
        inter_h = max(0.0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h
        if inter_area <= 0.0:
            return 0.0

        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        denom = area_a + area_b - inter_area
        if denom <= 0.0:
            return 0.0
        return float(inter_area / denom)
    except Exception:
        return 0.0


def find_matching_person_track(bbox_xyxy, now_ts):
    """
    Caută în session_data["persons"] cel mai bun track existent cu IoU ≥ 0.35
    față de bbox_xyxy, nu mai vechi de 1.2s.
    ATENȚIE: trebuie apelat cu state.lock deja deținut de apelant.
    """
    best_track = None
    best_iou = 0.0
    max_age_s = 1.2
    min_iou = 0.35

    persons_map = state.session_data.get("persons", {})
    if not isinstance(persons_map, dict):
        return None

    for existing_track_id, existing_state in persons_map.items():
        if not isinstance(existing_state, dict):
            continue
        last_bbox = existing_state.get("last_bbox")
        if not last_bbox:
            continue
        last_seen = float(existing_state.get("last_seen_ts", 0.0))
        if (now_ts - last_seen) > max_age_s:
            continue
        iou_val = bbox_iou_xyxy(bbox_xyxy, last_bbox)
        if iou_val >= min_iou and iou_val > best_iou:
            best_iou = iou_val
            best_track = existing_track_id

    return best_track


def handle_person_track_exits(visible_track_ids):
    """
    Pentru fiecare persoană care a dispărut din cadru (> person_exit_timeout_s),
    declanșează asincron analiza medicală.
    Achizitionează state.lock intern — NU apela din interiorul unui with state.lock.
    """
    import ai_analyzer.medical as medical

    now_ts = time.time()
    to_dispatch = []

    with state.lock:
        if not state.is_scanning or state.current_room is None:
            return

        room_idx = int(state.current_room)
        persons_map = state.session_data.get("persons", {})
        if not isinstance(persons_map, dict):
            return

        for track_id, person_state in persons_map.items():
            if not isinstance(person_state, dict):
                continue

            if track_id in visible_track_ids:
                person_state["last_seen_ts"] = now_ts
                person_state["in_frame"] = True
                continue

            last_seen_ts = float(person_state.get("last_seen_ts", now_ts))
            if person_state.get("in_frame", False) and (now_ts - last_seen_ts) >= state.person_exit_timeout_s:
                person_state["in_frame"] = False
                if not person_state.get("medical_dispatched"):
                    to_dispatch.append((room_idx, track_id))

    for item_room_idx, item_track_id in to_dispatch:
        medical.dispatch_person_medical_analysis_async(item_room_idx, item_track_id)
