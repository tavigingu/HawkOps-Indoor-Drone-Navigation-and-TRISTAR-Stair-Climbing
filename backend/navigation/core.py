import threading
import time
import os
import base64
import json
import uuid
import urllib.error
import urllib.request
import numpy as np
import cv2

import navigation.state as nav_state
import navigation.mission_path as mission_path
from navigation.common import drone_stabilize
from navigation.scan_fast import execute_fast_scan
from navigation.scan_medium import execute_medium_scan
from navigation.scan_complex import execute_complex_scan


def start_autopilot(controller, scan_mode="medium", room_count=1, start_position="hallway", target_floor=1, stair_signals=None, stair_single_flight=False):
    """Validează precondițiile și pornește autopilotul în thread separat.
    
    Args:
        controller: conexiune la dronă
        scan_mode:
            - "fast": fără măsurători după intrare, rotații reale 90L-180R-90R + ieșire
            - "medium": scan simplificat (modul fast vechi)
            - "complex": 5-segment crab-style
        room_count:
            - numărul de camere ce vor fi verificate consecutiv
        start_position:
            - "hallway": start direct din hol (caută uși stânga/dreapta)
            - "stairwell": start din casa scării, înainte de a intra pe hol
    """
    if controller is None:
        raise ValueError("Nu există conexiune la dronă")

    if nav_state.autopilot_active:
        raise ValueError("Autopilot deja activ")
    
    if scan_mode not in ["fast", "medium", "complex"]:
        raise ValueError("scan_mode trebuie să fie 'fast', 'medium' sau 'complex'")

    if room_count < 1:
        raise ValueError("room_count trebuie să fie >= 1")

    nav_state.init_room_timeline(room_count)
    nav_state.autopilot_active = True

    autopilot_thread = threading.Thread(
        target=execute_autopilot,
        args=(controller, scan_mode, room_count, start_position, target_floor, stair_signals, stair_single_flight),
        daemon=True,
    )
    autopilot_thread.start()

    mode_labels = {
        "fast": "Fast Scan (orientare rapidă + exit)",
        "medium": "Medium Scan (360°)",
        "complex": "Complex Scan (5 segmente)",
    }
    mode_name = mode_labels.get(scan_mode, scan_mode)
    return {
        "message": f"Autopilot pornit - {mode_name} - camere: {room_count}",
        "room_count": room_count,
        "target_center": nav_state.target_center,
        "frame_dimensions": nav_state.frame_dimensions,
    }


