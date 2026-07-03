"""
Mission Tracker — gestionează misiunea curentă și face bridging
între evenimentele din aplicație și baza de date.

NU modifică fluxul de navigație sau detecție.
Este apelat din:
  - server.py  : start/complete misiune + scan video la final
  - session.py : save room scan după ce JSON-ul e deja scris pe disc
"""

import os
import threading
from datetime import datetime
from typing import Optional

import database.crud as crud

try:
    import navigation.mission_path as mission_path
except Exception:  # pragma: no cover - navigation poate lipsi în unele contexte
    mission_path = None

# RLock (reentrant) ca să permitem apeluri imbricate din același thread
# (ex: complete_mission ține lock-ul și cheamă _save_telemetry → record_completed_module).
_lock = threading.RLock()
_current_mission_id: Optional[str] = None
_current_mission_started_at: Optional[str] = None
_last_autopilot_was_active: bool = False
# Reținut separat de _current_mission_id (care e șters la complete_mission) ca să
# putem salva telemetria din thread-ul de autopilot chiar și după ce misiunea a fost
# marcată completă din status-poll.
_last_known_mission_id: Optional[str] = None
# Seq-urile modulelor (fazelor) deja salvate pentru misiunea curentă — idempotență:
# o fază salvată incremental la end_phase nu se mai salvează încă o dată la final.
_persisted_module_seqs = set()


# ---------------------------------------------------------------------------
# Mission lifecycle
# ---------------------------------------------------------------------------

def start_mission(scan_mode: str, start_position: str,
                  room_count: int, target_floor: Optional[int] = None) -> str:
    global _current_mission_id, _current_mission_started_at, _last_known_mission_id
    with _lock:
        try:
            mission_id = crud.create_mission(
                scan_mode=scan_mode,
                start_position=start_position,
                room_count=room_count,
                target_floor=target_floor,
            )
            _current_mission_id = mission_id
            _last_known_mission_id = mission_id
            _current_mission_started_at = datetime.now().isoformat()
            _persisted_module_seqs.clear()
            return mission_id
        except Exception as err:
            print(f"⚠️ MissionTracker: start_mission eroare: {err}")
            return ""


def get_current_mission_id() -> Optional[str]:
    with _lock:
        return _current_mission_id


def complete_mission(mission_id: Optional[str] = None):
    global _current_mission_id
    with _lock:
        target_id = mission_id or _current_mission_id
        if not target_id:
            return
        try:
            _collect_videos(target_id)
            _save_telemetry(target_id)
            crud.complete_mission(target_id)
            if target_id == _current_mission_id:
                _current_mission_id = None
                _current_mission_started_at = None
        except Exception as err:
            print(f"⚠️ MissionTracker: complete_mission eroare: {err}")


def abort_mission(mission_id: Optional[str] = None):
    global _current_mission_id
    with _lock:
        target_id = mission_id or _current_mission_id
        if not target_id:
            return
        try:
            _save_telemetry(target_id)
            crud.abort_mission(target_id)
            if target_id == _current_mission_id:
                _current_mission_id = None
                _current_mission_started_at = None
        except Exception as err:
            print(f"⚠️ MissionTracker: abort_mission eroare: {err}")


def check_and_complete_mission(autopilot_active: bool):
    """
    Apelat periodic din _build_live_payload() în server.py.
    Dacă autopilotul tocmai s-a oprit (tranziție True→False), completăm misiunea.
    """
    global _last_autopilot_was_active
    with _lock:
        was_active = _last_autopilot_was_active
        _last_autopilot_was_active = autopilot_active

    if was_active and not autopilot_active:
        with _lock:
            mid = _current_mission_id
        if mid:
            print(f"🏁 MissionTracker: autopilot finalizat → completare misiune {mid}")
            complete_mission(mid)


# ---------------------------------------------------------------------------
# Room scan hook (apelat din ai_analyzer/session.py)
# ---------------------------------------------------------------------------

def save_room_scan_from_report(report: dict, json_path: str):
    """Salvează room scan-ul în DB dacă există o misiune activă."""
    with _lock:
        mission_id = _current_mission_id

    if not mission_id:
        print("⚠️ MissionTracker: save_room_scan fără misiune activă, skip")
        return

    try:
        crud.save_room_scan(mission_id=mission_id, report=report, json_path=json_path)
    except Exception as err:
        print(f"⚠️ MissionTracker: save_room_scan eroare: {err}")


# ---------------------------------------------------------------------------
# Telemetry (comenzi + metrici per modul/fază)
#
# Salvare INCREMENTALĂ: fiecare fază (centrare, menținere distanță/EMA, scanare,
# tranziție...) e scrisă în DB IMEDIAT ce se termină — prin sink-ul înregistrat în
# mission_path.end_phase(). Astfel, chiar dacă misiunea e întreruptă (land manual /
# aterizare forțată / crash), tot ce s-a terminat deja există în baza de date.
# La finalul misiunii, persist_telemetry() face un catch-all pentru fazele auto
# (care nu se închid explicit), idempotent prin seq-ul fazei.
# ---------------------------------------------------------------------------

