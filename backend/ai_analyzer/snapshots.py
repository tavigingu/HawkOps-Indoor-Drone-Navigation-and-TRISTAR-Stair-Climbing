"""
Salvare snapshot-uri cadre video cu persoane detectate.
Depinde de: state
"""

import os
import time
from datetime import datetime

import cv2

import ai_analyzer.state as state


def encode_frame_bytes(frame):
    """Encodează un frame OpenCV (BGR) în bytes JPEG."""
    try:
        frame_for_encode = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    except Exception:
        frame_for_encode = frame
    ok, jpeg_buffer = cv2.imencode('.jpg', frame_for_encode, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        return None
    return jpeg_buffer.tobytes()


def save_person_frame_snapshot(frame, track_ids, confs):
    """
    Salvează periodic un frame cu toate persoanele vizibile (interval minim 1s).
    Calea e înregistrată în session_data["person_frames"].
    """
    now_ts = time.time()
    with state.lock:
        if not state.is_scanning or state.current_room is None:
            return
        if state.person_frames_dir is None:
            return
        if now_ts - state.last_person_frame_save_ts < state.person_frame_save_interval_s:
            return

        room_idx = state.current_room
        frame_idx = int(state.session_data.get("frames_processed", 0))
        state.last_person_frame_save_ts = now_ts

        max_conf = max([float(c) for c in confs], default=0.0)
        track_label = "-".join(str(int(tid)) for tid in sorted(set(track_ids)))
        if not track_label:
            track_label = "na"

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        file_name = (
            f"room_{room_idx}_frame_{frame_idx:06d}_"
            f"tracks_{track_label}_conf_{max_conf:.2f}_{timestamp}.jpg"
        )
        file_path = os.path.join(state.person_frames_dir, file_name)

    try:
        frame_bytes = encode_frame_bytes(frame)
        if frame_bytes is not None:
            with open(file_path, 'wb') as image_file:
                image_file.write(frame_bytes)
            with state.lock:
                state.session_data["person_frames"].append(file_path)
    except Exception:
        pass


def save_best_person_snapshot(frame, track_id, bbox, keypoint_count):
    """
    Salvează cel mai bun crop al persoanei (cu cei mai mulți keypoints vizibili).
    Înlocuiește snapshot-ul anterior dacă keypoint_count e mai mare.
    """
    if int(keypoint_count) < 1:
        return

    with state.lock:
        if not state.is_scanning or state.current_room is None or state.person_frames_dir is None:
            return

        person_state = state.session_data["persons"].get(track_id)
        if person_state is None:
            return

        current_best = int(person_state.get("best_keypoints", -1))
        if keypoint_count <= current_best:
            return

        room_idx = int(state.current_room)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        file_name = f"room_{room_idx}_person_{int(track_id)}_kpts_{int(keypoint_count):02d}_{timestamp}.jpg"
        file_path = os.path.join(state.person_frames_dir, file_name)

    x1, y1, x2, y2 = [int(v) for v in bbox]
    frame_h, frame_w = frame.shape[:2]
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    pad_x = int(box_w * 0.35)   # 35% lateral — anterior 15%
    pad_y = int(box_h * 0.40)   # 40% vertical — anterior 20%

    x1 = max(0, min(frame_w - 1, x1 - pad_x))
    y1 = max(0, min(frame_h - 1, y1 - pad_y))
    x2 = max(0, min(frame_w, x2 + pad_x))
    y2 = max(0, min(frame_h, y2 + pad_y))

    if x2 <= x1 or y2 <= y1:
        return

    person_crop = frame[y1:y2, x1:x2]
    if person_crop is None or person_crop.size == 0:
        return

    try:
        frame_bytes = encode_frame_bytes(person_crop)
        if frame_bytes is None:
            return
        with open(file_path, 'wb') as image_file:
            image_file.write(frame_bytes)
        with state.lock:
            person_state_after = state.session_data["persons"].get(track_id)
            if person_state_after is None:
                return
            if keypoint_count > int(person_state_after.get("best_keypoints", -1)):
                person_state_after["best_keypoints"] = int(keypoint_count)
                person_state_after["best_image_path"] = file_path
    except Exception:
        return
