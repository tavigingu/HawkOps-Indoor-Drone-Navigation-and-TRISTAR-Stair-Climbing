import time
from navigation.common import execute_exit_sequence, drone_stabilize
import navigation.state as nav_state
import navigation.mission_path as mission_path


def execute_complex_scan(controller):
    """
    COMPLEX SCAN: Crab-style 5 segmente perimetru (modul original)
    După FAZA 2 se execută FAZA 3-5 din versiunea inițială
    """
    try:
        import stream_pipeline
    except Exception:
        stream_pipeline = None
    
    # FAZA 3: MĂSURĂTORI PEREȚI (FAȚĂ, DREAPTA, STÂNGA) + REPOZIȚIONARE SPRE UȘĂ
    nav_state.autopilot_status = "FAZA 3: Măsurători pereți"
    print("\n" + "="*60)
    print("📏 FAZA 3: Măsurători Pereți - SCANARE CAMEREI")
    print("="*60)
    print("   Drona măsoară distanțele către pereți...")
    print()

    # Așteaptă stabilizare pentru măsurare precisă
    drone_stabilize(controller, "normal", "start FAZA 3")

    # Măsoară peretele din FAȚĂ
    print("   📐 Măsurare perete FAȚĂ (înainte în cameră)...")
    drone_stabilize(controller, "light", "pre-măsurare FAȚĂ")
    front_distance = None
    if nav_state.edge_distances:
        left_dist, right_dist = nav_state.edge_distances
        # Estimare distanță față bazată pe marginile laterale
        front_distance = (left_dist + right_dist) / 2.0
        nav_state.wall_measurements['front'] = front_distance
        nav_state.log_wall_measurement("front", front_distance)
        print(f"   ✅ Perete FAȚĂ: {front_distance:.2f}m (estimat din L={left_dist:.2f}m, R={right_dist:.2f}m)")
    else:
        nav_state.log_wall_measurement("front", None)
        print(f"   ⚠️  Perete FAȚĂ: măsurare eșuată")

    if stream_pipeline is not None:
        try:
            stream_pipeline.save_measurement_snapshot('front', front_distance, point_name='center')
        except Exception as e:
            print(f"   ⚠️  Nu am putut salva snapshot front: {e}")

    # Rotește 100° la STÂNGA pentru a măsura peretele din stânga
    first_left_rotation_degrees = 100
    yaw_speed = 80
    quarter_turn_degrees = 105
    rotation_time_90 = 1.125  # secunde pentru 90°


    def rotate_in_place(label, degrees, direction):
        yaw_cmd = yaw_speed if direction == "right" else -yaw_speed
        rotation_duration = rotation_time_90 * (degrees / 90.0)
        print(f"\n   🔄 {label}: rotație {degrees}° {'dreapta' if direction == 'right' else 'stânga'}")

        # 1) Stop complet înainte de rotație (fără translatare reziduală)
        drone_stabilize(controller, "light", "pre-rotație")

        # 2) Rotație strict yaw-only în micro-pași (evită cuplajul cu fb/lr)
        elapsed = 0.0
        yaw_step_s = 0.08
        while elapsed < rotation_duration:
            controller.tello.send_rc_control(0, 0, 0, yaw_cmd)
            time.sleep(yaw_step_s)
            mission_path.record_timed_rc(0, 0, yaw_cmd, yaw_step_s, label=label)
            elapsed += yaw_step_s

        # 3) Stop complet după rotație + scurtă stabilizare
        drone_stabilize(controller, "normal", "post-rotație")
        print("   ✅ Rotație completă")

    def wait_for_fresh_edge_distances(after_ts, wall_label, timeout_s=2.5, poll_s=0.05):
        """Așteaptă un sample depth nou (post-rotație) ca să evite măsurări stale."""
        start = time.time()
        while (time.time() - start) < timeout_s:
            sample_ts = nav_state.edge_distances_timestamp
            if nav_state.edge_distances and sample_ts is not None and sample_ts > after_ts:
                return True
            time.sleep(poll_s)

        print(f"   ⚠️  {wall_label}: nu a venit sample nou după rotație, folosesc ultima valoare disponibilă")
        return False

    left_rotation_marker_ts = time.time()
    rotate_in_place("Rotație măsurare STÂNGA", first_left_rotation_degrees, "left")

    # Măsoară peretele din STÂNGA
    print("   📐 Măsurare perete STÂNGA...")
    wait_for_fresh_edge_distances(left_rotation_marker_ts, "Perete STÂNGA")
    drone_stabilize(controller, "light", "pre-măsurare STÂNGA")
    left_wall_distance = None
    if nav_state.edge_distances:
        left_dist_wall, right_dist_wall = nav_state.edge_distances
        left_wall_distance = (left_dist_wall + right_dist_wall) / 2.0
        nav_state.wall_measurements['left'] = left_wall_distance
        nav_state.log_wall_measurement("left", left_wall_distance)
        print(f"   ✅ Perete STÂNGA: {left_wall_distance:.2f}m (L={left_dist_wall:.2f}m, R={right_dist_wall:.2f}m)")
    else:
        nav_state.log_wall_measurement("left", None)
        print(f"   ⚠️  Perete STÂNGA: măsurare eșuată")

    if stream_pipeline is not None:
        try:
            stream_pipeline.save_measurement_snapshot('left', left_wall_distance, point_name='center')
        except Exception as e:
            print(f"   ⚠️  Nu am putut salva snapshot left: {e}")

    # Rotește compensat la DREAPTA pentru a obține ~180° real
    right_rotation_degrees = 200
    right_rotation_marker_ts = time.time()
    rotate_in_place("Rotație măsurare DREAPTA", right_rotation_degrees, "right")

    # Măsoară peretele din DREAPTA
    print("   📐 Măsurare perete DREAPTA...")
    wait_for_fresh_edge_distances(right_rotation_marker_ts, "Perete DREAPTA")
    drone_stabilize(controller, "light", "pre-măsurare DREAPTA")
    right_wall_distance = None
    if nav_state.edge_distances:
        left_dist_wall, right_dist_wall = nav_state.edge_distances
        right_wall_distance = (left_dist_wall + right_dist_wall) / 2.0
        nav_state.wall_measurements['right'] = right_wall_distance
        nav_state.log_wall_measurement("right", right_wall_distance)
        print(f"   ✅ Perete DREAPTA: {right_wall_distance:.2f}m (L={left_dist_wall:.2f}m, R={right_dist_wall:.2f}m)")
    else:
        nav_state.log_wall_measurement("right", None)
        print(f"   ⚠️  Perete DREAPTA: măsurare eșuată")

    if stream_pipeline is not None:
        try:
            stream_pipeline.save_measurement_snapshot('right', right_wall_distance, point_name='center')
        except Exception as e:
            print(f"   ⚠️  Nu am putut salva snapshot right: {e}")

    # Rotește 105° la STÂNGA pentru a reveni cu fața spre peretele opus ușii
    rotate_in_place("Revenire spre peretele opus ușii", quarter_turn_degrees, "left")

    print("\n" + "="*60)
    print("📊 REZUMAT MĂSURĂTORI:")
    if 'front' in nav_state.wall_measurements:
        print(f"   🔹 Perete FAȚĂ:    {nav_state.wall_measurements['front']:.2f} m")
    if 'right' in nav_state.wall_measurements:
        print(f"   🔹 Perete DREAPTA: {nav_state.wall_measurements['right']:.2f} m")
    if 'left' in nav_state.wall_measurements:
        print(f"   🔹 Perete STÂNGA:  {nav_state.wall_measurements['left']:.2f} m")
    print("="*60)
    print("✅ Măsurători complete pentru toate cele 3 pereți!")

    # FAZA 4: DEPLASARE CRAB-STYLE DUPĂ MĂSURĂTORI
    nav_state.autopilot_status = "FAZA 4: Crab-style interior"
    print("\n" + "="*60)
    print("🦀 FAZA 4: Deplasare crab-style (după măsurători)")
    print("="*60)
    print("   1) Orientare spre peretele opus ușii")
    print("   2) Crab-style spre stânga")
    print("   3) Orientare cu camera spre peretele din dreapta")
    print("   4) Crab-style pe lângă peretele din stânga")
    print()

    required_keys = ("left", "right", "front")
    if not all(key in nav_state.wall_measurements for key in required_keys):
        missing = [key for key in required_keys if key not in nav_state.wall_measurements]
        raise RuntimeError(f"Lipsesc măsurători pentru: {', '.join(missing)}")

    left_dist = float(nav_state.wall_measurements["left"])
    right_dist = float(nav_state.wall_measurements["right"])
    front_dist = float(nav_state.wall_measurements["front"])

    crab_speed = 30  # cm/s
    move_check_interval = 0.2
    safety_margin = 0.20
    min_segment = 0.15

    # Păstrăm aceeași logică de 5 segmente ca în traseul inițial
    seg_1 = max(min_segment, (left_dist / 3.0) - safety_margin)
    seg_2 = max(min_segment, (front_dist / 3.0) - safety_margin)
    seg_3 = max(min_segment, ((left_dist / 3.0) + (right_dist / 3.0)) - safety_margin)
    seg_4 = max(min_segment, (front_dist / 3.0) - safety_margin)
    seg_5 = max(min_segment, (right_dist / 3.0))

    print("📐 Segmente crab-style calculate (5 segmente):")
    print(f"   S1: {seg_1:.2f}m")
    print(f"   S2: {seg_2:.2f}m")
    print(f"   S3: {seg_3:.2f}m")
    print(f"   S4: {seg_4:.2f}m")
    print(f"   S5: {seg_5:.2f}m")

    def rotate_right(label, degrees=105):
        rotate_in_place(label, degrees, "right")

    def crab_left_meters(distance_m, label):
        duration = (distance_m * 100.0) / crab_speed
        elapsed = 0.0
        print(f"\n   ↔️  {label}: stânga {distance_m:.2f}m (~{duration:.1f}s)")
        while elapsed < duration:
            controller.tello.send_rc_control(-crab_speed, 0, 0, 0)
            time.sleep(move_check_interval)
            mission_path.record_timed_rc(-crab_speed, 0, 0, move_check_interval, label=label)
            elapsed += move_check_interval
        drone_stabilize(controller, "light", "post-crab")
        print(f"   ✅ {label} finalizat")

    # În acest moment camera este din nou spre peretele opus ușii (după revenirea explicită)
    # Segmentele se fac crab-style, iar între ele rotim astfel încât camera să rămână orientată spre centru.
    print(f"   📏 S1 calculat: {seg_1:.2f}m")
    crab_left_meters(seg_1, "Segment 1 (crab)")

    rotate_right("Orientare S2: spre peretele din dreapta", degrees=quarter_turn_degrees)
    print(f"   📏 S2 calculat: {seg_2:.2f}m")
    crab_left_meters(seg_2, "Segment 2 (crab)")

    rotate_right("Orientare S3: spre peretele cu ușa", degrees=quarter_turn_degrees)
    print(f"   📏 S3 calculat: {seg_3:.2f}m")
    crab_left_meters(seg_3, "Segment 3 (crab)")

    rotate_right("Orientare S4: spre peretele din stânga", degrees=105)
    print(f"   📏 S4 calculat: {seg_4:.2f}m")
    crab_left_meters(seg_4, "Segment 4 (crab)")

    rotate_right("Orientare S5: spre peretele opus ușii", degrees=105)
    print(f"   📏 S5 calculat: {seg_5:.2f}m")
    crab_left_meters(seg_5, "Segment 5 (crab)")

    # Pauză solidă anti-intercalare comenzi
    drone_stabilize(controller, "full", "pre-exit complex scan")

    # FAZA 5: EXIT
    execute_exit_sequence(controller, turn_back_degrees=215)
