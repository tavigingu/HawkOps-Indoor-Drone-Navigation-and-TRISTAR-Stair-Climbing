"""
CRUD operations pentru baza de date HawkOps.
Toate funcțiile sunt thread-safe și folosesc conexiuni per-thread.
"""

import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

from database.db import get_connection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Missions
# ---------------------------------------------------------------------------

def create_mission(scan_mode: str, start_position: str, room_count: int,
                   target_floor: Optional[int] = None) -> str:
    """Creează o misiune nouă și returnează ID-ul."""
    mission_id = _new_id()
    conn = get_connection()
    conn.execute(
        """INSERT INTO missions (id, started_at, scan_mode, start_position, room_count, target_floor, status)
           VALUES (?, ?, ?, ?, ?, ?, 'in_progress')""",
        (mission_id, datetime.now().isoformat(), scan_mode, start_position, room_count, target_floor),
    )
    conn.commit()
    print(f"📋 DB: misiune creată id={mission_id}")
    return mission_id


def complete_mission(mission_id: str):
    """Marchează misiunea ca finalizată."""
    conn = get_connection()
    conn.execute(
        "UPDATE missions SET status='completed', ended_at=? WHERE id=?",
        (datetime.now().isoformat(), mission_id),
    )
    conn.commit()
    print(f"✅ DB: misiune completată id={mission_id}")


def abort_mission(mission_id: str):
    """Marchează misiunea ca abortată."""
    conn = get_connection()
    conn.execute(
        "UPDATE missions SET status='aborted', ended_at=? WHERE id=?",
        (datetime.now().isoformat(), mission_id),
    )
    conn.commit()


def get_mission(mission_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
    return _row_to_dict(row)


def list_missions(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM missions ORDER BY started_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return _rows_to_list(rows)


def count_missions() -> int:
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) as cnt FROM missions").fetchone()
    return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# Room Scans
# ---------------------------------------------------------------------------

def save_room_scan(mission_id: str, report: Dict[str, Any], json_path: str) -> str:
    """Salvează un room scan complet din raportul JSON."""
    scan_id = _new_id()
    pre = report.get("pre_entry_ai_analysis") or {}
    ocr_paths = report.get("ocr_frame_paths") or {}
    hazards = report.get("hazards_detected") or {}

    conn = get_connection()
    conn.execute(
        """INSERT INTO room_scans
           (id, mission_id, room_index, room_label, scan_start, scan_end,
            frames_analyzed, persons_detected, hazard_fire, hazard_smoke,
            pre_entry_level, pre_entry_description, pre_entry_image_path,
            ocr_crop_path, ocr_full_frame_path, json_report_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            scan_id,
            mission_id,
            report.get("room_index"),
            report.get("room_label"),
            report.get("scan_start"),
            report.get("scan_end"),
            report.get("frames_analyzed", 0),
            report.get("persons_detected", 0),
            1 if hazards.get("fire") else 0,
            1 if hazards.get("smoke") else 0,
            pre.get("level"),
            pre.get("description"),
            pre.get("image_url"),
            ocr_paths.get("crop_path"),
            ocr_paths.get("full_frame_path"),
            json_path,
        ),
    )

    # Salvează persoanele
    for person in report.get("persons_details") or []:
        _save_person(conn, scan_id, person)

    conn.commit()
    print(f"📋 DB: room scan salvat id={scan_id} (camera {report.get('room_index')})")
    return scan_id


def _save_person(conn: sqlite3.Connection, room_scan_id: str, person: Dict[str, Any]):
    person_id = _new_id()
    medical = person.get("medical_analysis") or {}
    position = person.get("position") or {}
    conn.execute(
        """INSERT INTO persons
           (id, room_scan_id, track_id, posture, confidence,
            medical_state, medical_description, image_path, region, best_keypoints)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            person_id,
            room_scan_id,
            person.get("track_id"),
            person.get("posture"),
            person.get("confidence"),
            medical.get("medical_state"),
            medical.get("description"),
            person.get("image_path"),
            position.get("region"),
            person.get("best_keypoints", 0),
        ),
    )


def get_room_scans_for_mission(mission_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM room_scans WHERE mission_id=? ORDER BY scan_start ASC",
        (mission_id,),
    ).fetchall()
    return _rows_to_list(rows)


def get_persons_for_scan(room_scan_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM persons WHERE room_scan_id=? ORDER BY best_keypoints DESC",
        (room_scan_id,),
    ).fetchall()
    return _rows_to_list(rows)


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------

def save_video(mission_id: str, video_type: str, file_path: str) -> str:
    video_id = _new_id()
    conn = get_connection()
    conn.execute(
        "INSERT INTO videos (id, mission_id, video_type, file_path, created_at) VALUES (?, ?, ?, ?, ?)",
        (video_id, mission_id, video_type, file_path, datetime.now().isoformat()),
    )
    conn.commit()
    return video_id


