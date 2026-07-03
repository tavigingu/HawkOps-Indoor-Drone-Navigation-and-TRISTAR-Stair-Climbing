import time
import os
import numpy as np

import navigation.state as nav_state
import navigation.mission_path as mission_path


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


def drone_stabilize(controller, level="normal", label=""):
    """Stabilizare standard drone după orice mișcare.

    Niveluri:
      light  – 0.3s + 0.3s  (corecții fine, post-puls mic)
      normal – 0.5s + 0.7s  (tranziții generale)
      full   – 0.6s + 1.0s  (înainte de rotații, post-avansare lungă)
    """
    pauses = {
        "light":  (0.3, 0.3),
        "normal": (0.5, 0.7),
        "full":   (0.6, 1.0),
    }
    p1, p2 = pauses.get(level, pauses["normal"])
    tag = f" [{label}]" if label else ""
    
    tello_obj = getattr(controller, 'tello', controller)
    
    tello_obj.send_rc_control(0, 0, 0, 0)
    time.sleep(p1)
    tello_obj.send_rc_control(0, 0, 0, 0)
    time.sleep(p2)
    print(f"   🧘 Stabilizare {level}{tag} completă ({p1+p2:.1f}s)")


def _hold_door_distance_with_ema(
    controller,
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
    tolerance_px,
):
    ratio_ema = None
    stable_hits = 0
    _ = tolerance_px
    tick_speed = int(np.clip(abs(_read_env_int("ENTRY_DISTANCE_HOLD_FB_TICK_SPEED", 14)), 8, 20))
    selected_metric = "full_frame_blue_ratio"

    if metric_method != selected_metric:
        print(
            f"   ℹ️ {phase_label}: ignor metric_method='{metric_method}' și folosesc strict '{selected_metric}'"
        )

    if accept_mode not in ("raw", "ema"):
        print(f"   ℹ️ {phase_label}: accept_mode invalid '{accept_mode}', fallback='raw'")
        accept_mode = "raw"

    def _compute_fb_speed(current_ratio):
        # Pentru full-frame blue: valoare mai mică => drona e prea departe => mergi înainte.
        # Valoare mai mare => e prea aproape => mergi înapoi.
        ratio_error = target_ratio - current_ratio
        if abs(ratio_error) <= 0.003:
            return 0
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
            return True

        if fb_speed != 0:
            print(f"   🕹️ {phase_label}: tick față/spate (fb={fb_speed}, pulse={pulse_s:.2f}s)")
            controller.tello.send_rc_control(0, fb_speed, 0, 0)
            time.sleep(pulse_s)
            mission_path.record_timed_rc(0, fb_speed, 0, pulse_s, label="exit_distance_hold")
            controller.tello.send_rc_control(0, 0, 0, 0)
            time.sleep(pause_s)
        else:
            controller.tello.send_rc_control(0, 0, 0, 0)
            time.sleep(0.15)

    print(f"   ⚠️ {phase_label}: timeout, continui ieșirea fără blocare")
    controller.tello.send_rc_control(0, 0, 0, 0)
    time.sleep(0.15)
    return True

