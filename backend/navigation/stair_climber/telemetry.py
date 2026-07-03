"""
Telemetrie urcare pe scări — înregistrează timpii, comenzile RC, evoluția scorurilor
per semnal (Sobel/Gabor/DA2) și confidence-ul final, pe parcursul fiecărui zbor.

Salvare INCREMENTALĂ: fiecare zbor e scris în DB imediat ce se termină (end_flight),
deci datele supraviețuiesc unui abort/land. Totul e izolat în try/except — nicio
eroare de telemetrie nu poate afecta zborul real.
"""

import time

try:
    import database.crud as crud
except Exception:  # pragma: no cover
    crud = None

# throttle eșantioane (serie temporală) — ~6-7 Hz
SAMPLE_MIN_INTERVAL_S = 0.15

_s = {
    "active": False,
    "climb_id": None,
    "mission_id": None,
    "flight_index": 0,
    "flight_t0": None,
    "samples": [],
    "last_sample_ts": 0.0,
    "state_durations": {},
    "last_tick_ts": None,
    "last_state": None,
}


def _reset_flight():
    _s["flight_t0"] = time.time()
    _s["samples"] = []
    _s["last_sample_ts"] = 0.0
    _s["state_durations"] = {"SEARCH": 0.0, "CLIMBING": 0.0, "PRE_LAND": 0.0, "SEARCH_NEXT": 0.0}
    _s["last_tick_ts"] = None
    _s["last_state"] = None


def begin_climb(mission_id, target_floor, start_position, signals, total_flights, battery_start=None):
    """Pornește o sesiune de telemetrie pentru o urcare. Sigur dacă DB lipsește."""
    _s["active"] = False
    _s["climb_id"] = None
    _s["mission_id"] = mission_id
    _s["flight_index"] = 0
    if crud is None:
        return
    try:
        _s["climb_id"] = crud.create_stair_climb(
            mission_id=mission_id, target_floor=target_floor,
            start_position=start_position, signals=signals,
            total_flights=total_flights, battery_start=battery_start,
        )
        _s["active"] = True
    except Exception as err:
        print(f"⚠️ stair telemetry begin_climb: {err}")


def begin_flight(flight_index):
    if not _s["active"]:
        return
    _s["flight_index"] = int(flight_index)
    _reset_flight()


def record_sample(state, analysis_r, fwd=0, up=0, lat=0):
    """Înregistrează un tick: actualizează duratele pe stare și (throttled) un eșantion."""
    if not _s["active"] or _s["flight_t0"] is None:
        return
    try:
        now = time.time()
        # acumulează durata pe starea anterioară
        if _s["last_tick_ts"] is not None and _s["last_state"] is not None:
            dt = now - _s["last_tick_ts"]
            _s["state_durations"][_s["last_state"]] = _s["state_durations"].get(_s["last_state"], 0.0) + dt
        _s["last_tick_ts"] = now
        _s["last_state"] = state

        if now - _s["last_sample_ts"] >= SAMPLE_MIN_INTERVAL_S:
            _s["last_sample_ts"] = now
            r = analysis_r or {}
            _s["samples"].append({
                "t": round(now - _s["flight_t0"], 3),
                "state": state,
                "grad_score": round(float(r.get("grad_score", 0.0)), 4),
                "gabor_score": round(float(r.get("gabor_score", 0.0)), 4),
                "depth_stair": round(float(r.get("depth_stair", 0.0)), 4),
                "cov": round(float(r.get("cov", 0.0)), 4),
                "stair_conf": round(float(r.get("stair_conf", 0.0)), 4),
                "flat_conf": round(float(r.get("flat_conf", 0.0)), 4),
                "fwd": float(fwd), "up": float(up), "lat": float(lat),
            })
    except Exception as err:
        print(f"⚠️ stair telemetry record_sample: {err}")


def end_flight(outcome="completed"):
    """Flush incremental în DB al zborului curent + eșantioanele lui."""
    if not _s["active"] or crud is None or _s["climb_id"] is None or _s["flight_t0"] is None:
        return
    try:
        sd = _s["state_durations"]
        flight = {
            "flight_index": _s["flight_index"],
            "search_duration_s": round(sd.get("SEARCH", 0.0) + sd.get("SEARCH_NEXT", 0.0), 3),
            "climbing_duration_s": round(sd.get("CLIMBING", 0.0), 3),
            "preland_duration_s": round(sd.get("PRE_LAND", 0.0), 3),
            "total_duration_s": round(time.time() - _s["flight_t0"], 3),
            "outcome": outcome,
            "samples": list(_s["samples"]),
        }
        crud.save_stair_flight(_s["climb_id"], _s["mission_id"], flight)
    except Exception as err:
        print(f"⚠️ stair telemetry end_flight: {err}")


def end_climb(success, battery_end=None):
    if not _s["active"] or crud is None or _s["climb_id"] is None:
        _s["active"] = False
        return
    try:
        crud.finalize_stair_climb(_s["climb_id"], success=success, battery_end=battery_end)
    except Exception as err:
        print(f"⚠️ stair telemetry end_climb: {err}")
    finally:
        _s["active"] = False