def get_videos_for_mission(mission_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM videos WHERE mission_id=? ORDER BY created_at ASC",
        (mission_id,),
    ).fetchall()
    return _rows_to_list(rows)


# ---------------------------------------------------------------------------
# Mission Telemetry (module/faze + comenzi dronă)
# ---------------------------------------------------------------------------

def save_mission_telemetry(mission_id: str, telemetry: Dict[str, Any]) -> int:
    """Salvează modulele (faze) și comenzile dronei pentru o misiune.

    `telemetry` are forma returnată de mission_path._summarize_telemetry().
    Returnează numărul de module salvate.
    """
    if not telemetry:
        return 0

    modules = telemetry.get("modules") or []
    if not modules:
        return 0

    conn = get_connection()
    saved = 0
    for module in modules:
        _insert_module(conn, mission_id, module)
        saved += 1

    conn.commit()
    print(f"📊 DB: telemetrie salvată ({saved} module) pentru misiunea {mission_id}")
    return saved


def _insert_module(conn, mission_id: str, module: Dict[str, Any]) -> str:
    """Inserează un singur modul + comenzile sale. NU face commit (apelantul decide)."""
    module_id = _new_id()
    conn.execute(
        """INSERT INTO mission_modules
           (id, mission_id, seq, room_index, module_key, module_label,
            start_ts, end_ts, duration_s, command_count, total_command_time_s,
            ema_min, ema_max, ema_final, ema_variation, samples_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            module_id,
            mission_id,
            module.get("seq"),
            module.get("room"),
            module.get("module_key"),
            module.get("module_label"),
            module.get("start_ts"),
            module.get("end_ts"),
            module.get("duration_s"),
            module.get("command_count", 0),
            module.get("total_command_time_s"),
            module.get("ema_min"),
            module.get("ema_max"),
            module.get("ema_final"),
            module.get("ema_variation"),
            json.dumps(module.get("samples") or []),
        ),
    )

    for cmd in module.get("commands") or []:
        conn.execute(
            """INSERT INTO mission_commands
               (id, module_id, mission_id, seq, t, kind, label,
                lr, fb, yaw, duration_s, degrees)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _new_id(),
                module_id,
                mission_id,
                cmd.get("seq"),
                cmd.get("t"),
                cmd.get("kind"),
                cmd.get("label"),
                cmd.get("lr"),
                cmd.get("fb"),
                cmd.get("yaw"),
                cmd.get("duration"),
                cmd.get("degrees"),
            ),
        )
    return module_id


def save_module(mission_id: str, module: Dict[str, Any]) -> int:
    """Salvează un singur modul (fază) + comenzile sale, IMEDIAT ce s-a terminat.
    Returnează 1 dacă a salvat, 0 altfel. Folosit pentru salvare incrementală."""
    if not mission_id or not module:
        return 0
    conn = get_connection()
    _insert_module(conn, mission_id, module)
    conn.commit()
    label = module.get("module_label") or module.get("module_key") or "?"
    print(
        f"📊 DB: modul salvat incremental '{label}' "
        f"(room={module.get('room')}, cmds={module.get('command_count', 0)}) "
        f"misiune {mission_id}"
    )
    return 1


def get_modules_for_mission(mission_id: str) -> List[Dict[str, Any]]:
    """Returnează modulele unei misiuni cu comenzile aferente și samples parsate."""
    conn = get_connection()
    module_rows = conn.execute(
        "SELECT * FROM mission_modules WHERE mission_id=? ORDER BY seq ASC",
        (mission_id,),
    ).fetchall()
    modules = _rows_to_list(module_rows)

    for module in modules:
        cmd_rows = conn.execute(
            "SELECT * FROM mission_commands WHERE module_id=? ORDER BY seq ASC",
            (module["id"],),
        ).fetchall()
        module["commands"] = _rows_to_list(cmd_rows)
        try:
            module["samples"] = json.loads(module.get("samples_json") or "[]")
        except Exception:
            module["samples"] = []
        module.pop("samples_json", None)

    return modules


# ---------------------------------------------------------------------------
# Telemetrie urcare pe scări (stair_climbs / stair_flights / stair_samples)
# ---------------------------------------------------------------------------

def create_stair_climb(mission_id, target_floor, start_position, signals,
                       total_flights, battery_start=None) -> str:
    """Creează o sesiune de urcare și returnează climb_id."""
    conn = get_connection()
    climb_id = _new_id()
    conn.execute(
        """INSERT INTO stair_climbs
           (id, mission_id, target_floor, start_position, signals, total_flights,
            flights_done, started_at, battery_start, success)
           VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, 0)""",
        (
            climb_id, mission_id, target_floor, start_position, signals,
            total_flights, datetime.now().isoformat(), battery_start,
        ),
    )
    conn.commit()
    print(f"🪜 DB: stair_climb creat id={climb_id} (semnale={signals}, zboruri={total_flights})")
    return climb_id


