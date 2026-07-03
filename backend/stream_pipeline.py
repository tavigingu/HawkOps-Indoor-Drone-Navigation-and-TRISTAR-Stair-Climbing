#!/usr/bin/env python3
"""
Pipeline pentru video + depth processing.
Conține toată logica de captură frame-uri, procesare depth și stream generators.
"""

import os
import sys
import threading
import time
from datetime import datetime
from queue import Queue

import cv2
import numpy as np
import torch

import navigation


# Import Depth Anything V2
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'Depth-Anything-V2'))
from depth_anything_v2.dpt import DepthAnythingV2

# Import AI Analyzer
import ai_analyzer



frame_queue = Queue(maxsize=30)
depth_queue = Queue(maxsize=30)
depth_model = None
depth_model_is_metric = False   # True dacă modelul activ e metric indoor (max_depth=20)
stop_event = threading.Event()
capture_thread = None
depth_thread = None
is_streaming = False
controller_ref = None
last_depth_snapshot = None
last_raw_frame_snapshot = None
last_depth_meters_snapshot = None
last_depth_mid_threshold = None
last_sampling_points = None
last_sampling_distances = None
_nav_measure_mode_logged = None
snapshot_lock = threading.Lock()

calibration_lock = threading.Lock()
calibration_profiles = {}
active_calibration_profile = 'corridor'


def _parse_calibration_json(calibration_json):
    import json

    with open(calibration_json, 'r') as f:
        data = json.load(f)

    points = data.get('calibration_points', {})
    if not points:
        return None, None

    pixel_values = np.array([int(k) for k in points.keys()])
    real_distances = np.array([float(v) for v in points.values()])
    return pixel_values, real_distances


def _parse_calibration_yaml(calibration_yaml):
    parsed_points = {}
    in_points = False

    with open(calibration_yaml, 'r', encoding='utf-8') as yaml_file:
        for raw_line in yaml_file:
            line = raw_line.strip()
            if not line:
                continue
            if line == 'calibration_points:':
                in_points = True
                continue
            if in_points and not raw_line.startswith('  '):
                break
            if in_points and line.startswith('"') and '":' in line:
                key_str, value_str = line.split('":', 1)
                pixel_key = int(key_str.replace('"', '').strip())
                real_val = float(value_str.strip())
                parsed_points[pixel_key] = real_val

    if not parsed_points:
        return None, None

    pixel_values = np.array(sorted(parsed_points.keys()), dtype=np.int32)
    real_distances = np.array([parsed_points[int(p)] for p in pixel_values], dtype=np.float32)
    return pixel_values, real_distances


def _load_profile_from_candidates(profile_name, candidates):
    for calibration_file in candidates:
        if not os.path.exists(calibration_file):
            continue

        try:
            if calibration_file.endswith('.yaml') or calibration_file.endswith('.yml'):
                pixel_values, real_distances = _parse_calibration_yaml(calibration_file)
            else:
                pixel_values, real_distances = _parse_calibration_json(calibration_file)

            if pixel_values is None or real_distances is None or len(pixel_values) == 0:
                continue

            print(f"✅ Calibrare {profile_name} încărcată: {len(pixel_values)} puncte")
            print(f"   Fișier: {calibration_file}")
            print(f"   Range: {real_distances.min():.1f}m - {real_distances.max():.1f}m")
            return {
                'pixel_values': pixel_values,
                'real_distances': real_distances,
                'source_file': calibration_file,
            }
        except Exception as error:
            print(f"⚠️  Profil {profile_name} invalid în {calibration_file}: {error}")

    return None


def refresh_calibration_profiles():
    """Încarcă/reîncarcă profilurile de calibrare disponibile."""
    global calibration_profiles, active_calibration_profile

    base_dir = os.path.dirname(__file__)
    calibration_dir = os.path.join(base_dir, 'calibration')
    room_yaml = os.path.join(calibration_dir, 'depth_calibration_new.yaml')
    corridor_yaml = os.path.join(calibration_dir, 'depth_calibration_corridor.yaml')
    legacy_json = os.path.join(calibration_dir, 'depth_calibration.json')

    old_room_yaml = os.path.join(base_dir, 'depth_calibration_new.yaml')
    old_corridor_yaml = os.path.join(base_dir, 'depth_calibration_corridor.yaml')
    old_legacy_json = os.path.join(base_dir, 'depth_calibration.json')

    loaded_profiles = {}

    room_profile = _load_profile_from_candidates('room', [room_yaml, legacy_json, old_room_yaml, old_legacy_json])
    if room_profile:
        loaded_profiles['room'] = room_profile

    corridor_profile = _load_profile_from_candidates(
        'corridor',
        [corridor_yaml, legacy_json, old_corridor_yaml, old_legacy_json],
    )
    if corridor_profile:
        loaded_profiles['corridor'] = corridor_profile

    if not loaded_profiles:
        print("⚠️  Nu există profil de calibrare valid (room/corridor)")

    with calibration_lock:
        calibration_profiles = loaded_profiles
        if active_calibration_profile not in calibration_profiles:
            if 'corridor' in calibration_profiles:
                active_calibration_profile = 'corridor'
            elif 'room' in calibration_profiles:
                active_calibration_profile = 'room'