def execute_autopilot(controller, scan_mode="medium", room_count=1, start_position="hallway", target_floor=1, stair_signals=None, stair_single_flight=False):
    """
    Funcție autopilot cu suport pentru trei moduri:
    - scan_mode="fast": fără măsurători după intrare, rotații reale 90L-180R-90R + ieșire
    - scan_mode="medium": 360° scan la centru + revenire simetrică (fostul fast)
    - scan_mode="complex": 5-segment crab-style perimetru (modul original)
    - start_position="hallway" sau "stairwell"
    """
    mission_path_error = None

    try:
        mission_path.reset_mission(scan_mode=scan_mode, room_count=room_count)
        print("\n" + "="*60)
        print("🤖 === AUTOPILOT PORNIT ===")
        print("="*60)
        mode_banner = {
            "fast": "⚡ FAST SCAN (orientare rapidă + exit)",
            "medium": "🛰️ MEDIUM SCAN (360°)",
            "complex": "🦀 COMPLEX SCAN (5 segmente)",
        }
        print(f"📡 MOD: {mode_banner.get(scan_mode, scan_mode)}")
        print(f"🏠 Camere de verificat: {room_count}")
        print(f"📍 Punct de start: {start_position.upper()}")
        print("\n📋 PLAN MISIUNE:")
        print("  FAZA 0: Căutare ușă (crab-style spre dreapta, dacă nu e detectată)")
        print("  FAZA 1: Aliniere laterală pe axa X (crab-style)")
        print("  FAZA 2: Avansare 1.8 metri înainte prin ușă")
        if scan_mode == "fast":
            print("  FAZA 3: Fără măsurători - orientare rapidă pentru ieșire")
        elif scan_mode == "medium":
            print("  FAZA 3a: Măsurători 3 pereți (simplificat)")
            print("  FAZA 3b: Centru cameră + 360° rota")
            print("  FAZA 3c: Revenire simetrică")
        else:
            print("  FAZA 3: Măsurători pereți (3 direcții cu rotații)")
            print("  FAZA 4: Crab-style 5 segmente perimetru")
        print("  FAZA 5: Revenire spre ușă + recentrare + ieșire 2.0m")
        print("  TRANZIȚIE: 180° pe hol + continuare crab-style spre dreapta")
        print("="*60 + "\n")

        try:
            import stream_pipeline
        except Exception:
            stream_pipeline = None

        def switch_depth_profile(profile_name, phase_label):
            if stream_pipeline is None:
                return
            try:
                ok, message, available = stream_pipeline.set_active_calibration_profile(profile_name)
                if ok:
                    print(f"🎚️  [{phase_label}] calibrare depth -> {profile_name}")
                else:
                    print(f"⚠️  [{phase_label}] nu pot seta profilul '{profile_name}': {message} | disponibile: {available}")
            except Exception as switch_err:
                print(f"⚠️  [{phase_label}] eroare la schimbare profil calibrare: {switch_err}")

        right_crab_fb_comp = 0  # crab lateral cât mai "curat" (fără diagonală înainte)

        def _read_env_int(name, default_value):
            try:
                return int(os.environ.get(name, str(default_value)))
            except Exception:
                return int(default_value)

        def _read_env_float(name, default_value):
            try:
                return float(os.environ.get(name, str(default_value)))
            except Exception:
                return float(default_value)

        distance_hold_enabled = (
            os.environ.get("ENTRY_DISTANCE_HOLD_ENABLED", "1").strip().lower()
            in ("1", "true", "yes", "on")
        )
        distance_hold_target_ratio = _read_env_float("ENTRY_DISTANCE_HOLD_TARGET_RATIO", 0.50)
        distance_hold_deadband = _read_env_float("ENTRY_DISTANCE_HOLD_DEADBAND", 0.05)
        distance_hold_ema_alpha = _read_env_float("ENTRY_DISTANCE_HOLD_EMA_ALPHA", 0.18)
        distance_hold_method = os.environ.get("ENTRY_DISTANCE_HOLD_METHOD", "full_frame_blue_ratio").strip().lower()
        distance_hold_accept_mode = os.environ.get("ENTRY_DISTANCE_HOLD_ACCEPT_MODE", "raw").strip().lower()
        distance_hold_fb_tick_speed = _read_env_int("ENTRY_DISTANCE_HOLD_FB_TICK_SPEED", 25)
        distance_hold_max_iterations = _read_env_int("ENTRY_DISTANCE_HOLD_MAX_ITERS", 12)
        distance_hold_stable_required = _read_env_int("ENTRY_DISTANCE_HOLD_STABLE_REQUIRED", 3)
        distance_hold_pulse_s = _read_env_float("ENTRY_DISTANCE_HOLD_PULSE_S", 0.35)
        distance_hold_pause_s = _read_env_float("ENTRY_DISTANCE_HOLD_PAUSE_S", 0.20)
        distance_hold_abort_on_fail = (
            os.environ.get("ENTRY_DISTANCE_HOLD_ABORT_ON_FAIL", "0").strip().lower()
            in ("1", "true", "yes", "on")
        )

        def hold_entry_distance_after_center(
            phase_label,
            target_ratio,
            deadband,
            ema_alpha,
            max_iterations,
            stable_required,
            pulse_s,
            pause_s,
            metric_method,
            accept_mode,
            tolerance_px=70,
        ):
            """Menține distanța față de ușă pe baza unei metrici depth (implicit full-frame)."""
            ratio_ema = None
            stable_hits = 0
            selected_metric = "full_frame_blue_ratio"

            if accept_mode not in ("raw", "ema"):
                print(f"   ℹ️ {phase_label}: accept_mode invalid '{accept_mode}', fallback='raw'")
                accept_mode = "raw"

            if metric_method != selected_metric:
                print(
                    f"   ℹ️ {phase_label}: ignor metric_method='{metric_method}' și folosesc strict '{selected_metric}'"
                )

            tick_speed = int(np.clip(abs(distance_hold_fb_tick_speed), 8, 35))

            def _compute_fb_speed(current_ratio):
                # Corecția utilizatorului: "când e foarte aproape, vede NUMAI golul albastru"
                # blue_ratio mare => ușa e PREA APROAPE => mergi în spate (-tick)
                # blue_ratio mic => ușa e PREA DEPARTE => mergi în față (+tick)
                ratio_error = target_ratio - current_ratio
                if abs(ratio_error) <= 0.003:
                    return 0
                
                # Curent prea mare (ex: 0.7 față de 0.5) => ratio_error < 0 => mergi ÎNAPOI (-tick_speed)
                # Curent prea mic (ex: 0.2 față de 0.5) => ratio_error > 0 => mergi ÎNAINTE (+tick_speed)
                fb_speed = tick_speed if ratio_error > 0 else -tick_speed
                return fb_speed

            for iteration in range(1, max_iterations + 1):
                depth_global_metrics = (
                    nav_state.depth_global_metrics if isinstance(nav_state.depth_global_metrics, dict) else {}
                )

                lower_bound = target_ratio - deadband
                upper_bound = target_ratio + deadband
                full_frame_blue_ratio = depth_global_metrics.get("full_frame_blue_ratio")
                try:
                    full_frame_blue_ratio = float(full_frame_blue_ratio) if full_frame_blue_ratio is not None else None
                except Exception:
                    full_frame_blue_ratio = None

                ratio_raw = full_frame_blue_ratio

                if ratio_raw is None or not np.isfinite(ratio_raw):
                    print(f"   ⏳ {phase_label}: metrica de distanță indisponibilă [{iteration}/{max_iterations}]")
                    controller.tello.send_rc_control(0, 0, 0, 0)
                    time.sleep(0.2)
                    continue

                if ratio_ema is None:
                    ratio_ema = ratio_raw
                else:
                    ratio_ema = ema_alpha * ratio_raw + (1.0 - ema_alpha) * ratio_ema

                # Telemetrie: salvăm variația EMA pentru statistici (nu afectează controlul)
                try:
                    mission_path.record_metric_sample("ratio_raw", ratio_raw)
                    mission_path.record_metric_sample("ratio_ema", ratio_ema)
                except Exception:
                    pass

                print(
                    f"   🔎 {phase_label}: iter={iteration}/{max_iterations} "
                    f"metric={selected_metric} "
                    f"(full_blue={full_frame_blue_ratio if full_frame_blue_ratio is not None else 'n/a'})"
                )

                control_ratio = ratio_raw if accept_mode == "raw" else ratio_ema
                ratio_error = target_ratio - control_ratio

                if control_ratio < lower_bound:
                    fb_speed = _compute_fb_speed(control_ratio)
                    stable_hits = 0
                    decision_reason = f"ratio_{accept_mode}<{lower_bound:.3f}"
                elif control_ratio > upper_bound:
                    fb_speed = _compute_fb_speed(control_ratio)
                    stable_hits = 0
                    decision_reason = f"ratio_{accept_mode}>{upper_bound:.3f}"
                else:
                    fb_speed = 0
                    stable_hits += 1
                    decision_reason = f"{lower_bound:.3f}<=ratio_{accept_mode}<={upper_bound:.3f}"

                if fb_speed > 0:
                    action = "înainte"
                elif fb_speed < 0:
                    action = "înapoi"
                else:
                    action = "hold"

                print(
                    f"   🎯 {phase_label}: ratio_raw={ratio_raw:.3f}, ratio_ema={ratio_ema:.3f}, "
                    f"control({accept_mode})={control_ratio:.3f}, "
                    f"target={target_ratio:.3f}±{deadband:.3f} (bounds={lower_bound:.3f}-{upper_bound:.3f}), "
                    f"err={ratio_error:+.3f} -> {action} (fb={fb_speed}, reason={decision_reason}) "
                    f"[{stable_hits}/{stable_required}]"
                )

                if stable_hits >= stable_required:
                    controller.tello.send_rc_control(0, 0, 0, 0)
                    time.sleep(0.15)
                    print(f"   ✅ {phase_label}: distanță stabilizată")
                    if stream_pipeline is not None:
                        try:
                            saved = stream_pipeline.save_distance_hold_debug_frames(
                                tag="entry_distance_lock",
                                target_bbox=None,
                                target_ratio=target_ratio,
                                ratio_ema=ratio_ema,
                                metric_method=selected_metric,
                            )
                            if saved:
                                print(
                                    "   💾 FAZA 1.5 snapshot-uri salvate: "
                                    f"raw={saved.get('raw')}, depth={saved.get('depth')}, threshold={saved.get('threshold')}"
                                )
                        except Exception as save_err:
                            print(f"   ⚠️ {phase_label}: nu pot salva snapshot-urile debug ({save_err})")
                    return True

                if fb_speed != 0:
                    print(f"   🕹️ {phase_label}: tick față/spate (fb={fb_speed}, pulse={pulse_s:.2f}s)")
                    controller.tello.send_rc_control(0, fb_speed, 0, 0)
                    time.sleep(pulse_s)
                    mission_path.record_timed_rc(0, fb_speed, 0, pulse_s, label="pre_entry_distance_hold")
                    controller.tello.send_rc_control(0, 0, 0, 0)
                    time.sleep(pause_s)
                else:
                    controller.tello.send_rc_control(0, 0, 0, 0)
                    time.sleep(0.15)

            print(f"   ⚠️ {phase_label}: timeout - distanța nu s-a stabilizat")
            controller.tello.send_rc_control(0, 0, 0, 0)
            time.sleep(0.15)
            return False

        def apply_ocr_response_to_report(room_idx, response_data, request_id, source_tag="direct", ocr_frame_paths=None):
            raw_results = response_data.get("results", []) if isinstance(response_data, dict) else []
            valid_results = [
                {
                    "text": str(item.get("text", "")).strip(),
                    "confidence": float(item.get("confidence", 0.0)),
                }
                for item in raw_results
                if isinstance(item, dict) and str(item.get("text", "")).strip()
            ]

            valid_results.sort(key=lambda item: item["confidence"], reverse=True)

            if not valid_results:
                print(
                    f"   ℹ️ [OCR][{request_id}] niciun text detectat "
                    f"(raw_results={len(raw_results)}, source={source_tag})"
                )
                return None

            best = valid_results[0]
            room_label = best["text"]
            print(
                f"   🏷️ [OCR][{request_id}] room_label='{room_label}' "
                f"(conf={best['confidence']:.2f}, candidates={len(valid_results)}, source={source_tag})"
            )

            stream_pipeline.set_room_label_for_report(room_idx, room_label, valid_results, ocr_frame_paths=ocr_frame_paths)
            print(f"   ✅ [OCR][{request_id}] label trimis către raport (camera={room_idx}, source={source_tag})")
            return room_label

        def dispatch_deferred_ocr_retry(room_idx, payload_bytes, ocr_url, request_id, ocr_frame_paths=None):
            if stream_pipeline is None:
                return

            deferred_retries = 8
            deferred_timeout_s = 20.0
            deferred_sleep_s = 6.0
            try:
                deferred_retries = int(os.environ.get("OCR_ROOM_LABEL_DEFERRED_RETRIES", "8"))
            except Exception:
                pass
            try:
                deferred_timeout_s = float(os.environ.get("OCR_ROOM_LABEL_DEFERRED_TIMEOUT_S", "20"))
            except Exception:
                pass
            try:
                deferred_sleep_s = float(os.environ.get("OCR_ROOM_LABEL_DEFERRED_SLEEP_S", "6"))
            except Exception:
                pass

            if deferred_retries < 1:
                deferred_retries = 1

            def _deferred_worker():
                print(
                    f"   🧵 [OCR][{request_id}] pornesc deferred retry "
                    f"(retries={deferred_retries}, timeout={deferred_timeout_s:.1f}s, sleep={deferred_sleep_s:.1f}s)"
                )
                for attempt_idx in range(deferred_retries):
                    request = urllib.request.Request(
                        ocr_url,
                        data=payload_bytes,
                        headers={
                            "Content-Type": "application/json",
                            "X-OCR-Request-ID": request_id,
                            "X-Room-Index": str(room_idx),
                        },
                        method="POST",
                    )
                    try:
                        print(
                            f"   🌐 [OCR][{request_id}] deferred POST {ocr_url} "
                            f"(attempt {attempt_idx + 1}/{deferred_retries})"
                        )
                        with urllib.request.urlopen(request, timeout=deferred_timeout_s) as response:
                            response_data = json.loads(response.read().decode('utf-8'))
                        print(f"   📥 [OCR][{request_id}] deferred răspuns status={response.status}")
                        room_label = apply_ocr_response_to_report(
                            room_idx,
                            response_data,
                            request_id,
                            source_tag="deferred",
                            ocr_frame_paths=ocr_frame_paths,
                        )
                        if room_label:
                            return
                    except Exception as deferred_error:
                        print(
                            f"   ⚠️ [OCR][{request_id}] deferred error "
                            f"(attempt {attempt_idx + 1}/{deferred_retries}): {deferred_error}"
                        )

                    if attempt_idx < deferred_retries - 1:
                        time.sleep(deferred_sleep_s)

                print(f"   ❌ [OCR][{request_id}] deferred retries epuizate fără label")

            worker = threading.Thread(
                target=_deferred_worker,
                name=f"ocr-deferred-{room_idx}-{request_id}",
                daemon=True,
            )
            worker.start()

        def detect_room_label_before_entry(room_idx, frame_for_ocr=None, ocr_request_id=None):
            """Face OCR pe frame-ul curent exact înainte de intrarea prin ușă."""
            if stream_pipeline is None:
                return None

            def extract_best_label_crop(frame_bgr):
                """Returnează cel mai bun crop de tip label dreptunghiular sau None."""
                try:
                    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                    h, w = gray.shape[:2]
                    image_area = float(h * w)
                    blur = cv2.GaussianBlur(gray, (5, 5), 0)

                    mask_variants = [
                        cv2.Canny(blur, 60, 160),
                        cv2.adaptiveThreshold(
                            blur,
                            255,
                            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                            cv2.THRESH_BINARY_INV,
                            31,
                            7,
                        ),
                    ]

                    grad = cv2.morphologyEx(blur, cv2.MORPH_GRADIENT, np.ones((3, 3), dtype=np.uint8))
                    _, grad_thr = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                    mask_variants.append(grad_thr)

                    best_candidate = None
                    best_score = -1.0
                    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))

                    for mask in mask_variants:
                        proc = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
                        contours, _ = cv2.findContours(proc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                        for contour in contours:
                            area = cv2.contourArea(contour)
                            if area < image_area * 0.003 or area > image_area * 0.65:
                                continue

                            perimeter = cv2.arcLength(contour, True)
                            if perimeter <= 1.0:
                                continue

                            approx = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
                            if len(approx) < 4 or len(approx) > 8:
                                continue

                            x, y, bw, bh = cv2.boundingRect(approx)

                            # Ignoră detecțiile din benzile laterale (15% stânga / 15% dreapta):
                            # acolo apare interiorul camerei/încăperii și produce detecții false.
                            # Se acceptă doar candidați cu centrul în banda centrală (70%).
                            side_margin = 0.15 * w
                            cand_center_x = x + bw / 2.0
                            if cand_center_x < side_margin or cand_center_x > (w - side_margin):
                                continue

                            aspect = bw / max(float(bh), 1.0)
                            if aspect < 1.1 or aspect > 8.5:
                                continue

                            box_area = float(bw * bh)
                            extent = area / max(box_area, 1.0)
                            if extent < 0.35:
                                continue

                            roi = gray[y : y + bh, x : x + bw]
                            if roi.size == 0:
                                continue

                            local_std = float(np.std(roi))
                            shape_bonus = 1.0 if len(approx) == 4 else 0.5
                            score = (
                                1.7 * shape_bonus
                                + 2.0 * extent
                                + 0.8 * min(aspect, 6.0) / 6.0
                                + 0.9 * min(local_std / 64.0, 1.0)
                            )

                            if score > best_score:
                                best_score = score
                                best_candidate = (x, y, bw, bh)

                    if best_candidate is None:
                        return None, None

                    x, y, bw, bh = best_candidate
                    crop = frame_bgr[y : y + bh, x : x + bw]
                    if crop.size == 0:
                        return None, None

                    return crop, best_candidate
                except Exception:
                    return None, None

            request_id = str(ocr_request_id or f"ocr-{room_idx}-{uuid.uuid4().hex[:8]}")
            payload = None
            ocr_url = os.environ.get(
                "OCR_ROOM_LABEL_URL",
                "http://127.0.0.1:8001/api/v1/ocr/room-label",
            )

            try:
                if frame_for_ocr is None:
                    frame_for_ocr = controller.get_frame_bgr()
                if frame_for_ocr is None:
                    print(f"   ⚠️ [OCR][{request_id}] frame indisponibil")
                    return None

                source_h, source_w = frame_for_ocr.shape[:2]
                ocr_input_frame = frame_for_ocr
                detected_bbox = None

                detected_crop, detected_bbox = extract_best_label_crop(frame_for_ocr)
                if detected_crop is not None:
                    ocr_input_frame = detected_crop
                    x, y, bw, bh = detected_bbox
                    print(
                        f"   🎯 [OCR][{request_id}] label detectat bbox=({x},{y},{bw},{bh}) "
                        f"din frame {source_w}x{source_h}"
                    )
                else:
                    print(
                        f"   ℹ️ [OCR][{request_id}] fără label clar detectat, fallback pe frame complet "
                        f"{source_w}x{source_h}"
                    )

                frame_h, frame_w = ocr_input_frame.shape[:2]
                print(
                    f"   📤 [OCR][{request_id}] pregătire trimitere camera={room_idx} "
                    f"ocr_frame={frame_w}x{frame_h}"
                )

                ok, jpeg_buffer = cv2.imencode('.jpg', ocr_input_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if not ok:
                    print(f"   ⚠️ [OCR][{request_id}] encode JPEG eșuat")
                    return None

                overlay_path = None
                try:
                    reports_dir = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), "..", "reports", "ocr_frames")
                    )
                    os.makedirs(reports_dir, exist_ok=True)
                    frame_ts_ms = int(time.time() * 1000)

                    # Salvăm DOAR frame-ul ÎNTREG cu detecția (bbox verde) desenată pe el.
                    # Acesta e singurul frame trimis în frontend pentru debug OCR
                    # (nu mai trimitem crop-ul).
                    debug_overlay = frame_for_ocr.copy()
                    if detected_bbox is not None:
                        x, y, bw, bh = detected_bbox
                        cv2.rectangle(debug_overlay, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
                    overlay_path = os.path.join(
                        reports_dir,
                        f"ocr_pre_entry_room_{room_idx}_{frame_ts_ms}_detected_bbox.jpg",
                    )
                    cv2.imwrite(overlay_path, debug_overlay)
                    print(f"   🖼️ [OCR][{request_id}] full frame cu bbox salvat -> {overlay_path}")
                except Exception as save_error:
                    overlay_path = None
                    print(f"   ⚠️ [OCR][{request_id}] nu pot salva frame-ul ({save_error})")

                # Colectează căile salvate pentru raport — DOAR frame-ul întreg cu bbox.
                ocr_frame_paths = {}
                if overlay_path:
                    ocr_frame_paths["full_frame_path"] = overlay_path

                # Atașează frame-urile la raport ACUM, independent de rezultatul OCR,
                # ca să avem mereu debug vizual (ce s-a trimis la OCR) chiar dacă nu se
                # detectează niciun text.
                if ocr_frame_paths and stream_pipeline is not None:
                    try:
                        stream_pipeline.set_room_ocr_frame_paths_for_report(room_idx, ocr_frame_paths)
                    except Exception as attach_error:
                        print(f"   ⚠️ [OCR][{request_id}] nu pot atașa frame-urile la raport ({attach_error})")

                image_b64 = base64.b64encode(jpeg_buffer.tobytes()).decode('utf-8')
                payload = json.dumps({"image_base64": image_b64}).encode('utf-8')

                ocr_timeout_s = 15.0
                ocr_retries = 2
                try:
                    ocr_timeout_s = float(os.environ.get("OCR_ROOM_LABEL_TIMEOUT_S", "15"))
                except Exception:
                    pass

                try:
                    ocr_retries = int(os.environ.get("OCR_ROOM_LABEL_RETRIES", "2"))
                except Exception:
                    pass

                if ocr_retries < 1:
                    ocr_retries = 1

                response_data = None
                last_request_error = None
                for attempt_idx in range(ocr_retries):
                    print(
                        f"   🌐 [OCR][{request_id}] POST {ocr_url} "
                        f"(attempt {attempt_idx + 1}/{ocr_retries}, timeout={ocr_timeout_s:.1f}s)"
                    )
                    request = urllib.request.Request(
                        ocr_url,
                        data=payload,
                        headers={
                            "Content-Type": "application/json",
                            "X-OCR-Request-ID": request_id,
                            "X-Room-Index": str(room_idx),
                        },
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(request, timeout=ocr_timeout_s) as response:
                            response_data = json.loads(response.read().decode('utf-8'))
                            print(f"   📥 [OCR][{request_id}] răspuns primit status={response.status}")
                        break
                    except Exception as request_error:
                        last_request_error = request_error
                        if attempt_idx < ocr_retries - 1:
                            print(
                                f"   ⚠️ [OCR][{request_id}] timeout/eroare "
                                f"(încercarea {attempt_idx + 1}/{ocr_retries}): {request_error}"
                            )
                            time.sleep(0.25)
                        else:
                            raise last_request_error

                # Desenează bbox-ul VERDE din rezultatele EasyOCR pe frame-ul întreg.
                # Detectorul local de contur (extract_best_label_crop) poate rata zona
                # (semn mic / contrast slab) și atunci nu se desena nimic, chiar dacă
                # OCR-ul găsea textul. Folosim coordonatele reale returnate de OCR.
                try:
                    if overlay_path and isinstance(response_data, dict):
                        ocr_results = response_data.get("results") or []
                        off_x, off_y = (0, 0)
                        if detected_bbox is not None:
                            off_x, off_y = int(detected_bbox[0]), int(detected_bbox[1])
                        overlay_img = frame_for_ocr.copy()
                        drawn = 0
                        for item in ocr_results:
                            if not (isinstance(item, dict) and str(item.get("text", "")).strip()):
                                continue
                            bb = item.get("bounding_box") or []
                            pts = [(int(p[0]) + off_x, int(p[1]) + off_y) for p in bb if len(p) >= 2]
                            if len(pts) >= 4:
                                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                                cv2.rectangle(overlay_img, (min(xs), min(ys)), (max(xs), max(ys)), (0, 255, 0), 2)
                                cv2.putText(overlay_img, str(item.get("text", "")).strip(),
                                            (min(xs), max(0, min(ys) - 8)),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                                drawn += 1
                        if drawn > 0:
                            cv2.imwrite(overlay_path, overlay_img)
                            print(f"   🟩 [OCR][{request_id}] bbox OCR desenat pe frame ({drawn} zone)")
                except Exception as draw_err:
                    print(f"   ⚠️ [OCR][{request_id}] nu pot desena bbox OCR: {draw_err}")

                room_label = apply_ocr_response_to_report(
                    room_idx,
                    response_data,
                    request_id,
                    source_tag="direct",
                    ocr_frame_paths=ocr_frame_paths,
                )
                if room_label is None:
                    dispatch_deferred_ocr_retry(room_idx, payload, ocr_url, request_id, ocr_frame_paths=ocr_frame_paths)
                return room_label
            except urllib.error.URLError as ocr_error:
                print(f"   ⚠️ [OCR][{request_id}] serviciu indisponibil: {ocr_error}")
                try:
                    dispatch_deferred_ocr_retry(room_idx, payload, ocr_url, request_id, ocr_frame_paths=ocr_frame_paths)
                except Exception:
                    pass
            except Exception as ocr_error:
                print(f"   ⚠️ [OCR][{request_id}] eroare: {ocr_error}")
                try:
                    dispatch_deferred_ocr_retry(room_idx, payload, ocr_url, request_id, ocr_frame_paths=ocr_frame_paths)
                except Exception:
                    pass

            return None

        def analyze_room_hazards_before_entry(room_idx, frame_for_ai=None, ai_request_id=None):
            """Trimite frame-ul pre-entry către serviciul AI și salvează analiza în raport."""
            if stream_pipeline is None:
                return None

            request_id = str(ai_request_id or f"ai-pre-entry-{room_idx}-{uuid.uuid4().hex[:8]}")

            try:
                if frame_for_ai is None:
                    frame_for_ai = controller.get_frame_bgr()
                if frame_for_ai is None:
                    print(f"   ⚠️ [AI][{request_id}] frame indisponibil")
                    return None

                ok, jpeg_buffer = cv2.imencode('.jpg', frame_for_ai, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if not ok:
                    print(f"   ⚠️ [AI][{request_id}] encode JPEG eșuat")
                    return None

                ai_image_rel_path = None
                try:
                    reports_dir = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), "..", "reports", "ai_frames")
                    )
                    os.makedirs(reports_dir, exist_ok=True)
                    frame_ts_ms = int(time.time() * 1000)
                    ai_image_filename = f"ai_pre_entry_room_{room_idx}_{frame_ts_ms}.jpg"
                    ai_image_abs_path = os.path.join(reports_dir, ai_image_filename)
                    with open(ai_image_abs_path, "wb") as ai_file:
                        ai_file.write(jpeg_buffer.tobytes())
                    ai_image_rel_path = f"/reports/assets/ai_frames/{ai_image_filename}"
                    print(f"   💾 [AI][{request_id}] frame salvat -> {ai_image_abs_path}")
                except Exception as save_error:
                    print(f"   ⚠️ [AI][{request_id}] nu pot salva frame-ul ({save_error})")

                image_b64 = base64.b64encode(jpeg_buffer.tobytes()).decode('utf-8')
                payload = json.dumps({"image_base64": image_b64}).encode('utf-8')

                ai_url = os.environ.get(
                    "AI_ROOM_ANALYSIS_URL",
                    "http://127.0.0.1:8000/api/v1/analysis/room-hazards",
                )

                ai_timeout_s = 20.0
                ai_retries = 2
                try:
                    ai_timeout_s = float(os.environ.get("AI_ROOM_ANALYSIS_TIMEOUT_S", "20"))
                except Exception:
                    pass

                try:
                    ai_retries = int(os.environ.get("AI_ROOM_ANALYSIS_RETRIES", "2"))
                except Exception:
                    pass

                if ai_retries < 1:
                    ai_retries = 1

                response_data = None
                for attempt_idx in range(ai_retries):
                    print(
                        f"   🌐 [AI][{request_id}] POST {ai_url} "
                        f"(attempt {attempt_idx + 1}/{ai_retries}, timeout={ai_timeout_s:.1f}s)"
                    )
                    request = urllib.request.Request(
                        ai_url,
                        data=payload,
                        headers={
                            "Content-Type": "application/json",
                            "X-AI-Request-ID": request_id,
                            "X-Room-Index": str(room_idx),
                        },
                        method="POST",
                    )

                    try:
                        with urllib.request.urlopen(request, timeout=ai_timeout_s) as response:
                            response_data = json.loads(response.read().decode('utf-8'))
                            print(f"   📥 [AI][{request_id}] răspuns primit status={response.status}")
                        break
                    except Exception as request_error:
                        if attempt_idx < ai_retries - 1:
                            print(
                                f"   ⚠️ [AI][{request_id}] timeout/eroare "
                                f"(încercarea {attempt_idx + 1}/{ai_retries}): {request_error}"
                            )
                            time.sleep(0.25)
                        else:
                            raise request_error

                if not isinstance(response_data, dict):
                    print(f"   ⚠️ [AI][{request_id}] răspuns invalid")
                    stream_pipeline.set_room_pre_entry_analysis_for_report(
                        room_idx,
                        {
                            "status": "error",
                            "level": "unknown",
                            "description": "Serviciul AI a răspuns cu format invalid.",
                            "hazards_identified": [],
                            "image_url": ai_image_rel_path,
                            "source": "pre_entry_ai_service",
                            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "request_id": request_id,
                            "response_received": True,
                            "http_status": 200,
                            "error": "invalid_response_format",
                        },
                    )
                    return None

                analysis_payload = {
                    "status": "success",
                    "level": response_data.get("level"),
                    "hazards_identified": list(response_data.get("hazards_identified") or []),
                    "description": response_data.get("description"),
                    "image_url": ai_image_rel_path,
                    "source": "pre_entry_ai_service",
                    "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "request_id": request_id,
                    "response_received": True,
                    "http_status": 200,
                    "error": None,
                }

                if not analysis_payload.get("level"):
                    print(f"   ⚠️ [AI][{request_id}] level lipsă în răspuns")
                    stream_pipeline.set_room_pre_entry_analysis_for_report(
                        room_idx,
                        {
                            "status": "error",
                            "level": "unknown",
                            "hazards_identified": list(response_data.get("hazards_identified") or []),
                            "description": response_data.get("description")
                            or "Serviciul AI a răspuns, dar fără câmpul level.",
                            "image_url": ai_image_rel_path,
                            "source": "pre_entry_ai_service",
                            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "request_id": request_id,
                            "response_received": True,
                            "http_status": 200,
                            "error": "missing_level",
                        },
                    )
                    return None

                stream_pipeline.set_room_pre_entry_analysis_for_report(room_idx, analysis_payload)
                print(
                    f"   ✅ [AI][{request_id}] analiză salvată în raport "
                    f"(camera={room_idx}, level={analysis_payload.get('level')})"
                )
                return analysis_payload

            except urllib.error.HTTPError as ai_error:
                status_code = getattr(ai_error, "code", None)
                error_text = str(ai_error)
                try:
                    error_body = ai_error.read().decode("utf-8", errors="ignore").strip()
                    if error_body:
                        error_text = f"{error_text} | body={error_body[:350]}"
                except Exception:
                    pass

                print(f"   ⚠️ [AI][{request_id}] HTTP error: {error_text}")
                stream_pipeline.set_room_pre_entry_analysis_for_report(
                    room_idx,
                    {
                        "status": "error",
                        "level": "unknown",
                        "hazards_identified": [],
                        "description": "Serviciul AI a răspuns cu eroare HTTP.",
                        "image_url": ai_image_rel_path,
                        "source": "pre_entry_ai_service",
                        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "request_id": request_id,
                        "response_received": True,
                        "http_status": status_code,
                        "error": error_text,
                    },
                )
            except urllib.error.URLError as ai_error:
                print(f"   ⚠️ [AI][{request_id}] serviciu indisponibil: {ai_error}")
                stream_pipeline.set_room_pre_entry_analysis_for_report(
                    room_idx,
                    {
                        "status": "error",
                        "level": "unknown",
                        "hazards_identified": [],
                        "description": "Serviciul AI nu a putut fi contactat.",
                        "image_url": ai_image_rel_path,
                        "source": "pre_entry_ai_service",
                        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "request_id": request_id,
                        "response_received": False,
                        "http_status": None,
                        "error": str(ai_error),
                    },
                )
            except Exception as ai_error:
                print(f"   ⚠️ [AI][{request_id}] eroare: {ai_error}")
                stream_pipeline.set_room_pre_entry_analysis_for_report(
                    room_idx,
                    {
                        "status": "error",
                        "level": "unknown",
                        "hazards_identified": [],
                        "description": "Analiza AI pre-entry a eșuat în backend.",
                        "image_url": ai_image_rel_path,
                        "source": "pre_entry_ai_service",
                        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "request_id": request_id,
                        "response_received": False,
                        "http_status": None,
                        "error": str(ai_error),
                    },
                )

            return None

        def dispatch_room_label_ocr_async(room_idx, frame_for_ocr=None):
            """Trimite OCR în background fără să blocheze fluxul de zbor."""
            if stream_pipeline is None:
                return False

            try:
                if frame_for_ocr is None:
                    frame_for_ocr = controller.get_frame_bgr()
                if frame_for_ocr is None:
                    print("   ⚠️ OCR pre-entry async: frame indisponibil")
                    return False

                frame_snapshot = frame_for_ocr.copy()
            except Exception as frame_error:
                print(f"   ⚠️ OCR pre-entry async: captură/copy eșuată ({frame_error})")
                return False

            request_id = f"ocr-room-{room_idx}-{int(time.time() * 1000)}"

            def _ocr_worker():
                detect_room_label_before_entry(
                    room_idx,
                    frame_for_ocr=frame_snapshot,
                    ocr_request_id=request_id,
                )

            worker = threading.Thread(
                target=_ocr_worker,
                name=f"ocr-room-label-{room_idx}",
                daemon=True,
            )
            worker.start()
            print(f"   🚀 [OCR][{request_id}] async dispatch pentru camera {room_idx}")
            return True

        def dispatch_room_hazards_ai_async(room_idx, frame_for_ai=None):
            """Trimite analiza AI pre-entry în background fără să blocheze fluxul de zbor."""
            if stream_pipeline is None:
                return False

            try:
                if frame_for_ai is None:
                    frame_for_ai = controller.get_frame_bgr()
                if frame_for_ai is None:
                    print("   ⚠️ AI pre-entry async: frame indisponibil")
                    return False

                frame_snapshot = frame_for_ai.copy()
            except Exception as frame_error:
                print(f"   ⚠️ AI pre-entry async: captură/copy eșuată ({frame_error})")
                return False

            request_id = f"ai-room-{room_idx}-{int(time.time() * 1000)}"

            def _ai_worker():
                analyze_room_hazards_before_entry(
                    room_idx,
                    frame_for_ai=frame_snapshot,
                    ai_request_id=request_id,
                )

            worker = threading.Thread(
                target=_ai_worker,
                name=f"ai-room-hazards-{room_idx}",
                daemon=True,
            )
            worker.start()
            print(f"   🚀 [AI][{request_id}] async dispatch pentru camera {room_idx}")
            return True

        def detect_room_label_with_rotation(room_idx, degrees=30):
            """OCR async pe frame-ul rotit + AI async pe frame-ul imediat după revenire."""
            rotation_attempted = False
            rotated_ocr_frame = None
            post_return_centered_frame = None
            ocr_capture_settle_s = _read_env_float("OCR_PRE_ENTRY_CAPTURE_SETTLE_S", 0.65)
            ocr_capture_burst = _read_env_int("OCR_PRE_ENTRY_CAPTURE_BURST", 3)
            ocr_capture_burst_gap_s = _read_env_float("OCR_PRE_ENTRY_CAPTURE_BURST_GAP_S", 0.08)
            try:
                print(f"   🔄 OCR pre-entry: rotație stânga {degrees}° pentru captură")
                drone_stabilize(controller, level="light", label="pre-OCR")
                
                # Marcam incercarea INAINTE de apelul SDK, pt ca daca ramanem fara ACK (timeout 20s),
                # Tello totusi executa fizic rotatia, iar exceptia nu trebuie sa opreasca rotatia inapoi!
                rotation_attempted = True 
                controller.move_counter_clockwise(degrees)
                
                mission_path.record_rotation(degrees, clockwise=False, label="pre_entry_ocr_left")
                
                if ocr_capture_settle_s > 0:
                    print(f"   ⏳ OCR pre-entry: stabilizare după rotație ({ocr_capture_settle_s:.2f}s)")
                    time.sleep(ocr_capture_settle_s)

                capture_attempts = max(1, int(ocr_capture_burst))
                valid_captures = 0
                for capture_idx in range(capture_attempts):
                    candidate_frame = controller.get_frame_bgr()
                    if candidate_frame is not None:
                        rotated_ocr_frame = candidate_frame
                        valid_captures += 1
                    if capture_idx < capture_attempts - 1 and ocr_capture_burst_gap_s > 0:
                        time.sleep(ocr_capture_burst_gap_s)

                if rotated_ocr_frame is None:
                    print("   ⚠️ OCR pre-entry: captură după rotație indisponibilă")
                else:
                    print(
                        f"   📸 OCR pre-entry: capturi valide după rotație "
                        f"{valid_captures}/{capture_attempts}"
                    )
            except Exception as rotate_error:
                print(f"   ⚠️ OCR pre-entry: rotație stânga a semnalat eroare (posibil timeout): {rotate_error}")
                # Chiar daca a dat eroare de timeout, drona probabil s-a intors fizic! Mergem mai departe.

            if rotation_attempted:
                # Facem O SINGURA INCERCARE de rotatie inapoi, fara retry!
                # Retry-urile cu timeout uri false adaugau inca 30 de grade eronat.
                try:
                    print(f"   🔄 OCR pre-entry: revenire rotație dreapta {degrees}°")
                    controller.tello.send_rc_control(0, 0, 0, 0)
                    time.sleep(0.8) # Delay crucial anti-skip Tello firmware
                    return_degrees = degrees + int(os.environ.get("OCR_RETURN_DEGREES_OFFSET", 0))
                    controller.move_clockwise(return_degrees)
                    mission_path.record_rotation(return_degrees, clockwise=True, label="pre_entry_ocr_right")
                    time.sleep(0.5)
                except Exception as rotate_back_error:
                    print(f"   ⚠️ OCR pre-entry: revenire rotație dreapta a dat timeout/eroare: {rotate_back_error}")
                    # Nu mai dam loop, fiindca cel mai probabil a executat blocul fizic

            # După revenire la heading, capturăm frame-ul centrat pe ușă pentru AI.
            try:
                post_return_centered_frame = controller.get_frame_bgr()
                if post_return_centered_frame is None:
                    print("   ⚠️ AI pre-entry: frame după revenire indisponibil")
            except Exception as post_capture_error:
                print(f"   ⚠️ AI pre-entry: captură după revenire eșuată ({post_capture_error})")

            # OCR rulează ASYNC pe frame-ul rotit la 30°.
            dispatch_room_label_ocr_async(room_idx, frame_for_ocr=rotated_ocr_frame)

            # AI rulează ASYNC pe frame-ul imediat după revenire (centrat pe ușă).
            dispatch_room_hazards_ai_async(room_idx, frame_for_ai=post_return_centered_frame)
            return None

        def center_door_before_forward(
            phase_label,
            tolerance_px=70,
            max_iterations=10,
            stable_required=1,
            soft_accept_px=100,
        ):
            """Centrează ușa pe mijloc înainte de avansare."""
            stable_hits = 0
            best_abs_offset = 10**9
            last_offset = None
            prev_offset = None

            for iteration in range(max_iterations):
                if not nav_state.target_center or not nav_state.frame_dimensions:
                    print(f"   ❌ {phase_label}: target indisponibil")
                    return False

                current_target_x, _ = nav_state.target_center
                current_frame_w, _ = nav_state.frame_dimensions
                current_center_x = current_frame_w // 2
                current_offset_x = current_target_x - current_center_x
                current_abs_offset = abs(current_offset_x)
                best_abs_offset = min(best_abs_offset, current_abs_offset)
                prev_offset = last_offset
                last_offset = current_offset_x

                if current_abs_offset <= tolerance_px:
                    stable_hits += 1
                    print(
                        f"   ✅ {phase_label}: centrat ({current_offset_x}px) "
                        f"[{stable_hits}/{stable_required}]"
                    )
                    if stable_hits >= stable_required:
                        controller.tello.send_rc_control(0, 0, 0, 0)
                        time.sleep(0.15)
                        return True
                    time.sleep(0.15)
                    continue

                stable_hits = 0
                lateral_speed = int(np.clip(current_offset_x * 0.12, -22, 22))
                if lateral_speed == 0:
                    lateral_speed = 8 if current_offset_x > 0 else -8

                # Anti-overshoot: dacă semnul s-a inversat față de iterația anterioară, frânare
                if prev_offset is not None and (prev_offset * current_offset_x < 0):
                    lateral_speed = int(lateral_speed * 0.4) or (1 if current_offset_x > 0 else -1)
                    print(f"   ⚠️ {phase_label}: overshoot ({prev_offset}px→{current_offset_x}px), frânare lr={lateral_speed}")

                direction = "dreapta" if lateral_speed > 0 else "stânga"
                pulse_time = 0.15 if current_abs_offset <= 100 else 0.25
                print(
                    f"   🔄 {phase_label}: offset={current_offset_x}px -> corecție {direction} "
                    f"(lr={lateral_speed}, pulse={pulse_time}s)"
                )

                controller.tello.send_rc_control(lateral_speed, 0, 0, 0)
                time.sleep(pulse_time)
                mission_path.record_timed_rc(lateral_speed, 0, 0, pulse_time, label="phase1_centering")
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.15)

            if best_abs_offset <= soft_accept_px and last_offset is not None:
                print(
                    f"   ⚠️ {phase_label}: acceptare relaxată (offset final {last_offset}px, best {best_abs_offset}px)"
                )
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.15)
                return True

            print(f"   ❌ {phase_label}: nu s-a obținut centrare stabilă")
            return False

        def micro_recenter_after_ocr(
            phase_label,
            tolerance_px=70,
            max_ticks=2,
        ):
            """Corecție fină după OCR: maxim 2 impulsuri laterale, doar dacă offset-ul e în afara toleranței."""
            for tick_idx in range(1, max_ticks + 1):
                if not nav_state.target_center or not nav_state.frame_dimensions:
                    print(f"   ⚠️ {phase_label}: target indisponibil, skip")
                    return

                current_target_x, _ = nav_state.target_center
                current_frame_w, _ = nav_state.frame_dimensions
                current_center_x = current_frame_w // 2
                current_offset_x = current_target_x - current_center_x

                if abs(current_offset_x) <= tolerance_px:
                    print(f"   ✅ {phase_label}: deja centrat (offset={current_offset_x}px)")
                    return

                lateral_speed = int(np.clip(current_offset_x * 0.12, -18, 18))
                if lateral_speed == 0:
                    lateral_speed = 8 if current_offset_x > 0 else -8

                direction = "dreapta" if lateral_speed > 0 else "stânga"
                print(
                    f"   🔧 {phase_label}: tick {tick_idx}/{max_ticks}, offset={current_offset_x}px "
                    f"-> corecție {direction} (lr={lateral_speed})"
                )
                controller.tello.send_rc_control(lateral_speed, 0, 0, 0)
                time.sleep(0.16)
                mission_path.record_timed_rc(lateral_speed, 0, 0, 0.16, label="post_ocr_micro_center")
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.12)

            # Stop final explicit
            controller.tello.send_rc_control(0, 0, 0, 0)
            time.sleep(0.1)

        def align_lateral_distance_before_ocr(
            phase_label,
            target_min_m=0.60,
            target_max_m=0.80,
            max_iterations=12,
            missing_target_patience=5,
        ):
            """Ajustează poziția față/spate până când cel puțin o laterală este în intervalul țintă."""
            missing_hits = 0

            def interval_error(value):
                if value < target_min_m:
                    return target_min_m - value
                if value > target_max_m:
                    return value - target_max_m
                return 0.0

            for iteration in range(1, max_iterations + 1):
                if not nav_state.edge_distances or len(nav_state.edge_distances) != 2:
                    missing_hits += 1
                    if missing_hits >= missing_target_patience:
                        print(f"   ❌ {phase_label}: distanțe laterale indisponibile")
                        return False
                    print(
                        f"   ⏳ {phase_label}: aștept distanțe laterale "
                        f"[{missing_hits}/{missing_target_patience}]"
                    )
                    controller.tello.send_rc_control(0, 0, 0, 0)
                    time.sleep(0.2)
                    continue

                left_dist, right_dist = nav_state.edge_distances
                if not np.isfinite(left_dist) or not np.isfinite(right_dist):
                    missing_hits += 1
                    if missing_hits >= missing_target_patience:
                        print(f"   ❌ {phase_label}: distanțe laterale invalide")
                        return False
                    print(
                        f"   ⏳ {phase_label}: distanțe invalide L={left_dist}, R={right_dist} "
                        f"[{missing_hits}/{missing_target_patience}]"
                    )
                    controller.tello.send_rc_control(0, 0, 0, 0)
                    time.sleep(0.2)
                    continue

                missing_hits = 0
                left_ok = target_min_m <= left_dist <= target_max_m
                right_ok = target_min_m <= right_dist <= target_max_m

                if left_ok or right_ok:
                    print(
                        f"   ✅ {phase_label}: interval atins "
                        f"L={left_dist:.2f}m, R={right_dist:.2f}m"
                    )
                    controller.tello.send_rc_control(0, 0, 0, 0)
                    time.sleep(0.15)
                    return True

                left_err = interval_error(left_dist)
                right_err = interval_error(right_dist)

                if left_err <= right_err:
                    control_side = "L"
                    control_dist = left_dist
                else:
                    control_side = "R"
                    control_dist = right_dist

                if control_dist > target_max_m:
                    fb_cmd = 18
                    action = "înainte"
                else:
                    fb_cmd = -18
                    action = "înapoi"

                print(
                    f"   🔄 {phase_label}: L={left_dist:.2f}m, R={right_dist:.2f}m "
                    f"-> corecție {action} (fb={fb_cmd}, ref={control_side}, iter={iteration}/{max_iterations})"
                )

                controller.tello.send_rc_control(0, fb_cmd, 0, 0)
                time.sleep(0.32)
                mission_path.record_timed_rc(0, fb_cmd, 0, 0.32, label="pre_entry_align")
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.2)

            print(
                f"   ❌ {phase_label}: nu s-a atins intervalul {target_min_m:.2f}-{target_max_m:.2f}m "
                "pe laterale"
            )
            return False

        # Guard anti-reentry: după ieșirea dintr-o cameră și rotația de tranziție,
        # ignorăm detecțiile de ușă pentru o perioadă scurtă ca să nu reselectăm
        # aceeași ușă din care tocmai am ieșit.
        ignore_door_until_ts = 0.0


        if start_position == "stairs":
            nav_state.autopilot_status = "Pornire de pe STAIRS"
            print("\n" + "="*60)
            print("🏢 FAZA DE START: STAIR CLIMBER")
            print("="*60)
            if not controller.is_flying():
                print("   🚀 Decolare automată...")
                controller.takeoff()
                time.sleep(1.0)

            from navigation.stair_climber.controller import execute_stair_climber
            # Run the stairs sequence (cu semnalele alese din frontend)
            success = execute_stair_climber(controller.tello, target_floor=target_floor, start_position=start_position, signals=stair_signals, single_flight=stair_single_flight)
            if not success:
                print("   ⚠️ Stair Climber aborted sau esuat.")
                nav_state.autopilot_active = False
                return

            # Mod test rapid: a urcat un singur zbor și a aterizat → încheiem misiunea aici
            # (fără tranziție spre stairwell / hol).
            if stair_single_flight:
                nav_state.autopilot_status = "✅ Single-flight complet (aterizat pe palier)"
                print("\n✅ STAIR CLIMBER SINGLE-FLIGHT COMPLET — drona a aterizat pe palier.\n")
                return

            print("   ✅ Stair Climber finalizat. Tranzitie spre STAIRWELL...")
            # Now implicitly switch to stairwell logic for the remainder of the entry sequence
            start_position = "stairwell"

        # Variabile globale pt. inregistrare STAIRWELL
        global _vw_raw_stairwell, _vw_annotated_stairwell
        _vw_raw_stairwell = None
        _vw_annotated_stairwell = None

        def start_stairwell_recordings():
            import datetime, os, cv2
            global _vw_raw_stairwell, _vw_annotated_stairwell
            os.makedirs('stairwell_recordings', exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            _vw_raw_stairwell = cv2.VideoWriter(f"stairwell_recordings/raw_{stamp}.mp4", cv2.VideoWriter_fourcc(*'mp4v'), 10.0, (960, 720))
            _vw_annotated_stairwell = cv2.VideoWriter(f"stairwell_recordings/annotated_{stamp}.mp4", cv2.VideoWriter_fourcc(*'mp4v'), 10.0, (960, 720))

        def stop_stairwell_recordings():
            global _vw_raw_stairwell, _vw_annotated_stairwell
            if _vw_raw_stairwell:
                _vw_raw_stairwell.release()
                _vw_raw_stairwell = None
            if _vw_annotated_stairwell:
                _vw_annotated_stairwell.release()
                _vw_annotated_stairwell = None

        def update_stairwell_recordings():
            import cv2
            global _vw_raw_stairwell, _vw_annotated_stairwell
            if not nav_state.autopilot_active:
                raise Exception("Misiune anulată. Se opresc înregistrările forțat.")

            # luam ultimul frame curat
            read_obj = getattr(controller.tello, 'get_frame_read', None)
            if not read_obj: return
            frame = read_obj().frame
            if frame is None:
                return

            # Format 960x720 expected for standard video
            target_dim = (960, 720)

            # Scrie frame brut (cu adnotari YOLO pe el)
            if _vw_raw_stairwell is not None:
                 try:
                     import ai_analyzer
                     ai_frame_raw = ai_analyzer.get_analyzer().annotate_live_frame(frame.copy())
                 except:
                     ai_frame_raw = frame.copy()
                     
                 if ai_frame_raw.shape[:2] != (720, 960):
                     ai_frame_raw = cv2.resize(ai_frame_raw, target_dim)
                 _vw_raw_stairwell.write(ai_frame_raw)

            # Scrie frame DA2 + Contur simplu:
            if _vw_annotated_stairwell is not None:
                 import stream_pipeline
                 da2_frame = getattr(stream_pipeline, 'last_depth_snapshot', None)
                 if da2_frame is None:
                     da2_frame = frame.copy()
                     
                 if da2_frame.shape[:2] != (720, 960):
                     da2_frame = cv2.resize(da2_frame, target_dim)
                 _vw_annotated_stairwell.write(da2_frame)

        if start_position == "stairwell":
            nav_state.autopilot_status = "Pornire din Casa Scării"
            print("="*60)
            print("🏢 FAZA DE START: Plecare din CASA SCĂRII")
            print("="*60)
            start_stairwell_recordings()
            if not controller.is_flying():
                print("   🚀 Decolare automată...")
                controller.takeoff()
                time.sleep(0.8)
            else:
                print("   ✅ Drona este deja în zbor.")

            print("   ➡️ Avansare 2 metri...")
            forward_distance_cm = 200
            forward_speed = 40
            duration = forward_distance_cm / forward_speed
            controller.tello.send_rc_control(0, forward_speed, 0, 0)
            _orig_s = time.sleep
            import threading
            _stairwell_tid = threading.get_ident()
            def _s_rec(d):
                if threading.get_ident() != _stairwell_tid:
                    _orig_s(d)
                    return
                if not nav_state.autopilot_active:
                    _orig_s(0.1) # tiny sleep to flush commands
                    raise Exception("Aterizare forțată - autopilot oprit.")
                try:
                    update_stairwell_recordings()
                except Exception:
                    pass
                _orig_s(d)
            time.sleep = _s_rec

            time.sleep(duration)
            mission_path.record_timed_rc(0, forward_speed, 0, duration, label="stairwell_forward_2.3m")
            controller.tello.send_rc_control(0, 0, 0, 0)
            time.sleep(0.8)

            print("   🔄 Rotație 105 grade stânga (spre ușa principală)...")
            try:
                controller.rotate_counter_clockwise(105)
                mission_path.record_rotation(105, clockwise=False, label="stairwell_turn_left")
            except Exception:
                yaw_speed = 80
                rotation_duration = 1.125 * (105 / 90.0)
                controller.tello.send_rc_control(0, 0, 0, -yaw_speed)
                time.sleep(rotation_duration)
                mission_path.record_timed_rc(0, 0, -yaw_speed, rotation_duration, label="stairwell_turn_left_fallback")
                controller.tello.send_rc_control(0, 0, 0, 0)
            time.sleep(1.0)
            update_stairwell_recordings()

            print("   🔍 Așteptăm detecția ușii pachetului...")
            grace_start = time.time()
            found_stairwell_door = False
            while time.time() - grace_start < 4.0:
                update_stairwell_recordings()
                if nav_state.target_detected and nav_state.target_center is not None and nav_state.frame_dimensions is not None:
                    found_stairwell_door = True
                    break
                _orig_s(0.1)

            if not found_stairwell_door:
                print("   ⚠️ Ușa nu a fost detectată inițial. Căutare crab-style spre DREAPTA...")
                search_timeout = 15.0
                search_interval = 0.25
                search_time = 0.0
                search_speed = 24

                while search_time < search_timeout:
                    update_stairwell_recordings()
                    if nav_state.target_detected and nav_state.target_center is not None and nav_state.frame_dimensions is not None:
                        print("   ✅ UȘĂ GĂSITĂ!")
                        found_stairwell_door = True
                        break

                    controller.tello.send_rc_control(search_speed, 0, 0, 0)
                    
                    step_elapsed = 0.0
                    micro_step = 0.05
                    door_found_during_motion = False
                    
                    while step_elapsed < search_interval:
                        _orig_s(micro_step)
                        update_stairwell_recordings()
                        step_elapsed += micro_step
                        search_time += micro_step
                        mission_path.record_timed_rc(search_speed, 0, 0, micro_step, label="stairwell_search_door_crab_right")

                        if nav_state.target_detected and nav_state.target_center is not None and nav_state.frame_dimensions is not None:
                            print("   🛑 Ușă detectată în mișcare -> STOP imediat")
                            controller.tello.send_rc_control(0, 0, 0, 0)
                            found_stairwell_door = True
                            door_found_during_motion = True
                            break

                    if door_found_during_motion:
                        break

                # Stop căutare
                controller.tello.send_rc_control(0, 0, 0, 0)
                _orig_s(0.5)
                
                if not found_stairwell_door:
                    print(f"   ❌ Nu s-a găsit ușa în {search_timeout}s de căutare crab-style.")

            print("   🎯 Centrare pe axa X...")
            mission_path.begin_phase("centering", "Centrare ușă")
            is_centered = center_door_before_forward(
                "STAIRWELL FAZA 1",
                tolerance_px=70,
                max_iterations=12,
                stable_required=1,
                soft_accept_px=105,
            )
            mission_path.end_phase()

            if distance_hold_enabled:
                print("   📏 Controlul distanței (FAZA 1.5)...")
                mission_path.begin_phase("distance_hold", "Menținere distanță")
                hold_entry_distance_after_center(
                    "STAIRWELL FAZA 1.5",
                    target_ratio=distance_hold_target_ratio,
                    deadband=distance_hold_deadband,
                    ema_alpha=distance_hold_ema_alpha,
                    max_iterations=distance_hold_max_iterations,
                    stable_required=distance_hold_stable_required,
                    pulse_s=distance_hold_pulse_s,
                    pause_s=distance_hold_pause_s,
                    metric_method=distance_hold_method,
                    accept_mode=distance_hold_accept_mode,
                    tolerance_px=70,
                )
                mission_path.end_phase()

            print("   🎬 Avansare 1.8 metri prin ușa de la intrare (fără OCR)...")
            total_time = 0
            forward_speed_stair = 35
            forward_time_needed_stair = 180 / forward_speed_stair
            tracking_deadband_px_stair = 50
            tracking_gain_stair = 0.10
            max_lateral_correction_stair = 14
            check_interval_stair = 0.5
            
            while total_time < forward_time_needed_stair:
                update_stairwell_recordings()
                lateral_correction = 0
                if nav_state.target_center and nav_state.frame_dimensions:
                    c_target_x, _ = nav_state.target_center
                    c_frame_w, _ = nav_state.frame_dimensions
                    c_center_x = c_frame_w // 2
                    c_offset_x = c_target_x - c_center_x
                    if abs(c_offset_x) > tracking_deadband_px_stair:
                        lateral_correction = int(np.clip(c_offset_x * tracking_gain_stair, -max_lateral_correction_stair, max_lateral_correction_stair))

                controller.tello.send_rc_control(lateral_correction, forward_speed_stair, 0, 0)
                time.sleep(check_interval_stair)
                mission_path.record_timed_rc(
                    lateral_correction,
                    forward_speed_stair,
                    0,
                    check_interval_stair,
                    label="stairwell_entry",
                )
                total_time += check_interval_stair
            
            controller.tello.send_rc_control(0, 0, 0, 0)
            time.sleep(2)
            
            print("   🔄 Rotație 105 grade stânga spre direcția de explorare hol...")
            try:
                controller.rotate_counter_clockwise(105)
                mission_path.record_rotation(105, clockwise=False, label="stairwell_turn_left_final")
            except Exception:
                yaw_speed = 80
                rotation_duration = 1.125 * (105 / 90.0)
                controller.tello.send_rc_control(0, 0, 0, -yaw_speed)
                time.sleep(rotation_duration)
                mission_path.record_timed_rc(0, 0, -yaw_speed, rotation_duration, label="stairwell_turn_left_final_fb")
                controller.tello.send_rc_control(0, 0, 0, 0)
            
            finally:
                time.sleep = _orig_s

            time.sleep(1.0)
            update_stairwell_recordings()
            stop_stairwell_recordings()
            print("✅ Drona este pe hol. Continuăm rutina normală de scanare camere spre DREAPTA crab-style.")
            nav_state.target_detected = False
            nav_state.target_center = None
            nav_state.target_bbox = None
            ignore_door_until_ts = time.time() + 2.0

        if start_position == "hallway":
            nav_state.autopilot_status = "Pornire direct din HOL"
            print("="*60)
            print("🏢 FAZA DE START: Plecare direct din HOL")
            print("="*60)
            if not controller.is_flying():
                print("   🚀 Decolare automată...")
                controller.takeoff()
                # Așteptăm pentru ca decolarea să fie stabilă și depth camera să producă cadre valide
                time.sleep(2.5)
            else:
                print("   ✅ Drona este deja în zbor.")

            print("   🔍 Așteptăm stabilizarea detecției ușii din față (4 secunde)...")
            grace_start = time.time()
            found_door = False
            while time.time() - grace_start < 4.0:
                # Profilul de coridor este ideal pentru hol/distanțe mai mari
                switch_depth_profile("corridor", "Căutare ușă HOL START")
                if nav_state.target_detected and nav_state.target_center is not None and nav_state.frame_dimensions is not None:
                    found_door = True
                    break
                time.sleep(0.1)

            if found_door:
                print("   🎯 Ușă detectată după decolare!")
            else:
                print("   ⚠️ Ușa nu a fost detectată imediat, va intra în faza de căutare (crab-style).")

        # Variabile globale pt. inregistrare HALLWAY / CAMERE
        global _vw_raw_hallway, _vw_annotated_hallway
        _vw_raw_hallway = None
        _vw_annotated_hallway = None

        def start_hallway_recordings():
            import datetime, os, cv2
            global _vw_raw_hallway, _vw_annotated_hallway
            os.makedirs('hallway_recordings', exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            _vw_raw_hallway = cv2.VideoWriter(f"hallway_recordings/raw_ai_{stamp}.mp4", cv2.VideoWriter_fourcc(*'mp4v'), 10.0, (960, 720))
            _vw_annotated_hallway = cv2.VideoWriter(f"hallway_recordings/da2_contours_{stamp}.mp4", cv2.VideoWriter_fourcc(*'mp4v'), 10.0, (960, 720))

        def stop_hallway_recordings():
            global _vw_raw_hallway, _vw_annotated_hallway
            if _vw_raw_hallway:
                _vw_raw_hallway.release()
                _vw_raw_hallway = None
            if _vw_annotated_hallway:
                _vw_annotated_hallway.release()
                _vw_annotated_hallway = None

        def update_hallway_recordings():
            import cv2
            import stream_pipeline
            global _vw_raw_hallway, _vw_annotated_hallway
            
            if not nav_state.autopilot_active:
                raise Exception("Misiune anulată. Se opresc înregistrările forțat.")

            read_obj = getattr(controller.tello, 'get_frame_read', None)
            if not read_obj: return
            frame = read_obj().frame
            if frame is None: return
            
            target_dim = (960, 720)

            if _vw_raw_hallway is not None:
                try:
                    import ai_analyzer
                    ai_frame_raw = ai_analyzer.get_analyzer().annotate_live_frame(frame.copy())
                except:
                    ai_frame_raw = frame.copy()
                
                if ai_frame_raw.shape[:2] != (720, 960):
                    ai_frame_raw = cv2.resize(ai_frame_raw, target_dim)
                _vw_raw_hallway.write(ai_frame_raw)

            if _vw_annotated_hallway is not None:
                da2_frame = getattr(stream_pipeline, 'last_depth_snapshot', None)
                if da2_frame is None:
                    da2_frame = frame.copy()
                
                if da2_frame.shape[:2] != (720, 960):
                    da2_frame = cv2.resize(da2_frame, target_dim)
                _vw_annotated_hallway.write(da2_frame)

        start_hallway_recordings()
        _orig_s_global = time.sleep
        import threading
        _autopilot_tid = threading.get_ident()
        def _sleep_with_hallway_rec(d):
            if threading.get_ident() != _autopilot_tid:
                _orig_s_global(d)
                return
            
            if not nav_state.autopilot_active:
                _orig_s_global(0.1)
                raise Exception("Aterizare forțată - autopilot oprit.")
            
            start_t = time.time()
            # buclă mică de adnotare recurentă pentru fișiere fluide
            while time.time() - start_t < d:
                if not nav_state.autopilot_active:
                    _orig_s_global(0.1)
                    raise Exception("Aterizare forțată - autopilot oprit.")
                try:
                    update_hallway_recordings()
                except Exception:
                    pass
                _to_sleep = min(0.1, d - (time.time() - start_t))
                if _to_sleep > 0:
                    _orig_s_global(_to_sleep)
                else: break
                
        # Setăm noul hook global care populează filmarea constant în pauzele de execuție
        time.sleep = _sleep_with_hallway_rec

        for room_index in range(room_count):
            current_room = room_index + 1
            nav_state.set_current_room(current_room)
            mission_path.set_current_room(current_room)
            nav_state.wall_measurements = {}
            nav_state.measurement_log = []

            # În hol (căutare/centrare ușă) folosim profilul de coridor.
            switch_depth_profile("corridor", f"CAMERA {current_room} - HOL")

            print("\n" + "#" * 60)
            print(f"🏠 CAMERA {current_room}/{room_count}")
            print("#" * 60)

            # Mică perioadă de stabilizare după decolare/mișcare,
            # ca să nu pornească crab dreapta dacă ușa este chiar în față.
            detection_grace_s = 1.2
            grace_start = time.time()
            while time.time() - grace_start < detection_grace_s:
                if (
                    nav_state.target_detected
                    and nav_state.target_center is not None
                    and nav_state.frame_dimensions is not None
                    and time.time() >= ignore_door_until_ts
                ):
                    break
                time.sleep(0.1)

            # Check rapid dacă ușa e detectată la startup (fără validare complexă care blochează)
            now_ts = time.time()
            door_detected_at_start = (
                nav_state.target_detected
                and nav_state.target_center is not None
                and nav_state.frame_dimensions is not None
                and now_ts >= ignore_door_until_ts
            )

            # FAZA 0: CĂUTARE UȘĂ (dacă nu e detectată)
            if not door_detected_at_start:
                nav_state.autopilot_status = f"CAMERA {current_room}/{room_count} - FAZA 0: Căutare ușă"
                print("="*60)
                print("🔍 FAZA 0: Căutare Ușă - DEPLASARE CRAB-STYLE")
                print("="*60)
                print("   ⚠️  Ușa nu este detectată stabil (sau lipsește)")
                print("   ↔️  Drona va merge crab-style în DREAPTA pentru a căuta o ușă...")
                print()

                search_timeout = 15  # secunde - limită de căutare
                search_interval = 0.25  # pași mai scurți pentru oprire rapidă
                search_time = 0
                search_speed = 24  # RC control: mai lent pentru control fin
                search_fb_comp = 0  # implicit fără componentă înainte (evită apropierea de peretele cu uși)
                snapshot_interval_s = 2.5  # snapshot la câteva secunde pentru debug false detections
                last_snapshot_ts = 0.0
                found_stable_door = False

                while search_time < search_timeout:
                    print(
                        f"   🔄 Se caută ușă... ({search_time:.1f}s / {search_timeout}s) - Se mișcă dreapta",
                        end="",
                    )

                    # Check if door was detected during movement
                    door_visible_now = nav_state.target_detected and nav_state.target_center is not None and nav_state.frame_dimensions is not None
                    guard_elapsed = time.time() >= ignore_door_until_ts

                    if door_visible_now and guard_elapsed:
                        print(" ✅ UȘĂ GĂSITĂ!")
                        found_stable_door = True
                        break
                    elif door_visible_now and not guard_elapsed:
                        remaining = max(0.0, ignore_door_until_ts - time.time())
                        print(f" ⏳ Ușă vizibilă, dar în guard anti-reentry ({remaining:.1f}s)")
                    else:
                        print()

                    if stream_pipeline is not None:
                        now_ts = time.time()
                        if now_ts - last_snapshot_ts >= snapshot_interval_s:
                            try:
                                snap_name = f"door_search_{int(search_time * 10):03d}"
                                stream_pipeline.save_measurement_snapshot(snap_name, None, point_name='center')
                                last_snapshot_ts = now_ts
                            except Exception as e:
                                print(f"      ⚠️ Snapshot debug eșuat: {e}")

                    # Menține crab lateral: dacă e prea aproape de peretele cu uși,
                    # aplică un mic retreat înapoi în timp ce strafează dreapta.
                    search_fb_cmd = search_fb_comp

                    # Merge crab-style în dreapta în impulsuri scurte,
                    # ca să poată opri imediat când ușa devine vizibilă.
                    controller.tello.send_rc_control(search_speed, search_fb_cmd, 0, 0)
                    print(
                        f"      [DEBUG] RC control trimis: lr={search_speed}, "
                        f"fb={search_fb_cmd}, ud=0, yaw=0"
                    )

                    step_elapsed = 0.0
                    micro_step = 0.05
                    door_found_during_motion = False
                    while step_elapsed < search_interval:
                        time.sleep(micro_step)
                        step_elapsed += micro_step
                        search_time += micro_step
                        mission_path.record_timed_rc(search_speed, search_fb_cmd, 0, micro_step, label="phase0_search")

                        if (
                            nav_state.target_detected
                            and nav_state.target_center is not None
                            and nav_state.frame_dimensions is not None
                            and time.time() >= ignore_door_until_ts
                        ):
                            print("      🛑 Ușă detectată în mișcare -> STOP imediat")
                            controller.tello.send_rc_control(0, 0, 0, 0)
                            found_stable_door = True
                            door_found_during_motion = True
                            break

                    if door_found_during_motion:
                        break

                # Stop căutare
                print("   ✋ STOP căutare")
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.5)

                if not found_stable_door:
                    print(f"\n❌ Nu s-a găsit nicio ușă în {search_timeout}s")
                    nav_state.autopilot_status = "❌ Căutare eșuată - nicio ușă"
                    return

                print("✅ Ușă găsită! Continuare misiune...\n")
            else:
                print("✅ Ușă detectată stabil de la start - se sare peste FAZA 0")

            if not nav_state.target_center or not nav_state.frame_dimensions:
                raise RuntimeError("Nu există target center")

            target_x, target_y = nav_state.target_center
            frame_w, frame_h = nav_state.frame_dimensions
            frame_center_x, frame_center_y = frame_w // 2, frame_h // 2

            print(f"🎯 TARGET DETECTAT: ({target_x}, {target_y})")
            print(f"📷 FRAME CENTER: ({frame_center_x}, {frame_center_y})")

            # Calculează offset-ul
            offset_x = target_x - frame_center_x
            offset_y = target_y - frame_center_y

            print(f"📏 OFFSET: dx={offset_x}px, dy={offset_y}px\n")

            # FAZA 1 + FAZA 2: retry automat (stil backup)
            max_entry_attempts = 3
            entry_completed = False

            for entry_attempt in range(1, max_entry_attempts + 1):
                # FAZA 1: ALINIERE LATERALĂ (STÂNGA-DREAPTA) - CRAB STYLE
                nav_state.autopilot_status = f"CAMERA {current_room}/{room_count} - FAZA 1: Aliniere laterală"
                print("="*60)
                print(f"🎯 FAZA 1: Aliniere Laterală pe Axa X (CRAB-STYLE) - încercarea {entry_attempt}/{max_entry_attempts}")
                print("="*60)
                print("   ↔️  Drona se deplasează stânga-dreapta fără rotație")

                mission_path.begin_phase("centering", "Centrare ușă", room=current_room)
                is_centered = center_door_before_forward(
                    "FAZA 1",
                    tolerance_px=70,
                    max_iterations=9,
                    stable_required=1,
                    soft_accept_px=105,
                )
                mission_path.end_phase()
                if not is_centered:
                    if entry_attempt < max_entry_attempts:
                        print("   ↪️  Ținta nu e stabilă încă, repoziționare scurtă și retry automat...")
                        _rec_offset = 0
                        if nav_state.target_center and nav_state.frame_dimensions:
                            _rx, _ = nav_state.target_center
                            _rw, _ = nav_state.frame_dimensions
                            _rec_offset = _rx - (_rw // 2)
                        _rec_dir = 1 if _rec_offset > 0 else -1
                        print(f"   ↩️  Recovery dir={'dreapta' if _rec_dir > 0 else 'stânga'} (offset={_rec_offset}px)")
                        controller.tello.send_rc_control(_rec_dir * 12, 0, 0, 0)
                        time.sleep(0.25)
                        controller.tello.send_rc_control(0, 0, 0, 0)
                        time.sleep(0.35)
                        continue

                    nav_state.autopilot_status = "❌ Centrare eșuată"
                    print("❌ Nu pot continua: ușa nu este centrată stabil")
                    return

                print("✓ Aliniere laterală completă")
                print("✅ CENTRARE COMPLETĂ!\n")

                if distance_hold_enabled:
                    print("=" * 60)
                    print("🛑 TRANZIȚIE: FAZA 1 (centrare laterală) TERMINATĂ")
                    print("   ✅ STOP complet după centrare (fără corecții mixte)")
                    print("   ▶️ Urmează strict controlul față/spate în FAZA 1.5")
                    print("=" * 60)
                    drone_stabilize(controller, level="normal", label="post-centrare FAZA 1")

                if distance_hold_enabled:
                    nav_state.autopilot_status = (
                        f"CAMERA {current_room}/{room_count} - FAZA 1.5: Stabilizare distanță ușă"
                    )
                    print("=" * 60)
                    print("📏 FAZA 1.5: Stabilizare distanță față de ușă (opțională)")
                    print("=" * 60)
                    mission_path.begin_phase("distance_hold", "Menținere distanță", room=current_room)
                    distance_hold_ok = hold_entry_distance_after_center(
                        "FAZA 1.5",
                        target_ratio=distance_hold_target_ratio,
                        deadband=distance_hold_deadband,
                        ema_alpha=distance_hold_ema_alpha,
                        max_iterations=distance_hold_max_iterations,
                        stable_required=distance_hold_stable_required,
                        pulse_s=distance_hold_pulse_s,
                        pause_s=distance_hold_pause_s,
                        metric_method=distance_hold_method,
                        accept_mode=distance_hold_accept_mode,
                        tolerance_px=70,
                    )
                    mission_path.end_phase()
                    if distance_hold_ok:
                        print("✓ FAZA 1.5 finalizată\n")
                    else:
                        print("❌ FAZA 1.5 eșuată (distanță instabilă)\n")
                        if distance_hold_abort_on_fail:
                            nav_state.autopilot_status = "❌ FAZA 1.5 eșuată - misiune oprită"
                            print("🛑 Oprire misiune: nu rulez OCR/FAZA 2 după eșec FAZA 1.5")
                            controller.tello.send_rc_control(0, 0, 0, 0)
                            return
                        print("⚠️ Continui misiunea (fără revenire la centrare) după eșec FAZA 1.5\n")
                else:
                    print("⏭️  FAZA 1.5 dezactivată (ENTRY_DISTANCE_HOLD_ENABLED=0)")

                # Stabilizare înainte de OCR — drona trebuie să fie complet staționară
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.6)
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.8)
                print("   ✋ Stabilizare pre-OCR completă → pornesc rotația OCR")

                # OCR fix înainte de comanda de intrare în cameră,
                # după o rotație stânga 30° și revenire la heading-ul inițial.
                detect_room_label_with_rotation(current_room, degrees=30)

                post_ocr_micro_center_enabled = (
                    os.environ.get("POST_OCR_MICRO_CENTER_ENABLED", "1").strip().lower()
                    in ("1", "true", "yes", "on")
                )
                post_ocr_micro_center_tolerance_px = _read_env_int(
                    "POST_OCR_MICRO_CENTER_TOLERANCE_PX", 70
                )
                post_ocr_micro_center_ticks = _read_env_int(
                    "POST_OCR_MICRO_CENTER_MAX_TICKS", 2
                )

                if post_ocr_micro_center_enabled and post_ocr_micro_center_ticks > 0:
                    print("   🎯 Post-OCR: verific micro-recentrare...")
                    micro_recenter_after_ocr(
                        "POST-OCR RECENTER",
                        tolerance_px=post_ocr_micro_center_tolerance_px,
                        max_ticks=post_ocr_micro_center_ticks,
                    )
                else:
                    print("   ⏭️  Post-OCR micro-recentrare dezactivată")

                # FAZA 2: AVANSARE ÎNAINTE CU CAMERA DESCHISĂ SPRE UȘĂ
                nav_state.autopilot_status = f"CAMERA {current_room}/{room_count} - FAZA 2: Intrare prin ușă (1.8m)"
                print("🎬 FAZA 2: Avansare 1.8 metri înainte (crab-style pe axa X)")
                print("   ↔️  Drona se deplasează cu fața înainte (ca omul cu camera)")
                print()

                # Distanță țintă: mergi 1.8 metri înainte
                forward_distance = 180  # cm = 1.8 metri
                forward_time_needed = forward_distance / 35  # 35 cm/s pentru 1.8m

                min_safe_distance = 0.2  # metri - mai aproape de pereți
                max_safe_distance = 0.5  # metri - distanță mai mică

                forward_speed = 35  # cm/s - viteză standard de intrare
                max_forward_time = 20  # secunde - limită de siguranță
                check_interval = 0.5  # control periodic, avans continuu
                tracking_deadband_px = 50
                max_lateral_correction = 14
                tracking_gain = 0.10

                total_time = 0

                while total_time < max_forward_time:
                    # Verifică distanțele de la margini (dacă sunt în zona bună)
                    if nav_state.edge_distances:
                        left_dist, right_dist = nav_state.edge_distances

                        # Dacă deja suntem în zona sigură, continuă
                        if (left_dist >= min_safe_distance and left_dist <= max_safe_distance) or \
                           (right_dist >= min_safe_distance and right_dist <= max_safe_distance):
                            print(f"📏 ✅ Margini în zona sigură: L={left_dist:.2f}m, R={right_dist:.2f}m")
                        else:
                            print(f"📏 🔄 Margini: L={left_dist:.2f}m, R={right_dist:.2f}m")

                    # Avansează înainte continuu + corecții laterale din mers (dacă e nevoie)
                    lateral_correction = 0
                    if nav_state.target_center and nav_state.frame_dimensions:
                        current_target_x, _ = nav_state.target_center
                        current_frame_w, _ = nav_state.frame_dimensions
                        current_center_x = current_frame_w // 2
                        current_offset_x = current_target_x - current_center_x

                        if abs(current_offset_x) > tracking_deadband_px:
                            lateral_correction = int(np.clip(current_offset_x * tracking_gain, -max_lateral_correction, max_lateral_correction))

                    print(
                        f"   ➡️  Avansare... (timp: {total_time:.1f}s / {forward_time_needed:.1f}s, lr={lateral_correction})"
                    )
                    controller.tello.send_rc_control(lateral_correction, forward_speed, 0, 0)
                    time.sleep(check_interval)
                    mission_path.record_timed_rc(
                        lateral_correction,
                        forward_speed,
                        0,
                        check_interval,
                        label="phase2_entry",
                    )
                    total_time += check_interval

                    # Oprește dacă a avansat suficient
                    if total_time >= forward_time_needed:
                        print("✅ S-a avansat 1.8 metri prin ușă!")
                        break

                # Stop final - asigură stop complet!
                print("\n" + "="*60)
                print("🛑 FAZA 2: TERMINATĂ - STOP COMPLET")
                print("="*60)
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(2)

                # După intrare în cameră trecem pe profilul calibrat pentru interior.
                switch_depth_profile("room", f"CAMERA {current_room} - INTERIOR")
                nav_state.mark_room_entered(current_room)

                entry_completed = True
                break

            if not entry_completed:
                nav_state.autopilot_status = "❌ Intrare eșuată"
                print("❌ Intrare eșuată după retry automat")
                return

            # ========== BIFURCĂ PE SCAN_MODE ==========
            if stream_pipeline is not None:
                stream_pipeline.start_ai_scan(current_room, scan_mode=scan_mode)
                stream_pipeline.start_slam_session(
                    mission_id=f"room_{current_room}_{nav_state.mission_id if hasattr(nav_state, 'mission_id') else 'auto'}"
                )

            mission_path.begin_phase("scan", "Scanare", room=current_room)
            if scan_mode == "fast":
                execute_fast_scan(controller)
            elif scan_mode == "medium":
                execute_medium_scan(controller)
            else:
                execute_complex_scan(controller)
            mission_path.end_phase()

            if stream_pipeline is not None:
                report_path = stream_pipeline.stop_ai_scan()
                if report_path:
                    print(f"📊 REPORT GENERAT: {report_path}")
                slam_result = stream_pipeline.stop_slam_session()
                if slam_result and slam_result.get('stats', {}).get('frames_sent', 0) > 0:
                    print(f"🗺️ SLAM: {slam_result['stats']['frames_sent']} frame-uri, "
                          f"hartă {'disponibilă' if slam_result.get('map') else 'indisponibilă'}, "
                          f"cloud {slam_result.get('cloud_points', 0)} puncte")

            mission_path.note_event(f"room_{current_room}_scan_complete")

            # Tranziție pe hol pentru camera următoare
            if current_room < room_count:
                nav_state.autopilot_status = f"TRANZIȚIE {current_room}->{current_room + 1}: crab 0.5m + 180° + crab dreapta"
                print("\n" + "=" * 60)
                print(f"🔁 TRANZIȚIE: Pregătire pentru CAMERA {current_room + 1}/{room_count}")
                print("=" * 60)

                yaw_speed = 80
                rotation_time_90 = 1.125
                right_180_cmd = 205  # comandă empirică pentru ~180° real
                rotation_duration = rotation_time_90 * (right_180_cmd / 90.0)

                transition_crab_speed = 28
                transition_pre_rotate_distance_m = 1.0
                transition_pre_rotate_time = (transition_pre_rotate_distance_m * 100.0) / transition_crab_speed

                print(
                    "   ↔️  Tranziție 1/3: crab-style spre stânga 1.0m "
                    "(cu orientarea curentă, spatele rămâne spre ușa de ieșire)"
                )
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.2)
                controller.tello.send_rc_control(-transition_crab_speed, right_crab_fb_comp, 0, 0)
                time.sleep(transition_pre_rotate_time)
                mission_path.record_timed_rc(
                    -transition_crab_speed,
                    right_crab_fb_comp,
                    0,
                    transition_pre_rotate_time,
                    label="transition_crab_left",
                )
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.4)

                print("   🔄 Tranziție 2/3: rotație reală 180° pe hol (revenire cu fața către peretele cu uși)")
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.2)
                try:
                    # Comandă SDK: rotație reală 180°
                    controller.tello.rotate_clockwise(180)
                    mission_path.record_rotation(180, clockwise=True, label="transition_rotate_180")
                except Exception as rotate_err:
                    print(f"   ⚠️ rotate_clockwise(180) a eșuat ({rotate_err}); fallback pe RC timed")
                    controller.tello.send_rc_control(0, 0, 0, yaw_speed)
                    time.sleep(rotation_duration)
                    mission_path.record_timed_rc(0, 0, yaw_speed, rotation_duration, label="transition_rotate_180_fallback")
                    controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.8)

                transition_crab_time = 1.2
                print("   ↔️  Tranziție 3/3: shift crab-style spre dreapta pentru continuarea căutării")
                controller.tello.send_rc_control(transition_crab_speed, right_crab_fb_comp, 0, 0)
                time.sleep(transition_crab_time)
                mission_path.record_timed_rc(
                    transition_crab_speed,
                    right_crab_fb_comp,
                    0,
                    transition_crab_time,
                    label="transition_crab_right",
                )
                controller.tello.send_rc_control(0, 0, 0, 0)
                time.sleep(0.5)

                nav_state.target_detected = False
                nav_state.target_center = None
                nav_state.target_bbox = None
                ignore_door_until_ts = time.time() + 2.0

                print("   ✅ Tranziție completă - se caută următoarea ușă spre dreapta")

        nav_state.autopilot_status = "✅ Misiune completă!"
        print("\n✅ ✅ ✅ MISIUNE COMPLETĂ CU SUCCES! ✅ ✅ ✅")
        print("="*60 + "\n")

        # Aterizare automată la finalul misiunii — altfel drona rămâne în hover
        # până expiră timeout-ul intern și aterizează singură.
        try:
            controller.tello.send_rc_control(0, 0, 0, 0)
            time.sleep(0.5)
            print("🛬 Aterizare automată la final de misiune...")
            controller.tello.land()
            print("✅ Drona a aterizat.")
        except Exception as land_err:
            print(f"⚠️ Aterizare automată eșuată: {land_err}")

    except Exception as e:
        mission_path_error = str(e)
        nav_state.autopilot_status = f"❌ Eroare: {str(e)[:50]}"
        print(f"❌ Eroare în autopilot: {e}")
        import traceback
        traceback.print_exc()

        # Stop de urgență
        try:
            controller.tello.send_rc_control(0, 0, 0, 0)
        except:
            pass

    finally:
        try:
            stop_stairwell_recordings()
        except:
            pass

        try:
            stop_hallway_recordings()
        except:
            pass
            
        try:
            if '_orig_s_global' in locals():
                time.sleep = _orig_s_global
        except:
            pass

        path_result = mission_path.finalize_and_save(
            success=nav_state.autopilot_status.startswith("✅"),
            error=mission_path_error,
        )
        if path_result:
            print(f"🗺️ Mission path JSON: {path_result.get('json_path')}")
            if path_result.get("png_path"):
                print(f"🖼️ Mission path PNG: {path_result.get('png_path')}")
            elif path_result.get("plot_error"):
                print(f"⚠️ Nu am putut genera PNG mission path: {path_result.get('plot_error')}")

        # Persistă telemetria (module/comenzi/EMA) ACUM, cât last_telemetry e proaspăt
        # calculată de finalize_and_save. Garantează salvarea chiar dacă misiunea a fost
        # întreruptă (land manual / aterizare forțată) și completată deja din status-poll.
        try:
            import mission_tracker
            mission_tracker.persist_telemetry()
        except Exception as _tel_err:
            print(f"⚠️ Nu am putut persista telemetria: {_tel_err}")

        nav_state.autopilot_active = False
        if not nav_state.autopilot_status.startswith("✅"):
            nav_state.autopilot_status = "Inactiv"