def execute_exit_sequence(controller, include_turn_back=True, turn_back_degrees=205):
    """
    FAZA 5: Revenire spre ușă + recentrare + ieșire 2.0m
    include_turn_back=True: face rotația de întoarcere spre ușă (medium/complex)
    include_turn_back=False: sare rotația (fast nou, deja orientat spre ușă)
    turn_back_degrees: grade comandate pentru rotația finală (compensate pentru deriva reală)
    """
    nav_state.autopilot_status = "FAZA 5: Revenire spre ușă și ieșire"
    print("\n" + "="*60)
    print("🚪 FAZA 5: Revenire spre ușă + recentrare + ieșire")
    print("="*60)

    yaw_speed = 80
    rotation_time_90 = 1.125
    if include_turn_back:
        # Compensare: grade comandate > grade reale pentru revenire spre ușă
        rotation_duration = rotation_time_90 * (turn_back_degrees / 90.0)
        print(f"\n   🔄 Întoarcere finală: {turn_back_degrees}° spre ușă...")
        controller.tello.send_rc_control(0, 0, 0, yaw_speed)
        time.sleep(rotation_duration)
        mission_path.record_timed_rc(0, 0, yaw_speed, rotation_duration, label="exit_turn_back")
        controller.tello.send_rc_control(0, 0, 0, 0)
        drone_stabilize(controller, level="normal", label="post-180° turn-back")
        print("   ✅ Întoarcere completă")
    else:
        print("\n   ✅ Întoarcere finală omisă (deja orientat spre ușă)")

    # CĂUTARE UȘĂ post-întoarcere: dacă YOLO nu vede ușa, continuă crab DREAPTA
    # (după rotația de 180°, direcția fizică a lui S5 = crab stânga devine crab dreapta)
    nav_state.autopilot_status = "CĂUTARE UȘĂ: crab post-180°"
    print("\n" + "="*60)
    print("🔍 CĂUTARE UȘĂ: continuă crab dreapta până la detecție stabilă")
    print("="*60)

    _door_search_speed   = 30      # cm/s — crab dreapta (simetric cu S5 care era stânga)
    _door_search_tick_s  = 0.15    # interval tick
    _door_search_timeout = 6.0     # max secunde de căutare
    _stable_needed       = 3       # frame-uri consecutive cu detecție
    _ds_elapsed          = 0.0
    _ds_streak           = 0

    if nav_state.target_center and nav_state.frame_dimensions:
        print("   ✅ Detecție ușă deja prezentă după întoarcere - sar căutarea")
    else:
        print(f"   ↔️  Căutare ușă: crab dreapta max {_door_search_timeout:.1f}s...")
        while _ds_elapsed < _door_search_timeout:
            if nav_state.target_center and nav_state.frame_dimensions:
                _ds_streak += 1
                print(
                    f"   🎯 Detecție ușă [{_ds_streak}/{_stable_needed}]: "
                    f"center={nav_state.target_center}  elapsed={_ds_elapsed:.2f}s"
                )
                if _ds_streak >= _stable_needed:
                    print("   ✅ Detecție stabilă - opresc căutarea crab")
                    controller.tello.send_rc_control(0, 0, 0, 0)
                    drone_stabilize(controller, level="light", label="post-door-search found")
                    break
            else:
                _ds_streak = 0  # resetează dacă detectia dispare

            # Crab DREAPTA (+lr) — continuă traseul fizic al S5 după flip 180°
            controller.tello.send_rc_control(_door_search_speed, 0, 0, 0)
            time.sleep(_door_search_tick_s)
            mission_path.record_timed_rc(_door_search_speed, 0, 0, _door_search_tick_s, label="door_search_post_turn")
            _ds_elapsed += _door_search_tick_s
        else:
            controller.tello.send_rc_control(0, 0, 0, 0)
            print(f"   ⚠️  Timeout căutare ușă ({_door_search_timeout:.1f}s) - continui cu exit oricum")
            drone_stabilize(controller, level="light", label="post-door-search timeout")

    # Recentrare pe ușă înainte de ieșire
    print("\n   🎯 Recentrare pe ușă înainte de ieșire...")
    center_tolerance_x = 25
    max_center_iterations = 14
    lateral_gain = 0.10
    lateral_control_sign = 1
    previous_abs_offset = None
    for iteration in range(max_center_iterations):
        if not nav_state.target_center or not nav_state.frame_dimensions:
            print("   ⚠️  Target ușă indisponibil - recentrare omisă")
            break

        target_x, _ = nav_state.target_center
        frame_w, _ = nav_state.frame_dimensions
        frame_center_x = frame_w // 2
        offset_x = target_x - frame_center_x

        if abs(offset_x) <= center_tolerance_x:
            print(f"   ✅ Ușa este centrată (offset {offset_x}px)")
            break

        current_abs_offset = abs(offset_x)
        if current_abs_offset > 220:
            pulse_time = 0.28
        elif current_abs_offset > 140:
            pulse_time = 0.22
        elif current_abs_offset > 90:
            pulse_time = 0.16
        else:
            pulse_time = 0.12

        if (
            previous_abs_offset is not None
            and current_abs_offset > previous_abs_offset + 10
        ):
            print(
                f"   ⚠️  Recentrare: zgomot/salt detector ({previous_abs_offset}px -> {current_abs_offset}px). Îmi continui direcția fizică."
            )

        lateral_speed = int(np.clip(lateral_control_sign * offset_x * lateral_gain, -16, 16))
        if lateral_speed == 0:
            lateral_speed = 8 if offset_x > 0 else -8

        print(
            f"   🔄 Recentrare {iteration + 1}/{max_center_iterations}: "
            f"offset={offset_x}px, lr={lateral_speed}, pulse={pulse_time:.2f}s"
        )
        controller.tello.send_rc_control(lateral_speed, 0, 0, 0)
        time.sleep(pulse_time)
        mission_path.record_timed_rc(lateral_speed, 0, 0, pulse_time, label="exit_recenter")
        controller.tello.send_rc_control(0, 0, 0, 0)
        time.sleep(0.35)

        previous_abs_offset = current_abs_offset

    drone_stabilize(controller, level="normal", label="post-recentrare ușă exit")

    distance_hold_enabled = (
        os.environ.get("ENTRY_DISTANCE_HOLD_ENABLED", "1").strip().lower()
        in ("1", "true", "yes", "on")
    )

    if distance_hold_enabled:
        distance_hold_target_ratio = _read_env_float("ENTRY_DISTANCE_HOLD_TARGET_RATIO", 0.50)
        distance_hold_deadband = _read_env_float("ENTRY_DISTANCE_HOLD_DEADBAND", 0.05)
        distance_hold_ema_alpha = _read_env_float("ENTRY_DISTANCE_HOLD_EMA_ALPHA", 0.18)
        distance_hold_method = os.environ.get("ENTRY_DISTANCE_HOLD_METHOD", "full_frame_blue_ratio").strip().lower()
        distance_hold_accept_mode = os.environ.get("ENTRY_DISTANCE_HOLD_ACCEPT_MODE", "raw").strip().lower()
        distance_hold_max_iterations = _read_env_int("ENTRY_DISTANCE_HOLD_MAX_ITERS", 12)
        distance_hold_stable_required = _read_env_int("ENTRY_DISTANCE_HOLD_STABLE_REQUIRED", 3)
        distance_hold_pulse_s = _read_env_float("ENTRY_DISTANCE_HOLD_PULSE_S", 0.22)
        distance_hold_pause_s = _read_env_float("ENTRY_DISTANCE_HOLD_PAUSE_S", 0.15)

        try:
            import stream_pipeline
            ok, message, available = stream_pipeline.set_active_calibration_profile("corridor")
            if ok:
                print("🎚️  [FAZA 5.5] calibrare depth -> corridor")
            else:
                print(f"⚠️  [FAZA 5.5] nu pot seta profilul 'corridor': {message} | disponibile: {available}")
        except Exception as switch_err:
            print(f"⚠️  [FAZA 5.5] eroare la schimbare profil calibrare: {switch_err}")

        print("\n   📏 FAZA 5.5: Stabilizare distanță față de ușă înainte de ieșire...")
        _hold_door_distance_with_ema(
            controller,
            phase_label="FAZA 5.5",
            target_ratio=distance_hold_target_ratio,
            deadband=distance_hold_deadband,
            ema_alpha=distance_hold_ema_alpha,
            max_iterations=distance_hold_max_iterations,
            stable_required=distance_hold_stable_required,
            pulse_s=distance_hold_pulse_s,
            pause_s=distance_hold_pause_s,
            metric_method=distance_hold_method,
            accept_mode=distance_hold_accept_mode,
            tolerance_px=center_tolerance_x,
        )
    else:
        print("\n   ⏭️  FAZA 5.5 dezactivată (ENTRY_DISTANCE_HOLD_ENABLED=0)")

    drone_stabilize(controller, level="normal", label="pre-ieșire hol")

    # Ieșire pe hol pe aceeași distanță ca intrarea (cu corecție laterală continuă)
    hall_exit_distance_m = 1.8
    hall_exit_speed = 35  # cm/s
    hall_exit_duration = (hall_exit_distance_m * 100.0) / hall_exit_speed
    move_check_interval = 0.2
    exit_lateral_gain = 0.08   # sensibilitate corecție (px → cm/s)
    exit_lateral_max = 15      # viteza laterală maximă la corecție (cm/s)
    exit_center_tolerance = 50  # px — sub această valoare nu se mai corectează
    print(f"\n   ➡️  Ieșire pe hol: {hall_exit_distance_m:.2f}m (~{hall_exit_duration:.1f}s) + corecție laterală activă")
    elapsed = 0.0
    while elapsed < hall_exit_duration:
        lateral_speed = 0
        if nav_state.target_center and nav_state.frame_dimensions:
            target_x, _ = nav_state.target_center
            frame_w, _ = nav_state.frame_dimensions
            offset_x = target_x - (frame_w // 2)
            if abs(offset_x) > exit_center_tolerance:
                lateral_speed = int(np.clip(offset_x * exit_lateral_gain,
                                             -exit_lateral_max, exit_lateral_max))
                print(f"   ↔️  Corecție exit: offset={offset_x:+d}px → lr={lateral_speed}")
        controller.tello.send_rc_control(lateral_speed, hall_exit_speed, 0, 0)
        time.sleep(move_check_interval)
        mission_path.record_timed_rc(lateral_speed, hall_exit_speed, 0, move_check_interval, label="exit_hall")
        elapsed += move_check_interval
    controller.tello.send_rc_control(0, 0, 0, 0)
    print("   ✅ Ieșire pe hol finalizată")

    controller.tello.send_rc_control(0, 0, 0, 0)
    nav_state.autopilot_status = "FAZA 5: Ieșire pe hol finalizată"
    nav_state.mark_room_exited()
    print("\n✅ FAZA 5 COMPLETĂ - drona a revenit pe hol")
    print("="*60 + "\n")