def set_active_calibration_profile(profile_name):
    """Schimbă profilul activ fără restartul pipeline-ului."""
    global active_calibration_profile
    with calibration_lock:
        if profile_name not in calibration_profiles:
            available = sorted(list(calibration_profiles.keys()))
            return False, f"Profil inexistent: {profile_name}", available

        active_calibration_profile = profile_name
        return True, f"Profil activ setat: {profile_name}", sorted(list(calibration_profiles.keys()))


def get_calibration_status():
    with calibration_lock:
        profiles = {
            name: {
                'points': int(len(data['pixel_values'])),
                'source_file': data['source_file'],
            }
            for name, data in calibration_profiles.items()
        }
        return {
            'active_profile': active_calibration_profile,
            'profiles': profiles,
            'available_profiles': sorted(list(calibration_profiles.keys())),
        }


def _get_active_calibration_data():
    with calibration_lock:
        profile_data = calibration_profiles.get(active_calibration_profile)
        if profile_data is None:
            return None, None, None
        return (
            profile_data['pixel_values'],
            profile_data['real_distances'],
            active_calibration_profile,
        )


def load_depth_calibration():
    """Compat: returnează profilul activ curent."""
    if not calibration_profiles:
        refresh_calibration_profiles()

    pixel_values, real_distances, profile_name = _get_active_calibration_data()
    if pixel_values is None or real_distances is None:
        print("⚠️  Nu s-a putut încărca calibrarea activă")
        return None, None

    print(f"📏 Profil calibrare activ: {profile_name}")
    return pixel_values, real_distances


def init_depth_model():
    """
    Inițializează modelul Depth Anything V2 (lazy load).
    Prioritate: metric indoor (max_depth=20) > relative vits.

    Checkpoint-uri căutate (în ordine):
      checkpoints/depth_anything_v2_metric_indoor_vits.pth   ← metric indoor (NYUv2)
      checkpoints/depth_anything_v2_metric_hypersim_vits.pth ← metric hypersim
      checkpoints/depth_anything_v2_vits.pth                 ← relative (fallback)

    Model metric → output direct în metri (0–20m), nu necesită calibrare pentru SLAM.
    Model relative → output arbitrar, se calibrează via interp() pentru navigație.
    """
    global depth_model, depth_model_is_metric

    if depth_model is not None:
        return depth_model

    print("🧠 Încărcare model Depth Anything V2...")

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"📱 Device: {device}")

    base_ckpt_dir = os.path.join(os.path.dirname(__file__), 'Depth-Anything-V2', 'checkpoints')

    model_config = {'encoder': 'vits', 'features': 64, 'out_channels': [48, 96, 192, 384]}

    # Caute checkpoint metric indoor mai întâi
    metric_candidates = [
        ('depth_anything_v2_metric_indoor_vits.pth',   20.0),  # fine-tuned NYUv2 indoor
        ('depth_anything_v2_metric_hypersim_vits.pth', 20.0),  # fine-tuned Hypersim indoor/general
    ]
    relative_candidate = 'depth_anything_v2_vits.pth'

    chosen_path = None
    is_metric = False
    chosen_max_depth = None

    for fname, max_d in metric_candidates:
        candidate = os.path.join(base_ckpt_dir, fname)
        if os.path.exists(candidate):
            chosen_path = candidate
            is_metric = True
            chosen_max_depth = max_d
            print(f"✅ Checkpoint metric indoor găsit: {fname} (max_depth={max_d}m)")
            break

    if chosen_path is None:
        chosen_path = os.path.join(base_ckpt_dir, relative_candidate)
        if not os.path.exists(chosen_path):
            print(f"❌ EROARE: Niciun checkpoint Depth Anything V2 găsit în {base_ckpt_dir}")
            print(f"   Descarcă de la: https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Indoor-Small")
            return None
        print(f"⚠️  Checkpoint metric nu există → fallback la relative: {relative_candidate}")
        print(f"   Pentru SLAM mai precis descarcă: depth_anything_v2_metric_indoor_vits.pth")

    if is_metric:
        depth_model = DepthAnythingV2(**model_config, max_depth=chosen_max_depth)
    else:
        depth_model = DepthAnythingV2(**model_config)

    depth_model.load_state_dict(torch.load(chosen_path, map_location=device))
    depth_model = depth_model.to(device).eval()
    depth_model_is_metric = is_metric

    mode_str = f'metric indoor (0–{chosen_max_depth}m)' if is_metric else 'relative (calibrare necesară)'
    print(f"✅ Model Depth Anything V2 [{mode_str}] încărcat cu succes")
    return depth_model


