import time
import cv2
import numpy as np
from .config import *
from .vision import *
from .vision import _analyze_frame, _draw_overlay, _compute_debug_visuals
from navigation.common import drone_stabilize
import navigation.state as nav_state
from . import telemetry as _tel

def _compute_fwd_speed(depth: np.ndarray) -> int:
    """
    Ajusteaza viteza inainte in functie de distanta fata de trepte.
    Daca drona e prea aproape (depth centru < MIN_DIST_M) → reduce forward.
    Intre MIN_DIST_M si TARGET_DIST_M → interpolare liniara.
    Deasupra TARGET_DIST_M → viteza normala FORWARD_SPEED.
    """
    if depth is None:
        return FORWARD_SPEED

    h, w = depth.shape
    # Zona centrala a imaginii = distanta estimata fata de trepte
    cy_s, cy_e = int(h * 0.35), int(h * 0.65)
    cx_s, cx_e = int(w * 0.25), int(w * 0.75)
    d_center = float(np.median(depth[cy_s:cy_e, cx_s:cx_e]))

    if d_center <= 0.1:
        return FORWARD_SPEED  # depth invalid, mergi normal

    if d_center < MIN_DIST_M:
        # Prea aproape — opreste forward, drona va urca singura pe verticala
        # (up_speed se calculeaza separat si NU devine 0 cand fwd=0)
        return 0

    if d_center < TARGET_DIST_M:
        # Intre min si tinta — interpolare liniara
        ratio = (d_center - MIN_DIST_M) / (TARGET_DIST_M - MIN_DIST_M)
        return int(np.clip(round(FORWARD_SPEED * ratio), 5, FORWARD_SPEED))

    return FORWARD_SPEED


# ═══════════════════════════════════════════════════════════════════════════════
#  OVERLAY FEREASTRA LIVE
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_up_speed(depth: np.ndarray, fwd_actual: int = None,
                       fallback_ratio: float = SLOPE_RATIO) -> int:
    """
    Calculeaza viteza sus din panta reala a scarii via DA2.

    Logica:
      - Compara depth zona sus vs zona jos a imaginii
      - Scara mai abrupt → d_top >> d_bot → panta mare → up mai mare
      - Scara lina → d_top ≈ d_bot → panta mica → up proportional mai mic
      - Daca depth invalid → fallback la SLOPE_RATIO (tan 32° ≈ 0.62)

    Nu are legatura cu distanta fata de trepte — asta e job-ul _compute_fwd_speed.
    up-ul se calculeaza proportional cu fwd_actual (deja redus de distanta).
    Deci daca esti aproape si fwd=5 → up=5*panta (mic dar proportional).
    Daca esti departe si fwd=20 → up=20*panta (normal).
    """
    fwd = fwd_actual if fwd_actual is not None else FORWARD_SPEED

    if depth is None:
        return int(np.clip(round(fwd * fallback_ratio), 8, 35))

    h, w = depth.shape
    cx_s, cx_e = int(w * 0.2), int(w * 0.8)

    d_bot = np.median(depth[int(h * 0.65) : int(h * 0.90), cx_s:cx_e])
    d_top = np.median(depth[int(h * 0.10) : int(h * 0.35), cx_s:cx_e])

    if d_bot <= 0.1 or d_top <= 0.1:
        return int(np.clip(round(fwd * fallback_ratio), 8, 35))

    depth_diff = float(d_top - d_bot)
    d_avg      = float((d_bot + d_top) / 2.0)

    # FOV vertical Tello ~66°
    fov_v_rad  = np.radians(66.0)
    fy         = (h / 2.0) / np.tan(fov_v_rad / 2.0)
    y_span_m   = (h * 0.275 / fy) * d_avg

    if y_span_m < 0.02 or depth_diff <= 0:
        return int(np.clip(round(fwd * fallback_ratio), 8, 35))

    slope_rad   = np.arctan2(abs(depth_diff), y_span_m)
    slope_ratio = float(np.clip(np.tan(slope_rad), 0.30, 0.90))  # limitat la [17°, 42°]
    # up adaptiv: la distanta mare up normal, la distanta mica up redus proportional
    d_center = float(np.median(depth[int(h*0.35):int(h*0.65), cx_s:cx_e]))
    dist_factor = float(np.clip((d_center - MIN_DIST_M) / (TARGET_DIST_M - MIN_DIST_M), 0.4, 1.0))
    up = int(np.clip(round(fwd * slope_ratio * dist_factor), 5, 30))
    return up


