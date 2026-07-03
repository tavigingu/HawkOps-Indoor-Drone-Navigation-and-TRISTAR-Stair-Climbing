import time
from navigation.common import execute_exit_sequence, drone_stabilize
import navigation.state as nav_state
import navigation.mission_path as mission_path


def execute_medium_scan(controller):
    """
    MEDIUM SCAN (fostul FAST): Intrare → +1/3 front → 360° → -1/3 front → 180° + exit
    După FAZA 2 (intrare 1.5m):
    1. Măsoară distanța front
    2. Merge înainte 1/3 × front_dist
    3. 360° rota pe loc (scanare)
    4. Merge înapoi 1/3 × front_dist (revine la ușă)
    5. Exit: 180° rotație + door center + 2.0m înainte
    """
    try:
        import stream_pipeline
    except Exception:
        stream_pipeline = None

    # FAZA 3: MĂSURARE FRONT (simplă)
    nav_state.autopilot_status = "FAZA 3: Măsurare front"
    print("\n" + "="*60)
    print("📏 FAZA 3: Măsurare Distanță Front")
    print("="*60)

    print("   📐 Măsurare perete FAȚĂ...")
    time.sleep(0.8)
    front_distance = None
    if nav_state.edge_distances:
        left_dist, right_dist = nav_state.edge_distances
        front_distance = (left_dist + right_dist) / 2.0
        nav_state.wall_measurements['front'] = front_distance
        nav_state.log_wall_measurement("front", front_distance)
        print(f"   ✅ Perete FAȚĂ: {front_distance:.2f}m")
    else:
        nav_state.log_wall_measurement("front", None)
        print(f"   ⚠️  Perete FAȚĂ: măsurare eșuată")
        front_distance = 3.0  # Default fallback

    if stream_pipeline is not None:
        try:
            stream_pipeline.save_measurement_snapshot('front', front_distance, point_name='center')
        except Exception as e:
            print(f"   ⚠️  Nu am putut salva snapshot front: {e}")

    # FAZA 3b: AVANSARE 1/3 FRONT
    nav_state.autopilot_status = "FAZA 3b: Avansare în cameră"
    print("\n" + "="*60)
    print("➡️ FAZA 3b: Avansare 1/3 × Front Distance")
    print("="*60)

    forward_scan_distance_m = front_distance / 3.0
    forward_scan_speed = 30  # cm/s
    forward_scan_time = (forward_scan_distance_m * 100.0) / forward_scan_speed
    move_check_interval = 0.2

    print(f"\n   ➡️  Avansare: {forward_scan_distance_m:.2f}m (~{forward_scan_time:.1f}s)")
    elapsed = 0.0
    while elapsed < forward_scan_time:
        controller.tello.send_rc_control(0, forward_scan_speed, 0, 0)
        time.sleep(move_check_interval)
        mission_path.record_timed_rc(0, forward_scan_speed, 0, move_check_interval, label="medium_forward")
        elapsed += move_check_interval
    controller.tello.send_rc_control(0, 0, 0, 0)
    print("   ✅ Avansare completă")
    drone_stabilize(controller, level="full", label="post-avansare → pre-360°")

    # FAZA 3c: 360° ROTA
    nav_state.autopilot_status = "FAZA 3c: Scanare 360°"
    print("\n" + "="*60)
    print("🌐 FAZA 3c: Rota 360° Scanare Cameră")
    print("="*60)

    yaw_speed = 80
    rotation_time_90 = 1.125
    full_rotation_yaw = 430
    full_rotation_time = rotation_time_90 * (full_rotation_yaw / 90.0)

    print(f"\n   🔄 Rota 340° pe loc...")
    drone_stabilize(controller, level="full", label="pre-rotație 360°")
    controller.tello.send_rc_control(0, 0, 0, yaw_speed)
    time.sleep(full_rotation_time)
    mission_path.record_timed_rc(0, 0, yaw_speed, full_rotation_time, label="medium_rotate_scan")
    controller.tello.send_rc_control(0, 0, 0, 0)
    print("   ✅ 340° rota completă")
    time.sleep(1.0)

    # FAZA 3d: REVENIRE ÎNAPOI 1/3 FRONT
    nav_state.autopilot_status = "FAZA 3d: Revenire la ușă"
    print("\n" + "="*60)
    print("↙️ FAZA 3d: Revenire 1/3 × Front Distance")
    print("="*60)

    print(f"\n   ↙️  Revenire înapoi: {forward_scan_distance_m:.2f}m (~{forward_scan_time:.1f}s)")
    elapsed = 0.0
    while elapsed < forward_scan_time:
        controller.tello.send_rc_control(0, -forward_scan_speed, 0, 0)
        time.sleep(move_check_interval)
        mission_path.record_timed_rc(0, -forward_scan_speed, 0, move_check_interval, label="medium_return")
        elapsed += move_check_interval
    controller.tello.send_rc_control(0, 0, 0, 0)
    print("   ✅ Revenire completă - drona e la ușă")
    drone_stabilize(controller, level="normal", label="post-revenire înapoi / pre-180°")

    # FAZA 5: EXIT (aceeași ca Complex, cu rotație finală puțin mărită)
    execute_exit_sequence(controller, turn_back_degrees=215)
