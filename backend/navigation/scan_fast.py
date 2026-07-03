import time
from navigation.common import execute_exit_sequence
import navigation.state as nav_state
import navigation.mission_path as mission_path


def execute_fast_scan(controller):
    """
    FAST SCAN NOU:
    După FAZA 2 (intrare 1.5m), fără măsurători:
    1. Rotație stânga 90° real
    2. Rotație dreapta 180° real
    3. Rotație dreapta 90° real
    4. Drona e din nou orientată spre ușă
    5. Recentrare pe ușă + ieșire 2.0m
    """
    nav_state.autopilot_status = "FAZA 3: Fast orientare pentru ieșire"
    print("\n" + "="*60)
    print("⚡ FAZA 3: Fast Scan (fără măsurători)")
    print("="*60)
    print("   🔄 Secvență rotații reale: 90° STÂNGA → 180° DREAPTA → 90° DREAPTA")

    yaw_speed = 80
    rotation_time_90 = 1.125

    # Compensări empirice: comandă 105° ≈ 90° real, 205° ≈ 180° real
    left_90_cmd = 105
    right_180_cmd = 205
    right_90_cmd = 105

    def rotate_left_real_90():
        duration = rotation_time_90 * (left_90_cmd / 90.0)
        print("   ↩️  Rotație STÂNGA 90° real")
        controller.tello.send_rc_control(0, 0, 0, -yaw_speed)
        time.sleep(duration)
        mission_path.record_timed_rc(0, 0, -yaw_speed, duration, label="fast_rotate_left")
        controller.tello.send_rc_control(0, 0, 0, 0)
        time.sleep(0.8)

    def rotate_right_real_180():
        duration = rotation_time_90 * (right_180_cmd / 90.0)
        print("   ↪️  Rotație DREAPTA 180° real")
        controller.tello.send_rc_control(0, 0, 0, yaw_speed)
        time.sleep(duration)
        mission_path.record_timed_rc(0, 0, yaw_speed, duration, label="fast_rotate_right_180")
        controller.tello.send_rc_control(0, 0, 0, 0)
        time.sleep(0.8)

    def rotate_right_real_90():
        duration = rotation_time_90 * (right_90_cmd / 90.0)
        print("   ↪️  Rotație DREAPTA 90° real")
        controller.tello.send_rc_control(0, 0, 0, yaw_speed)
        time.sleep(duration)
        mission_path.record_timed_rc(0, 0, yaw_speed, duration, label="fast_rotate_right_90")
        controller.tello.send_rc_control(0, 0, 0, 0)
        time.sleep(0.8)

    rotate_left_real_90()
    rotate_right_real_180()
    rotate_right_real_90()
    print("   ✅ Secvență rotații completă - orientare spre ușă")

    execute_exit_sequence(controller, include_turn_back=False)