def _process_depth_frames_loop():
    """Thread pentru procesarea depth maps cu calibrare."""
    global is_streaming, last_depth_snapshot, last_raw_frame_snapshot, last_depth_meters_snapshot
    global last_depth_mid_threshold, last_sampling_points, last_sampling_distances, _nav_measure_mode_logged

    print("🎨 Thread depth processing pornit")

    model = init_depth_model()
    if model is None:
        print("❌ Nu s-a putut inițializa modelul de depth")
        return

    refresh_calibration_profiles()
    active_profile_logged = None

    import matplotlib
    cmap = matplotlib.colormaps.get_cmap('Spectral_r')

    frame_count = 0
    skip_frames = 3
    last_depth_colored = None

    while not stop_event.is_set() and is_streaming:
        try:
            if not frame_queue.empty():
                frame_count += 1
                if frame_count % skip_frames != 0:
                    if last_depth_colored is not None and not depth_queue.full():
                        try:
                            depth_queue.put_nowait(last_depth_colored)
                        except:
                            pass
                    time.sleep(0.02)
                    continue

                frame = list(frame_queue.queue)[-1]

                if frame is not None:
                    with snapshot_lock:
                        last_raw_frame_snapshot = frame.copy()

                    pixel_vals, real_dists, active_profile_name = _get_active_calibration_data()
                    use_calibration = pixel_vals is not None and real_dists is not None

                    if use_calibration:
                        min_dist = float(real_dists.min())
                        max_dist = float(real_dists.max())
                        if active_profile_logged != active_profile_name:
                            print(f"📏 Profil calibrare activ: {active_profile_name} ({min_dist:.1f}m - {max_dist:.1f}m)")
                            active_profile_logged = active_profile_name
                    elif active_profile_logged != '__none__':
                        print("⚠️  Folosesc normalizare automată (fără calibrare activă)")
                        active_profile_logged = '__none__'

                    h, w = frame.shape[:2]
                    if w > 640:
                        scale = 640 / w
                        frame_small = cv2.resize(frame, (640, int(h * scale)))
                    else:
                        frame_small = frame

                    # Trimitem frame-ul la AI Analyzer daca scanarea este activa
                    ai_analyzer.get_analyzer().process_frame(frame)

                    with torch.no_grad():
                        depth = model.infer_image(frame_small, 384)

                    if frame_small.shape[:2] != frame.shape[:2]:
                        depth = cv2.resize(depth, (w, h))

                    # ---- EXPORT PENTRU STAIR CLIMBER (Identic Standalone) ----
                    # DA2 relativ = disparity (valoare mare -> aproape).
                    # Convertim la depth metric-like (valoare mare -> departe).
                    d_min_raw = float(depth.min())
                    d_max_raw = float(depth.max())
                    if d_max_raw > d_min_raw:
                        d_rel = 1.0 - (depth - d_min_raw) / (d_max_raw - d_min_raw)
                        d_rel = d_rel * 7.7 + 0.3
                    else:
                        d_rel = np.full_like(depth, 2.0, dtype=np.float32)

                    if controller_ref:
                        tello_obj = getattr(controller_ref, 'tello', controller_ref)
                        tello_obj.depth_frame = d_rel.copy()
                    # -------------------------------------------------------------

                    if use_calibration:
                        depth_normalized = (depth - depth.min()) / (depth.max() - depth.min()) * 255.0
                        depth_inverted = 255 - depth_normalized
                        depth_meters = np.interp(depth_inverted, pixel_vals, real_dists)
                        depth_meters_clipped = np.clip(depth_meters, min_dist, max_dist)
                        mid_threshold = (min_dist + max_dist) / 2.0
                        full_frame_blue_ratio = float(np.mean(depth_meters_clipped >= mid_threshold))
                        navigation.set_depth_global_metrics(
                            {
                                'full_frame_blue_ratio': full_frame_blue_ratio,
                                'mid_threshold_m': float(mid_threshold),
                                'frame_w': int(w),
                                'frame_h': int(h),
                            }
                        )
                        depth_for_color = (depth_meters_clipped - min_dist) / (max_dist - min_dist)
                        depth_for_color_inverted = 1.0 - depth_for_color
                        depth_colored = (cmap(depth_for_color_inverted)[:, :, :3] * 255)[:, :, ::-1].astype(np.uint8)

                        depth_with_overlay = depth_colored.copy()

                        # Punct de măsurare mutat mai sus în cadru (~1/3 din înălțime), mai aproape de tavan
                        center_y = int(h * 0.33)
                        center_x = w // 2
                        left_x = 50
                        right_x = w - 50

                        def get_distance_at(y, x):
                            y1, y2 = max(0, y - 2), min(h, y + 3)
                            x1, x2 = max(0, x - 2), min(w, x + 3)
                            return np.median(depth_meters[y1:y2, x1:x2])

                        dist_left = get_distance_at(center_y, left_x)
                        dist_right = get_distance_at(center_y, right_x)
                        dist_center = get_distance_at(center_y, center_x)

                        nav_measure_mode = os.environ.get(
                            "DEPTH_NAV_MEASURE_MODE", "mean3"
                        ).strip().lower()

                        # Compatibilitate retroactivă cu setarea veche.
                        center_only_nav_mode = (
                            os.environ.get("DEPTH_NAV_USE_CENTER_ONLY", "0").strip().lower()
                            in ("1", "true", "yes", "on")
                        )
                        if center_only_nav_mode:
                            nav_measure_mode = "center"

                        if nav_measure_mode not in ("edges", "center", "mean3"):
                            nav_measure_mode = "edges"

                        if _nav_measure_mode_logged != nav_measure_mode:
                            if nav_measure_mode == "center":
                                print("📍 DEPTH_NAV_MEASURE_MODE=center -> navigație pe punctul central")
                            elif nav_measure_mode == "mean3":
                                print("📍 DEPTH_NAV_MEASURE_MODE=mean3 -> navigație pe media (stânga+centru+dreapta)")
                            else:
                                print("📍 DEPTH_NAV_MEASURE_MODE=edges -> navigație pe distanțe laterale (stânga/dreapta)")
                            _nav_measure_mode_logged = nav_measure_mode

                        # Expune distanțele pentru navigație/măsurători:
                        # - edges: left/right reale (comportament implicit existent)
                        # - center: center pentru ambele canale
                        # - mean3: media (left+center+right)/3 pentru ambele canale
                        sample_ts = time.time()
                        if nav_measure_mode == "center":
                            nav_left = float(dist_center)
                            nav_right = float(dist_center)
                        elif nav_measure_mode == "mean3":
                            mean3 = float((dist_left + dist_center + dist_right) / 3.0)
                            nav_left = mean3
                            nav_right = mean3
                        else:
                            nav_left = float(dist_left)
                            nav_right = float(dist_right)

                        navigation.set_edge_distances(nav_left, nav_right, sample_timestamp=sample_ts)

                        last_sampling_points = {
                            'left': (left_x, center_y),
                            'center': (center_x, center_y),
                            'right': (right_x, center_y),
                        }
                        last_sampling_distances = {
                            'left': float(dist_left),
                            'center': float(dist_center),
                            'right': float(dist_right),
                        }

                        font = cv2.FONT_HERSHEY_SIMPLEX
                        font_scale = 0.6
                        thickness = 2

                        cv2.circle(depth_with_overlay, (center_x, center_y), 8, (255, 255, 255), 2)
                        cv2.circle(depth_with_overlay, (center_x, center_y), 9, (0, 0, 0), 3)
                        text = f"{dist_center:.2f}m"
                        (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
                        cv2.rectangle(depth_with_overlay, (center_x - tw // 2 - 5, center_y - 35),
                                      (center_x + tw // 2 + 5, center_y - 10), (0, 0, 0), -1)
                        cv2.putText(depth_with_overlay, text, (center_x - tw // 2, center_y - 15),
                                    font, font_scale, (255, 255, 255), thickness)

                        cv2.circle(depth_with_overlay, (left_x, center_y), 6, (255, 255, 255), 2)
                        cv2.circle(depth_with_overlay, (left_x, center_y), 7, (0, 0, 0), 3)
                        text = f"{dist_left:.2f}m"
                        (tw, th), _ = cv2.getTextSize(text, font, font_scale - 0.1, thickness - 1)
                        cv2.rectangle(depth_with_overlay, (left_x - tw // 2 - 3, center_y - 30),
                                      (left_x + tw // 2 + 3, center_y - 10), (0, 0, 0), -1)
                        cv2.putText(depth_with_overlay, text, (left_x - tw // 2, center_y - 15),
                                    font, font_scale - 0.1, (255, 255, 255), thickness - 1)

                        cv2.circle(depth_with_overlay, (right_x, center_y), 6, (255, 255, 255), 2)
                        cv2.circle(depth_with_overlay, (right_x, center_y), 7, (0, 0, 0), 3)
                        text = f"{dist_right:.2f}m"
                        (tw, th), _ = cv2.getTextSize(text, font, font_scale - 0.1, thickness - 1)
                        cv2.rectangle(depth_with_overlay, (right_x - tw // 2 - 3, center_y - 30),
                                      (right_x + tw // 2 + 3, center_y - 10), (0, 0, 0), -1)
                        cv2.putText(depth_with_overlay, text, (right_x - tw // 2, center_y - 15),
                                    font, font_scale - 0.1, (255, 255, 255), thickness - 1)

                        frame_center_x, frame_center_y = w // 2, h // 2

                        far_threshold_min = 1.7
                        far_threshold_max = 6.0
                        mask_far = ((depth_meters >= far_threshold_min) &
                                    (depth_meters <= far_threshold_max)).astype(np.uint8) * 255

                        kernel = np.ones((7, 7), np.uint8)
                        mask_far = cv2.morphologyEx(mask_far, cv2.MORPH_CLOSE, kernel, iterations=3)
                        mask_far = cv2.morphologyEx(mask_far, cv2.MORPH_OPEN, kernel, iterations=1)
                        mask_far = cv2.dilate(mask_far, kernel, iterations=2)

                        contours, _ = cv2.findContours(mask_far, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                        if contours:
                            valid_rects = []
                            min_area = 8000

                            for cnt in contours:
                                area = cv2.contourArea(cnt)
                                if area < min_area:
                                    continue

                                peri = cv2.arcLength(cnt, True)
                                approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)

                                if len(approx) >= 4:
                                    x, y, w_rect, h_rect = cv2.boundingRect(cnt)
                                    aspect_ratio = float(w_rect) / h_rect if h_rect > 0 else 0

                                    if 0.35 < aspect_ratio < 2.0:
                                        min_height_ratio = 0.3
                                        if h_rect < (h * min_height_ratio):
                                            continue

                                        margin_top = h * 0.2
                                        margin_bottom = h * 0.2

                                        if y > margin_top:
                                            continue
                                        if (y + h_rect) < (h - margin_bottom):
                                            continue

                                        y1, y2 = max(0, y), min(h, y + h_rect)
                                        x1, x2 = max(0, x), min(w, x + w_rect)

                                        roi = depth_meters[y1:y2, x1:x2]
                                        if roi.size > 0:
                                            close_threshold = 1.5
                                            close_points = np.sum(roi < close_threshold)
                                            total_points = roi.size
                                            close_percentage = (close_points / total_points) * 100 if total_points > 0 else 0

                                            if close_percentage > 50:
                                                continue

                                            # Filtru anti-fals pozitiv:
                                            # o ușă validă are de obicei două muchii verticale mai abrupte
                                            # (stânga + dreapta), nu doar un gradient albastru uniform.
                                            roi_h, roi_w = roi.shape[:2]
                                            if roi_h < 14 or roi_w < 14:
                                                continue

                                            grad_x = np.abs(np.diff(roi, axis=1))
                                            if grad_x.shape[1] < 6:
                                                continue

                                            edge_band = max(2, int(roi_w * 0.12))
                                            edge_band = min(edge_band, max(2, grad_x.shape[1] // 3))

                                            left_grad = grad_x[:, :edge_band]
                                            right_grad = grad_x[:, -edge_band:]
                                            if grad_x.shape[1] > (2 * edge_band):
                                                center_grad = grad_x[:, edge_band:-edge_band]
                                            else:
                                                center_grad = grad_x

                                            left_p90 = float(np.percentile(left_grad, 90))
                                            right_p90 = float(np.percentile(right_grad, 90))
                                            center_p90 = float(np.percentile(center_grad, 90))

                                            left_ratio = left_p90 / (center_p90 + 1e-6)
                                            right_ratio = right_p90 / (center_p90 + 1e-6)

                                            edge_strength = min(left_p90, right_p90)
                                            edge_ratio = min(left_ratio, right_ratio)

                                            border_margin = max(8, int(0.06 * w))
                                            touches_left_border = x <= border_margin
                                            touches_right_border = (x + w_rect) >= (w - border_margin)
                                            touches_border = touches_left_border or touches_right_border

                                            two_edge_ok = (edge_strength >= 0.02) and (edge_ratio >= 1.20)

                                            one_edge_strength = max(left_p90, right_p90)
                                            one_edge_ratio = max(left_ratio, right_ratio)
                                            one_edge_ok = touches_border and (one_edge_strength >= 0.03) and (one_edge_ratio >= 1.45)

                                            if not (two_edge_ok or one_edge_ok):
                                                continue

                                            if one_edge_ok and not two_edge_ok:
                                                edge_strength = one_edge_strength
                                                edge_ratio = one_edge_ratio

                                        valid_rects.append({
                                            'contour': cnt,
                                            'area': area,
                                            'bbox': (x, y, w_rect, h_rect),
                                            'center': (x + w_rect // 2, y + h_rect // 2),
                                            'edge_strength': edge_strength,
                                            'edge_ratio': edge_ratio,
                                            'partial_door': one_edge_ok and not two_edge_ok,
                                        })

                            if valid_rects:
                                largest_rect = max(valid_rects, key=lambda r: (r['edge_ratio'], r['area']))

                                x, y, w_rect, h_rect = largest_rect['bbox']
                                center_x, center_y = largest_rect['center']

                                bbox_area_ratio = float((w_rect * h_rect) / float(w * h))

                                roi_depth = depth_meters_clipped[y : y + h_rect, x : x + w_rect]
                                blue_ratio = 0.0
                                if roi_depth.size > 0:
                                    blue_ratio = float(np.mean(roi_depth >= mid_threshold))

                                navigation.set_target_detection(
                                    detected=True,
                                    center=(center_x, center_y),
                                    bbox=(x, y, w_rect, h_rect),
                                    dimensions=(w, h),
                                    metrics={
                                        'bbox_area_ratio': bbox_area_ratio,
                                        'blue_ratio': blue_ratio,
                                        'full_frame_blue_ratio': full_frame_blue_ratio,
                                    },
                                )

                                cv2.rectangle(depth_with_overlay, (x, y), (x + w_rect, y + h_rect),
                                              (0, 255, 0), 1)
                                cv2.circle(depth_with_overlay, (center_x, center_y), 8, (0, 255, 0), -1)
                                cv2.circle(depth_with_overlay, (center_x, center_y), 10, (255, 255, 255), 1)
                                label = f"TARGET: {center_x},{center_y}"
                                cv2.putText(depth_with_overlay, label, (x, y - 10),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
                                mode = "P" if largest_rect.get('partial_door') else "F"
                                edge_label = f"{mode} E:{largest_rect['edge_strength']:.3f} R:{largest_rect['edge_ratio']:.2f}"
                                cv2.putText(depth_with_overlay, edge_label, (x, y + h_rect + 20),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                                metric_label = f"A:{bbox_area_ratio:.3f} B:{blue_ratio:.3f}"
                                cv2.putText(depth_with_overlay, metric_label, (x, y + h_rect + 38),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                                cv2.line(depth_with_overlay, (center_x - 20, center_y),
                                         (center_x + 20, center_y), (0, 255, 0), 1)
                                cv2.line(depth_with_overlay, (center_x, center_y - 20),
                                         (center_x, center_y + 20), (0, 255, 0), 1)
                            else:
                                navigation.set_target_detection(False)
                        else:
                            navigation.set_target_detection(False)

                        cv2.line(depth_with_overlay, (frame_center_x - 30, frame_center_y),
                                 (frame_center_x + 30, frame_center_y), (255, 255, 255), 1)
                        cv2.line(depth_with_overlay, (frame_center_x, frame_center_y - 30),
                                 (frame_center_x, frame_center_y + 30), (255, 255, 255), 1)
                        cv2.circle(depth_with_overlay, (frame_center_x, frame_center_y), 3, (255, 255, 255), -1)

                        depth_colored = depth_with_overlay
                    else:
                        navigation.set_depth_global_metrics(None)
                        depth_normalized = (depth - depth.min()) / (depth.max() - depth.min()) * 255.0
                        depth_uint8 = depth_normalized.astype(np.uint8)
                        depth_colored = (cmap(depth_uint8)[:, :, :3] * 255)[:, :, ::-1].astype(np.uint8)

                    last_depth_snapshot = depth_colored.copy()
                    with snapshot_lock:
                        last_depth_snapshot = depth_colored.copy()
                        if use_calibration:
                            last_depth_meters_snapshot = depth_meters_clipped.copy()
                            last_depth_mid_threshold = float((min_dist + max_dist) / 2.0)
                        else:
                            last_depth_meters_snapshot = None
                            last_depth_mid_threshold = None
                    last_depth_colored = depth_colored.copy()

                    if depth_queue.full():
                        try:
                            depth_queue.get_nowait()
                        except:
                            pass

                    depth_queue.put(depth_colored)

                    if frame_count % 100 == 0:
                        print("🎨 Depth processing activ (1/5 frames)")

        except Exception as e:
            print(f"❌ Eroare procesare depth: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(0.1)

        time.sleep(0.01)

    print("🎨 Thread depth processing oprit")


def _capture_frames_loop():
    """Thread pentru captura continuă de frame-uri de la dronă."""
    global is_streaming

    print("📹 Thread captură frame-uri pornit")
    frame_count = 0

    while not stop_event.is_set() and is_streaming:
        try:
            if controller_ref:
                frame = controller_ref.get_frame_bgr()

                if frame is not None:
                    try:
                        frame_for_stream = ai_analyzer.get_analyzer().annotate_live_frame(frame)
                    except Exception:
                        frame_for_stream = frame

                    frame_count += 1

                    if frame_queue.full():
                        try:
                            frame_queue.get_nowait()
                        except:
                            pass

                    frame_queue.put(frame_for_stream)

                    if frame_count % 100 == 0:
                        print(f"📊 Frame-uri capturate: {frame_count}")

            time.sleep(0.033)
        except Exception as e:
            print(f"❌ Eroare în capture loop: {e}")
            time.sleep(0.1)

    print("📹 Thread captură frame-uri oprit")


def start_streaming(controller):
    """Pornește pipeline-ul de video/depth."""
    global is_streaming, controller_ref, capture_thread, depth_thread

    if is_streaming:
        return

    controller_ref = controller
    stop_event.clear()
    is_streaming = True

    init_depth_model()

    capture_thread = threading.Thread(target=_capture_frames_loop, daemon=True)
    depth_thread = threading.Thread(target=_process_depth_frames_loop, daemon=True)
    capture_thread.start()
    depth_thread.start()


def stop_streaming():
    """Oprește pipeline-ul și thread-urile asociate."""
    global is_streaming, controller_ref

    is_streaming = False
    stop_event.set()

    if capture_thread and capture_thread.is_alive():
        capture_thread.join(timeout=2)

    if depth_thread and depth_thread.is_alive():
        depth_thread.join(timeout=2)

    controller_ref = None


def shutdown_pipeline():
    """Alias semantic pentru shutdown complet pipeline."""
    stop_streaming()


def is_streaming_active():
    return is_streaming


def start_ai_scan(room_idx, scan_mode="medium"):
    """Pornește scanarea AI (detectarea YOLO) pe frame-urile pipeline-ului."""
    print(f"🎬 Stream Pipeline: Activare AI Scan pentru camera {room_idx} (mode={scan_mode})")
    ai_analyzer.get_analyzer().start_scan_session(room_idx, scan_mode=scan_mode)


def set_person_capture_active(is_active):
    """Controlează dacă detecțiile de persoane sunt contorizate/salvate în raport."""
    ai_analyzer.get_analyzer().set_person_capture_active(is_active)


def stop_ai_scan():
    """Oprește scanarea AI și returnează calea către raport."""
    print("🛑 Stream Pipeline: Oprire AI Scan")
    return ai_analyzer.get_analyzer().stop_scan_session_and_report()


def set_room_label_for_report(room_idx, room_label, ocr_results=None, ocr_frame_paths=None):
    """Setează label-ul OCR pentru raportul camerei curente/următoare."""
    candidates_count = len(ocr_results or [])
    print(
        f"🧾 Stream Pipeline: room_label primit pentru camera {room_idx} -> "
        f"'{room_label}' (candidates={candidates_count})"
    )
    ai_analyzer.get_analyzer().set_room_label(room_idx, room_label, ocr_results, ocr_frame_paths=ocr_frame_paths)


def set_room_ocr_frame_paths_for_report(room_idx, ocr_frame_paths):
    """Atașează la raport frame-urile trimise la OCR, indiferent de rezultatul OCR (debug)."""
    ai_analyzer.get_analyzer().set_room_ocr_frame_paths(room_idx, ocr_frame_paths)


def start_slam_session(mission_id=None):
    pass


def stop_slam_session():
    pass


def get_slam_status():
    return {}


def get_slam_map():
    return None


def set_room_pre_entry_analysis_for_report(room_idx, analysis_payload):
    """Setează analiza AI pre-entry pentru raportul camerei curente/următoare."""
    level = None
    if isinstance(analysis_payload, dict):
        level = analysis_payload.get("level")

    print(
        f"🧾 Stream Pipeline: pre-entry AI analysis pentru camera {room_idx} "
        f"(level={level})"
    )
    ai_analyzer.get_analyzer().set_room_pre_entry_analysis(room_idx, analysis_payload)


def generate_frames():
    """Generator pentru streaming MJPEG video."""
    print("🎬 Generator frame-uri pornit")

    while not stop_event.is_set():
        if not frame_queue.empty():
            try:
                frame = list(frame_queue.queue)[-1]

                if frame is not None:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    _, buffer = cv2.imencode('.jpg', frame_rgb, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    frame_bytes = buffer.tobytes()

                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n'
                           b'Access-Control-Allow-Origin: *\r\n\r\n' +
                           frame_bytes + b'\r\n')
            except Exception as e:
                print(f"❌ Eroare la generare frame: {e}")

        time.sleep(0.033)

    print("🎬 Generator frame-uri oprit")


def generate_depth_frames():
    """Generator pentru streaming MJPEG depth."""
    print("🎨 Generator depth frames pornit")

    while not stop_event.is_set():
        import navigation.state as nav_state
        depth_frame = None

        # 1. INJECT STAIR CLIMBER DEBUG FRAME IF AVAILABLE
        if getattr(nav_state, 'debug_frame', None) is not None:
            depth_frame = nav_state.debug_frame
        # 2. OTHERWISE USE DEPTH QUEUE
        elif not depth_queue.empty():
            try:
                depth_frame = list(depth_queue.queue)[-1]
            except Exception:
                pass

        if depth_frame is not None:
            try:
                _, buffer = cv2.imencode('.jpg', depth_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frame_bytes = buffer.tobytes()

                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n'
                       b'Access-Control-Allow-Origin: *\r\n\r\n' +
                       frame_bytes + b'\r\n')
            except Exception as e:
                print(f"❌ Eroare la generare depth frame/debug frame: {e}")

def get_latest_frame_jpeg(quality=90):
    """Returnează ultimul frame disponibil, encodat JPEG."""
    if frame_queue.empty():
        return None

    frame = list(frame_queue.queue)[-1]
    if frame is None:
        return None

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    _, buffer = cv2.imencode('.jpg', frame_rgb, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buffer.tobytes()


def save_distance_hold_debug_frames(tag, target_bbox=None, target_ratio=None, ratio_ema=None, metric_method=None):
    """Salvează snapshot-uri utile pentru FAZA 1.5: raw, depth overlay și threshold near/far."""
    with snapshot_lock:
        raw_frame = last_raw_frame_snapshot.copy() if last_raw_frame_snapshot is not None else None
        depth_overlay = last_depth_snapshot.copy() if last_depth_snapshot is not None else None
        depth_meters = last_depth_meters_snapshot.copy() if last_depth_meters_snapshot is not None else None
        mid_threshold = last_depth_mid_threshold

    if raw_frame is None and depth_overlay is None and depth_meters is None:
        return None

    output_dir = os.path.join(os.path.dirname(__file__), 'reports', 'distance_hold_frames')
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    safe_tag = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in str(tag or 'phase1_5'))
    prefix = f"{timestamp}_{safe_tag}"

    raw_path = None
    depth_path = None
    threshold_path = None

    if raw_frame is not None:
        raw_path = os.path.join(output_dir, f"{prefix}_raw.jpg")
        cv2.imwrite(raw_path, raw_frame)

    if depth_overlay is not None:
        depth_path = os.path.join(output_dir, f"{prefix}_depth.jpg")
        cv2.imwrite(depth_path, depth_overlay)

    if depth_meters is not None and mid_threshold is not None:
        threshold_mask_far = depth_meters >= float(mid_threshold)
        full_frame_blue_ratio_vis = float(np.mean(threshold_mask_far))
        threshold_vis = np.zeros((depth_meters.shape[0], depth_meters.shape[1], 3), dtype=np.uint8)
        threshold_vis[threshold_mask_far] = (255, 0, 0)   # depărtat = albastru (BGR)
        threshold_vis[~threshold_mask_far] = (0, 0, 255)  # aproape = roșu (BGR)

        if target_bbox is not None and len(target_bbox) == 4:
            try:
                x, y, w_rect, h_rect = [int(v) for v in target_bbox]
                cv2.rectangle(threshold_vis, (x, y), (x + w_rect, y + h_rect), (255, 255, 255), 2)
            except Exception:
                pass

        labels = []
        if metric_method:
            labels.append(f"metric={metric_method}")
        if ratio_ema is not None:
            labels.append(f"ratio_ema={float(ratio_ema):.3f}")
        if target_ratio is not None:
            labels.append(f"target={float(target_ratio):.3f}")
        labels.append(f"full_blue={full_frame_blue_ratio_vis:.3f}")
        labels.append(f"thr={float(mid_threshold):.2f}m")

        text = " | ".join(labels)
        cv2.rectangle(threshold_vis, (12, 12), (min(threshold_vis.shape[1] - 12, 920), 50), (0, 0, 0), -1)
        cv2.putText(threshold_vis, text, (18, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        threshold_path = os.path.join(output_dir, f"{prefix}_threshold.jpg")
        cv2.imwrite(threshold_path, threshold_vis)

    return {
        'raw': raw_path,
        'depth': depth_path,
        'threshold': threshold_path,
    }


def save_measurement_snapshot(wall_name, measured_distance, point_name='center'):
    """Salvează un snapshot depth pentru o măsurătoare punctuala (front/right/left)."""
    if last_depth_snapshot is None:
        return None

    snapshot = last_depth_snapshot.copy()
    output_dir = os.path.join(os.path.dirname(__file__), 'measurement_snapshots')
    os.makedirs(output_dir, exist_ok=True)

    points = last_sampling_points or {}
    distances = last_sampling_distances or {}
    point = points.get(point_name)

    if point is not None:
        px, py = point
        cv2.circle(snapshot, (px, py), 10, (255, 255, 255), 2)
        cv2.circle(snapshot, (px, py), 5, (0, 0, 255), -1)

    distance_text = "N/A" if measured_distance is None else f"{float(measured_distance):.2f}m"
    sampled_text = ""
    if point_name in distances:
        sampled_text = f" | sample_{point_name}: {distances[point_name]:.2f}m"

    label = f"{wall_name.upper()} = {distance_text}{sampled_text}"
    cv2.rectangle(snapshot, (12, 12), (min(snapshot.shape[1] - 12, 520), 52), (0, 0, 0), -1)
    cv2.putText(snapshot, label, (18, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    file_name = f"{timestamp}_{wall_name}.jpg"
    file_path = os.path.join(output_dir, file_name)
    cv2.imwrite(file_path, snapshot)
    print(f"📸 Snapshot măsurătoare salvat: {file_path}")
    return file_path
def generate_stair_da2_frames():
    while not stop_event.is_set():
        import navigation.state as nav_state
        frame = getattr(nav_state, 'stair_frame_da2', None)
        if frame is not None:
            try:
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\nContent-Type: image/jpeg\r\nAccess-Control-Allow-Origin: *\r\n\r\n' + frame_bytes + b'\r\n')
            except Exception:
                pass
        time.sleep(0.05)

def generate_stair_sobel_frames():
    while not stop_event.is_set():
        import navigation.state as nav_state
        frame = getattr(nav_state, 'stair_frame_sobel', None)
        if frame is not None:
            try:
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\nContent-Type: image/jpeg\r\nAccess-Control-Allow-Origin: *\r\n\r\n' + frame_bytes + b'\r\n')
            except Exception:
                pass
        time.sleep(0.05)

def generate_stair_gabor_frames():
    while not stop_event.is_set():
        import navigation.state as nav_state
        frame = getattr(nav_state, 'stair_frame_gabor', None)
        if frame is not None:
            try:
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\nContent-Type: image/jpeg\r\nAccess-Control-Allow-Origin: *\r\n\r\n' + frame_bytes + b'\r\n')
            except Exception:
                pass
        time.sleep(0.05)
