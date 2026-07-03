"""
Clasificare postură umană din keypoints YOLO-Pose.
Modul pur — nicio dependență de stare, doar numpy.
"""

import numpy as np


def classify_posture(kpts):
    """
    Determină postura unei persoane (standing / sitting / fallen / unknown)
    pe baza keypoints-urilor YOLO-Pose (17 puncte COCO).
    """
    try:
        conf_thr = 0.15

        def get_point(idx):
            if idx >= len(kpts):
                return None
            x_val, y_val, score = kpts[idx]
            if score < conf_thr:
                return None
            return float(x_val), float(y_val)

        def pick(*indices):
            for idx in indices:
                point = get_point(idx)
                if point is not None:
                    return point
            return None

        def avg_pair(idx_a, idx_b):
            point_a = get_point(idx_a)
            point_b = get_point(idx_b)
            if point_a is not None and point_b is not None:
                return ((point_a[0] + point_b[0]) / 2.0, (point_a[1] + point_b[1]) / 2.0)
            return point_a or point_b

        def has_segment(idx_a, idx_b):
            return get_point(idx_a) is not None and get_point(idx_b) is not None

        def angle_at(point_a, point_b, point_c):
            if point_a is None or point_b is None or point_c is None:
                return None
            vec_ba = np.array([point_a[0] - point_b[0], point_a[1] - point_b[1]], dtype=np.float32)
            vec_bc = np.array([point_c[0] - point_b[0], point_c[1] - point_b[1]], dtype=np.float32)
            norm_ba = float(np.linalg.norm(vec_ba))
            norm_bc = float(np.linalg.norm(vec_bc))
            if norm_ba < 1e-6 or norm_bc < 1e-6:
                return None
            cos_val = float(np.dot(vec_ba, vec_bc) / (norm_ba * norm_bc))
            cos_val = float(np.clip(cos_val, -1.0, 1.0))
            return float(np.degrees(np.arccos(cos_val)))

        nose = get_point(0)
        shoulder = avg_pair(5, 6)
        hip = avg_pair(11, 12)
        knee = avg_pair(13, 14)
        ankle = avg_pair(15, 16)

        left_shoulder = get_point(5)
        right_shoulder = get_point(6)
        left_hip = get_point(11)
        right_hip = get_point(12)
        left_knee = get_point(13)
        right_knee = get_point(14)
        left_ankle = get_point(15)
        right_ankle = get_point(16)

        visible_points = sum(1 for idx in [0, 5, 6, 11, 12, 13, 14, 15, 16] if get_point(idx) is not None)
        segment_count = 0
        for idx_a, idx_b in ((5, 11), (6, 12), (11, 13), (12, 14), (13, 15), (14, 16)):
            if has_segment(idx_a, idx_b):
                segment_count += 1

        if visible_points < 4 or segment_count < 2:
            return "unknown"

        if hip is None:
            return "unknown"

        if shoulder is None:
            shoulder = pick(5, 6, 0)
        if ankle is None:
            ankle = pick(15, 16, 13, 14)

        if shoulder is None:
            return "unknown"

        hip_to_ankle = abs(hip[1] - ankle[1]) if ankle is not None else None
        shoulder_to_hip = abs(shoulder[1] - hip[1])
        nose_to_hip = abs(nose[1] - hip[1]) if nose is not None else None
        nose_to_shoulder = abs(nose[1] - shoulder[1]) if nose is not None else None

        horizontal_span = None
        vertical_span = None
        if nose is not None and ankle is not None:
            horizontal_span = abs(nose[0] - ankle[0])
            vertical_span = abs(nose[1] - ankle[1])

        fallen_score = 0

        if nose_to_hip is not None and shoulder_to_hip > 20:
            if nose_to_hip < shoulder_to_hip * 0.65:
                fallen_score += 1

        if horizontal_span is not None and vertical_span is not None and vertical_span > 1:
            aspect_ratio = horizontal_span / vertical_span
            if aspect_ratio > 1.2:
                fallen_score += 2

        if shoulder_to_hip > 0 and nose_to_shoulder is not None and hip_to_ankle is not None:
            torso_height = shoulder_to_hip + nose_to_shoulder
            if torso_height < hip_to_ankle * 0.5:
                fallen_score += 1

        if left_shoulder and right_shoulder and left_hip and right_hip:
            avg_shoulder_y = (left_shoulder[1] + right_shoulder[1]) / 2.0
            avg_hip_y = (left_hip[1] + right_hip[1]) / 2.0
            if abs(avg_shoulder_y - avg_hip_y) < 50:
                fallen_score += 2

        if fallen_score >= 3:
            return "fallen"

        # ── Unghi la genunchi ──────────────────────────────────────────────
        # Drept (în picioare): ~165-180°  |  Îndoit (așezat/ghemuit): < ~120°
        knee_angle_candidates = []
        left_knee_angle  = angle_at(left_hip,  left_knee,  left_ankle)
        right_knee_angle = angle_at(right_hip, right_knee, right_ankle)
        if left_knee_angle  is not None: knee_angle_candidates.append(left_knee_angle)
        if right_knee_angle is not None: knee_angle_candidates.append(right_knee_angle)

        # ── SITTING ────────────────────────────────────────────────────────
        # Criteriu 1: cel puțin un genunchi clar îndoit (unghi ≤ 115°)
        sitting_by_angle = False
        if knee_angle_candidates:
            min_knee_angle = min(knee_angle_candidates)
            if min_knee_angle <= 115:
                sitting_by_angle = True

        # Criteriu 2: genunchii sunt aproape de nivelul șoldului pe verticală
        # (hip_to_knee / hip_to_ankle ≤ 0.30 → genunchii ridicați → persoana stă pe scaun/jos)
        sitting_by_position = False
        if knee is not None and hip_to_ankle is not None and hip_to_ankle > 10:
            hip_to_knee_v = abs(hip[1] - knee[1])
            hip_knee_ratio = hip_to_knee_v / (hip_to_ankle + 1e-6)
            if hip_knee_ratio <= 0.30:
                sitting_by_position = True

        if sitting_by_angle or sitting_by_position:
            return "sitting"

        # ── STANDING ──────────────────────────────────────────────────────
        if hip_to_ankle is not None and shoulder_to_hip > 20:
            if hip_to_ankle > shoulder_to_hip * 0.75 and segment_count >= 3:
                return "standing"

        if shoulder_to_hip > 30 and segment_count >= 3:
            return "standing"

        return "unknown"
    except Exception:
        return "unknown"