def record_completed_module(module):
    """Salvează în DB un singur modul (fază) terminat. Idempotent prin seq.

    Apelat ca sink din mission_path.end_phase() imediat ce o fază se închide."""
    if mission_path is None or not isinstance(module, dict):
        return
    seq = module.get("seq")
    with _lock:
        mid = _current_mission_id or _last_known_mission_id
        if not mid:
            return
        if seq is not None and seq in _persisted_module_seqs:
            return
    try:
        ok = crud.save_module(mid, module)
        if ok and seq is not None:
            with _lock:
                _persisted_module_seqs.add(seq)
    except Exception as err:
        print(f"⚠️ MissionTracker: record_completed_module eroare: {err}")


def _save_telemetry(mission_id: str):
    """Catch-all la finalul misiunii: salvează modulele rămase (în special fazele
    auto, care nu se închid explicit cu end_phase) care nu au fost deja persistate
    incremental. Idempotent prin seq-ul fiecărui modul."""
    if mission_path is None or not mission_id:
        return
    try:
        telemetry = mission_path.get_last_telemetry()
        if not telemetry:
            return
        for module in telemetry.get("modules") or []:
            record_completed_module(module)
    except Exception as err:
        print(f"⚠️ MissionTracker: _save_telemetry eroare: {err}")


def persist_telemetry():
    """Catch-all telemetrie pentru misiunea curentă/ultima cunoscută.

    Apelat din thread-ul de autopilot IMEDIAT după finalize_and_save (când
    last_telemetry e garantat calculată). Funcționează și dacă misiunea a fost deja
    marcată completă din status-poll (folosește _last_known_mission_id)."""
    with _lock:
        mid = _current_mission_id or _last_known_mission_id
    if mid:
        _save_telemetry(mid)


# Înregistrează sink-ul ca mission_path să poată salva fiecare fază imediat ce
# se termină (salvare incrementală). Sigur dacă mission_path lipsește.
if mission_path is not None and hasattr(mission_path, "set_phase_sink"):
    try:
        mission_path.set_phase_sink(record_completed_module)
    except Exception as _sink_err:
        print(f"⚠️ MissionTracker: nu am putut înregistra phase sink: {_sink_err}")


# ---------------------------------------------------------------------------
# Video collection (apelat la finalul misiunii)
# ---------------------------------------------------------------------------

def _collect_videos(mission_id: str):
    """Scanează directoarele de înregistrare și salvează videoclipurile în DB."""
    base_dir = os.path.join(os.path.dirname(__file__))

    recording_dirs = {
        "hallway_raw":            os.path.join(base_dir, "hallway_recordings"),
        "stairwell_raw":          os.path.join(base_dir, "stairwell_recordings"),
        "stair_climber_raw":      os.path.join(base_dir, "stair_climber_recordings"),
    }

    # Aflăm misiunea pentru a ști timestampul de start
    try:
        mission = crud.get_mission(mission_id)
        started_at_str = mission.get("started_at") if mission else None
        started_ts = _parse_ts(started_at_str) if started_at_str else 0.0
    except Exception:
        started_ts = 0.0

    # Fișierele deja înregistrate pentru această misiune
    try:
        existing = {v["file_path"] for v in crud.get_videos_for_mission(mission_id)}
    except Exception:
        existing = set()

    for video_type, directory in recording_dirs.items():
        if not os.path.isdir(directory):
            continue
        try:
            for filename in os.listdir(directory):
                if not filename.endswith(".mp4"):
                    continue
                filepath = os.path.abspath(os.path.join(directory, filename))
                if filepath in existing:
                    continue
                # Verifică dacă fișierul e mai nou decât startul misiunii
                try:
                    file_mtime = os.path.getmtime(filepath)
                    if file_mtime < started_ts - 5:   # 5s toleranță
                        continue
                except Exception:
                    pass

                # Determină tipul mai specific din nume
                specific_type = video_type
                if "da2_contours" in filename or "annotated" in filename:
                    specific_type = video_type.replace("_raw", "_da2")
                elif "grid" in filename:
                    specific_type = video_type.replace("_raw", "_grid")
                elif "raw_ai" in filename:
                    specific_type = video_type

                # Transcodează în H.264 redabil în browser (OpenCV scrie mp4v, pe care
                # browserele nu-l pot reda). In-place — calea rămâne aceeași.
                try:
                    import video_utils
                    filepath = video_utils.ensure_browser_h264(filepath)
                except Exception as _tc_err:
                    print(f"⚠️ MissionTracker: transcodare video eșuată: {_tc_err}")

                crud.save_video(mission_id=mission_id, video_type=specific_type, file_path=filepath)
                print(f"🎬 DB: video înregistrat {specific_type}: {filename}")
        except Exception as err:
            print(f"⚠️ MissionTracker: colectare video {directory} eroare: {err}")


def _parse_ts(iso_str: str) -> float:
    """Convertește ISO datetime string în Unix timestamp."""
    try:
        from datetime import timezone
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            import time as _time
            # Naive datetime → local time
            return _time.mktime(dt.timetuple())
        return dt.timestamp()
    except Exception:
        return 0.0