def save_stair_flight(climb_id, mission_id, flight) -> str:
    """Salvează un zbor de scară + eșantioanele sale (incremental, la finalul zborului)."""
    conn = get_connection()
    flight_id = _new_id()
    conn.execute(
        """INSERT INTO stair_flights
           (id, climb_id, mission_id, flight_index, search_duration_s,
            climbing_duration_s, preland_duration_s, total_duration_s, outcome, sample_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            flight_id, climb_id, mission_id, flight.get("flight_index"),
            flight.get("search_duration_s"), flight.get("climbing_duration_s"),
            flight.get("preland_duration_s"), flight.get("total_duration_s"),
            flight.get("outcome"), len(flight.get("samples") or []),
        ),
    )
    for i, s in enumerate(flight.get("samples") or []):
        conn.execute(
            """INSERT INTO stair_samples
               (id, flight_id, climb_id, seq, t, state, grad_score, gabor_score,
                depth_stair, cov, stair_conf, flat_conf, fwd, up, lat)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _new_id(), flight_id, climb_id, i, s.get("t"), s.get("state"),
                s.get("grad_score"), s.get("gabor_score"), s.get("depth_stair"),
                s.get("cov"), s.get("stair_conf"), s.get("flat_conf"),
                s.get("fwd"), s.get("up"), s.get("lat"),
            ),
        )
    # incrementăm flights_done pe sesiune
    conn.execute(
        "UPDATE stair_climbs SET flights_done = flights_done + 1 WHERE id=?",
        (climb_id,),
    )
    conn.commit()
    print(
        f"🪜 DB: stair_flight #{flight.get('flight_index')} salvat "
        f"({len(flight.get('samples') or [])} samples, outcome={flight.get('outcome')})"
    )
    return flight_id


def finalize_stair_climb(climb_id, success, battery_end=None):
    """Marchează sesiunea de urcare ca încheiată (durată + succes + baterie)."""
    conn = get_connection()
    row = conn.execute("SELECT started_at FROM stair_climbs WHERE id=?", (climb_id,)).fetchone()
    duration = None
    if row and row["started_at"]:
        try:
            duration = (datetime.now() - datetime.fromisoformat(row["started_at"])).total_seconds()
        except Exception:
            duration = None
    conn.execute(
        """UPDATE stair_climbs
           SET ended_at=?, duration_s=?, battery_end=?, success=? WHERE id=?""",
        (datetime.now().isoformat(), duration, battery_end, 1 if success else 0, climb_id),
    )
    conn.commit()
    print(f"🪜 DB: stair_climb finalizat id={climb_id} (success={success})")


def get_stair_flight_with_samples(flight_id: str) -> Optional[Dict[str, Any]]:
    """Returnează un zbor de scară (meta + semnalele active ale urcării + eșantioane)."""
    conn = get_connection()
    flight = _row_to_dict(conn.execute(
        "SELECT * FROM stair_flights WHERE id=?", (flight_id,)
    ).fetchone())
    if flight is None:
        return None
    # semnalele active vin de la sesiunea de urcare (stair_climbs.signals)
    climb_row = conn.execute(
        "SELECT signals FROM stair_climbs WHERE id=?", (flight.get("climb_id"),)
    ).fetchone()
    flight["signals"] = (climb_row["signals"] if climb_row else None) or ""
    flight["samples"] = _rows_to_list(conn.execute(
        "SELECT t, state, grad_score, gabor_score, depth_stair, cov, "
        "stair_conf, flat_conf, fwd, up, lat FROM stair_samples "
        "WHERE flight_id=? ORDER BY seq ASC",
        (flight_id,),
    ).fetchall())
    return flight


def get_stair_climbs_for_mission(mission_id: str) -> List[Dict[str, Any]]:
    """Returnează urcările unei misiuni cu zborurile și eșantioanele aferente."""
    conn = get_connection()
    climbs = _rows_to_list(conn.execute(
        "SELECT * FROM stair_climbs WHERE mission_id=? ORDER BY started_at ASC",
        (mission_id,),
    ).fetchall())
    for climb in climbs:
        flights = _rows_to_list(conn.execute(
            "SELECT * FROM stair_flights WHERE climb_id=? ORDER BY flight_index ASC",
            (climb["id"],),
        ).fetchall())
        for fl in flights:
            fl["samples"] = _rows_to_list(conn.execute(
                "SELECT t, state, grad_score, gabor_score, depth_stair, cov, "
                "stair_conf, flat_conf, fwd, up, lat FROM stair_samples "
                "WHERE flight_id=? ORDER BY seq ASC",
                (fl["id"],),
            ).fetchall())
        climb["flights"] = flights
    return climbs