import threading
import os
import datetime
from navigation.state import set_current_room

_vw_raw = None
_vw_grid = None

def init_recordings():
    global _vw_raw, _vw_grid
    os.makedirs('stair_climber_recordings', exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _vw_raw = cv2.VideoWriter(f"stair_climber_recordings/raw_{stamp}.mp4", cv2.VideoWriter_fourcc(*'mp4v'), 10.0, (960, 720))
    _vw_grid = cv2.VideoWriter(f"stair_climber_recordings/grid_{stamp}.mp4", cv2.VideoWriter_fourcc(*'mp4v'), 10.0, (640, 480))

def stop_recordings():
    global _vw_raw, _vw_grid
    if _vw_raw:
        _vw_raw.release()
        _vw_raw = None
    if _vw_grid:
        _vw_grid.release()
        _vw_grid = None

def process_live_debug(tello, analyze_result, current_state="SEARCH", flat_count=0, elapsed=0.0, up_v=0):
    import navigation.state as ns
    global _vw_raw, _vw_grid

    if hasattr(tello, 'get_frame_read'):
        frame = tello.get_frame_read().frame
        depth = getattr(tello, 'depth_frame', None)
        if frame is not None and depth is not None:
            # 1. Scrie raw stream local
            if _vw_raw is not None:
                if frame.shape[:2] != (720, 960):
                    fr_w = cv2.resize(frame, (960, 720))
                    _vw_raw.write(fr_w)
                else:
                    _vw_raw.write(frame)

            # 2. Comput visuals for frontend & grid
            sobel_f, gabor_f, da2_f = _compute_debug_visuals(frame, depth, analyze_result)
            ns.stair_frame_sobel = sobel_f
            ns.stair_frame_gabor = gabor_f
            ns.stair_frame_da2 = da2_f
            
            # 3. Creeaza Streamul imapartit in 4 si scrie in fisier local
            if _vw_grid is not None:
                disp_bgr = _draw_overlay(
                    frame.copy(), analyze_result, state=current_state,
                    flat_count=flat_count, elapsed=elapsed,
                    up_v=up_v, battery=tello.get_battery()
                )
                df0 = cv2.resize(disp_bgr, (320, 240))
                df1 = cv2.resize(sobel_f,  (320, 240))
                df2 = cv2.resize(gabor_f,  (320, 240))
                df3 = cv2.resize(da2_f,    (320, 240))
                
                top_row = np.hstack((df0, df1))
                bot_row = np.hstack((df2, df3))
                grid_img = np.vstack((top_row, bot_row))
                
                _vw_grid.write(grid_img)
            
            # Curatam metrics pentru trimitere frontend pastrand DOAR cele 4 baruri din sursa originala
            metrics = {
                "SCARI": float(analyze_result.get("stair_conf", 0)),
                "PALIER": float(analyze_result.get("flat_conf", 0)),
                "GRAD": float(analyze_result.get("grad_score", 0)),
                "GABOR": float(analyze_result.get("gabor_score", 0)),
            }
            ns.stair_metrics = metrics
            

def execute_stair_climber(tello, target_floor=1, start_position="stairs", signals=None, single_flight=False):
    print(f'[STAIR_CLIMBER] Initiind urcarea pentru target {target_floor} etaje.'
          + (' [SINGLE-FLIGHT]' if single_flight else ''))

    # Selecție semnale (din frontend/API) — aplicată runtime, fără restart.
    if signals is not None:
        try:
            from . import config as cfg
            sel = signals if isinstance(signals, (list, tuple)) else str(signals).split(",")
            sel = {s.strip().lower() for s in sel if str(s).strip()}
            cfg.set_active_signals(
                sobel="sobel" in sel,
                gabor="gabor" in sel,
                da2="da2" in sel,
            )
        except Exception as sig_err:
            print(f"⚠️ [STAIR_CLIMBER] nu pot seta semnalele ({sig_err})")

    # Pornește telemetria de urcare (timpi, comenzi, scoruri per semnal, conf).
    try:
        from . import config as cfg
        from . import telemetry as stair_tel
        import mission_tracker
        mid = mission_tracker.get_current_mission_id()
        try:
            bat = int(tello.get_battery())
        except Exception:
            bat = None
        stair_tel.begin_climb(
            mission_id=mid, target_floor=target_floor, start_position=start_position,
            signals=cfg.active_signals_str(),
            total_flights=(1 if single_flight else int(target_floor) * 2),
            battery_start=bat,
        )
    except Exception as tel_err:
        print(f"⚠️ [STAIR_CLIMBER] telemetrie indisponibilă ({tel_err})")
        stair_tel = None

    init_recordings()
    success = False
    try:
        success = _execute_stair_climber_impl(tello, target_floor, start_position, single_flight=single_flight)
        return success
    finally:
        stop_recordings()
        if stair_tel is not None:
            try:
                bat_end = None
                try:
                    bat_end = int(tello.get_battery())
                except Exception:
                    pass
                stair_tel.end_climb(success=success, battery_end=bat_end)
            except Exception:
                pass

def _execute_stair_climber_impl(tello, target_floor=1, start_position="stairs", single_flight=False):
    # Numaram de cate zboruri de scara avem nevoie (2 pe etaj).
    # Mod single_flight (test rapid): urcam DOAR un zbor, pana la palier, si aterizam.
    total_flights = 1 if single_flight else int(target_floor) * 2
    current_flight = 0
    search_aborted = False
    
    for current_flight in range(total_flights):
        print(f'\n[STAIR_CLIMBER] --- Urcam zborul {current_flight + 1} / {total_flights} ---')
        _tel.begin_flight(current_flight)

        state = 'SEARCH'
        flat_count = 0
        climb_t0 = None

        while state != 'DONE' and not search_aborted:
            # Check aborts from navigation state
            if not nav_state.autopilot_active:
                print('[STAIR_CLIMBER] Abort mission solicitat de user.')
                tello.send_rc_control(0,0,0,0)
                nav_state.debug_frame = None
                _tel.end_flight('aborted')
                return False
                
            if not hasattr(tello, 'get_frame_read'):
                time.sleep(0.05)
                continue
                
            frame = tello.get_frame_read().frame
            if frame is None:
                time.sleep(0.05)
                continue
                
            depth = getattr(tello, 'depth_frame', None) 
            
            # Analyze frame
            analysis_r = _analyze_frame(frame, depth)
            
            # Estimate variables for Video Overlay
            _elapsed = (time.time() - climb_t0) if state == 'CLIMBING' and climb_t0 else 0.0
            _f = 0
            _up_v = 0
            if state == 'CLIMBING':
                _f = _compute_fwd_speed(depth)
                _up_v = _compute_up_speed(depth, fwd_actual=(FORWARD_SPEED if _f == 0 else _f))

            # Share output debug to frontend & Video Writer
            nav_state.debug_frame = process_live_debug(
                tello, analysis_r,
                current_state=state,
                flat_count=flat_count,
                elapsed=_elapsed,
                up_v=_up_v
            )

            stair_conf = analysis_r.get('stair_conf', 0)
            flat_conf = analysis_r.get('flat_conf', 0)

            # Telemetrie: scoruri per semnal + conf + comenzi (throttled intern)
            _tel.record_sample(state, analysis_r, fwd=_f, up=_up_v, lat=0)
            
            if state == 'SEARCH':
                tello.send_rc_control(0, 0, 0, 0)
                if stair_conf >= STAIR_CONF_THRESHOLD:
                    print(f'✅ SCĂRI DETECTATE (conf={stair_conf:.2f}) → URCARE zbor {current_flight+1}')
                    state = 'CLIMBING'
                    climb_t0 = time.time()
                    flat_count = 0
                time.sleep(0.15)
                
            elif state == 'CLIMBING':
                elapsed = time.time() - climb_t0
                if tello.get_battery() <= LAND_BATTERY:
                    state = 'PRE_LAND'
                    continue
                if elapsed > CLIMB_TIMEOUT_S:
                    state = 'PRE_LAND'
                    continue
                    
                fwd_v = _compute_fwd_speed(depth)
                up_base = FORWARD_SPEED if fwd_v == 0 else fwd_v
                up_v = _compute_up_speed(depth, fwd_actual=up_base)
                
                lat_err = analysis_r.get('lat_err', 0.0)
                lat_conf = analysis_r.get('lat_conf', 0.0)
                lat_v = 0
                if abs(lat_err) > LATERAL_DEAD_ZONE and lat_conf > 0.15:
                    lat_scaled = lat_err * (0.7 + 0.9 * lat_conf) * LATERAL_GAIN
                    lat_v = int(np.clip(round(LATERAL_SPEED * lat_scaled), -LATERAL_MAX, LATERAL_MAX))
                
                # Ignorăm corecțiile laterale temporar pentru a merge strict drept
                lat_v = 0
                
                tello.send_rc_control(lat_v, fwd_v, up_v, 0)
                
                palier_ok = (stair_conf < STAIR_CONF_CEIL and flat_conf > FLAT_CONF_THRESHOLD)
                
                if palier_ok:
                    flat_count += 1
                else:
                    flat_count = max(0, flat_count - 1)
                    
                if flat_count >= FLAT_FRAMES_NEEDED:
                    print(f'🏁 CAPĂT SCĂRI CONFIRMAT zbor {current_flight+1}')
                    state = 'PRE_LAND'
                    
            elif state == 'PRE_LAND':
                print('   Oprire miscare...')
                for _ in range(5):
                    tello.send_rc_control(0, 0, 0, 0)
                    time.sleep(0.05)
                drone_stabilize(tello, level='full', label='post-flat')

                # Mod single_flight: NU mai facem dash-ul înainte pe palier — oprim aici
                # ca metricile să fie strict despre urcare. Aterizarea se face în ramura else.
                if not single_flight:
                    forward_time = (PRELAND_DASH_DISTANCE_M * 100.0) / PRELAND_DASH_SPEED
                    print(f'   Inaintare {PRELAND_DASH_DISTANCE_M:.1f}m pe palier...')
                    elapsed_dash = 0.0
                    while elapsed_dash < forward_time:
                        tello.send_rc_control(0, PRELAND_DASH_SPEED, 0, 0)
                        step = min(PRELAND_DASH_DT, forward_time - elapsed_dash)
                        time.sleep(step)
                        elapsed_dash += step
                    tello.send_rc_control(0, 0, 0, 0)
                    drone_stabilize(tello, level='full', label='post-inaintare')
                else:
                    print('   Single-flight: fără dash înainte — oprire directă pe palier.')

                state = 'DONE' # End of this flight's immediate climb sequence
                
        # End of while loop for flight — salvăm telemetria zborului (incremental)
        _tel.end_flight('completed')

        if search_aborted or not nav_state.autopilot_active:
            nav_state.debug_frame = None
            return False
            
        # Daca mai avem un zbor de facut ca sa egalam target_floor
        if current_flight < total_flights - 1:
            print('[STAIR_CLIMBER] Initiere rotatie 180 grade si crab style pentru urmatoarea sectiune...')
            
            full_rotation_time = PRELAND_ROT_TIME_90_S * (PRELAND_TURN_DEG / 90.0)
            tello.send_rc_control(0, 0, 0, 0)
            time.sleep(0.2)
            elapsed_yaw = 0.0
            while elapsed_yaw < full_rotation_time:
                tello.send_rc_control(0, 0, 0, PRELAND_YAW_SPEED)
                step = min(0.08, full_rotation_time - elapsed_yaw)
                time.sleep(step)
                elapsed_yaw += step
            tello.send_rc_control(0, 0, 0, 0)
            drone_stabilize(tello, level='full', label='post-rotatie')
            
            print('   Crab style spre stanga (cautare noi scari)...')
            t_search_start = time.time()
            
            def move_linear(dist_m, direction='left'):
                cmd_left = -CRAB_SEARCH_SPEED if direction == 'left' else 0
                cmd_fwd = CRAB_SEARCH_SPEED if direction == 'forward' else 0
                move_time = (dist_m * 100.0) / CRAB_SEARCH_SPEED
                elapsed_move = 0.0
                while elapsed_move < move_time:
                    tello.send_rc_control(cmd_left, cmd_fwd, 0, 0)
                    step = min(0.1, move_time - elapsed_move)
                    time.sleep(step)
                    elapsed_move += step
                for _ in range(5):
                    tello.send_rc_control(0, 0, 0, 0)
                    time.sleep(0.05)
                drone_stabilize(tello, level='normal', label=f'post-{direction}')
                # nav_state.debug_frame = None  -- Removed because we want to see
                return True

            move_linear(CRAB_INITIAL_DIST_M, 'left')
            for i in range(20): # Hover eval 2s
                tello.send_rc_control(0,0,0,0)
                time.sleep(0.1)
                
            _next_conf_count = 0
            consecutive_bad_frames = 0
            
            while _next_conf_count < 5 and nav_state.autopilot_active:
                 # Check aborts from navigation state
                if not nav_state.autopilot_active:
                    print('[STAIR_CLIMBER] Abort mission solicitat de user.')
                    tello.send_rc_control(0,0,0,0)
                    nav_state.debug_frame = None
                    return False
                    
                frame = tello.get_frame_read().frame
                if frame is None:
                    continue
                depth = getattr(tello, 'depth_frame', None)
                analysis_r2 = _analyze_frame(frame, depth)
                nav_state.debug_frame = process_live_debug(tello, analysis_r2, current_state="SEARCH_NEXT")
                
                # Use param
                if analysis_r2.get('stair_conf', 0) >= STAIR_CONF_THRESHOLD:
                    _next_conf_count += 1
                    consecutive_bad_frames = 0
                    time.sleep(0.1)
                else:
                    _next_conf_count = max(0, _next_conf_count - 1)
                    consecutive_bad_frames += 1
                    if consecutive_bad_frames >= 5:
                        print(f"   ⚠️ Detectie slaba. Mut inca {CRAB_STEP_DIST_M}m stanga...")
                        move_linear(CRAB_STEP_DIST_M, 'left')
                        consecutive_bad_frames = 0
                        
                if (time.time() - t_search_start) > CLIMB_TIMEOUT_S:
                    print("⏱️ Timeout FIND NEXT.")
                    nav_state.debug_frame = None
                    return False
                    
            # Dupa ce a gasit scari:
            tello.send_rc_control(0, 0, 0, 0)
            drone_stabilize(tello, level='full', label='post-SEARCH_NEXT')
            
            # Check depth dist (lift 20cm if too close)
            # Daca e prea aproape, urcam 20 cm in plus
            if depth is not None:
                h, w = depth.shape
                d_c = depth[int(h*0.3):int(h*0.7), int(w*0.3):int(w*0.7)]
                d_val = float(np.median(d_c[(d_c > 0) & (d_c < 10)])) if len(d_c[(d_c > 0) & (d_c < 10)]) > 0 else 2.0
                if 0.1 < d_val < MIN_DIST_M + 0.1:
                    print('   Distanța mică. Ridic drona ~20cm...')
                    eu = 0.0
                    while eu < 0.8:
                        tello.send_rc_control(0,0,30,0)
                        time.sleep(0.1)
                        eu += 0.1
                    tello.send_rc_control(0,0,0,0)
                    drone_stabilize(tello, level='normal', label='post-20cm-lift')
                    
        else:
            if single_flight:
                # Mod test rapid: am urcat un singur zbor pana la palier → aterizam aici.
                print('[STAIR_CLIMBER] Single-flight: palier atins → ATERIZARE pe loc.')
                for _ in range(3):
                    tello.send_rc_control(0, 0, 0, 0)
                    time.sleep(0.1)
                try:
                    tello.land()
                    print('✅ [STAIR_CLIMBER] Aterizat (single-flight).')
                except Exception as _land_err:
                    print(f'⚠️ [STAIR_CLIMBER] aterizare single-flight eșuată: {_land_err}')
                nav_state.debug_frame = None
                return True

            # Urcare finala pt corelare cu hol
            print('[STAIR_CLIMBER] Toate etajele cerute au fost atinse. Finalizat secventa.')

            print('[STAIR_CLIMBER] Urc suplimentar ~90cm pt sectiunea staircase / hallway (indiferent de start_position)...')

            # urca inca ~90cm (approx 2s at speed 45)
            elapsed_up_final = 0.0
            while elapsed_up_final < 2.0:
                tello.send_rc_control(0, 0, 45, 0)
                time.sleep(0.1)
                elapsed_up_final += 0.1
            tello.send_rc_control(0, 0, 0, 0)
            drone_stabilize(tello, level='full', label='post-90cm-lift-final')

            nav_state.debug_frame = None
            return True
            
    nav_state.debug_frame = None
    return True



