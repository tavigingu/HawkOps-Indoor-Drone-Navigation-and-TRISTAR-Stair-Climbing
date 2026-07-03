"""
SQLite database engine — init tables și conexiune.
Folosește sqlite3 din stdlib Python (zero dependențe externe).
"""

import os
import sqlite3
import threading

_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'hawkops.db')
_DB_PATH = os.path.abspath(_DB_PATH)

_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """Returnează o conexiune per-thread (thread-safe)."""
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """Creează tabelele dacă nu există. Apelat la pornirea serverului."""
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS missions (
            id          TEXT PRIMARY KEY,
            started_at  TEXT NOT NULL,
            ended_at    TEXT,
            scan_mode   TEXT,
            start_position TEXT,
            room_count  INTEGER,
            target_floor INTEGER,
            status      TEXT DEFAULT 'in_progress'
        );

        CREATE TABLE IF NOT EXISTS room_scans (
            id                  TEXT PRIMARY KEY,
            mission_id          TEXT NOT NULL,
            room_index          INTEGER NOT NULL,
            room_label          TEXT,
            scan_start          TEXT,
            scan_end            TEXT,
            frames_analyzed     INTEGER DEFAULT 0,
            persons_detected    INTEGER DEFAULT 0,
            hazard_fire         INTEGER DEFAULT 0,
            hazard_smoke        INTEGER DEFAULT 0,
            pre_entry_level     TEXT,
            pre_entry_description TEXT,
            pre_entry_image_path  TEXT,
            ocr_crop_path       TEXT,
            ocr_full_frame_path TEXT,
            json_report_path    TEXT,
            FOREIGN KEY (mission_id) REFERENCES missions(id)
        );

        CREATE TABLE IF NOT EXISTS persons (
            id                  TEXT PRIMARY KEY,
            room_scan_id        TEXT NOT NULL,
            track_id            INTEGER,
            posture             TEXT,
            confidence          REAL,
            medical_state       TEXT,
            medical_description TEXT,
            image_path          TEXT,
            region              TEXT,
            best_keypoints      INTEGER DEFAULT 0,
            FOREIGN KEY (room_scan_id) REFERENCES room_scans(id)
        );

        CREATE TABLE IF NOT EXISTS videos (
            id          TEXT PRIMARY KEY,
            mission_id  TEXT NOT NULL,
            video_type  TEXT,
            file_path   TEXT,
            created_at  TEXT,
            FOREIGN KEY (mission_id) REFERENCES missions(id)
        );

        CREATE TABLE IF NOT EXISTS mission_modules (
            id                   TEXT PRIMARY KEY,
            mission_id           TEXT NOT NULL,
            seq                  INTEGER,
            room_index           INTEGER,
            module_key           TEXT,
            module_label         TEXT,
            start_ts             REAL,
            end_ts               REAL,
            duration_s           REAL,
            command_count        INTEGER DEFAULT 0,
            total_command_time_s REAL,
            ema_min              REAL,
            ema_max              REAL,
            ema_final            REAL,
            ema_variation        REAL,
            samples_json         TEXT,
            FOREIGN KEY (mission_id) REFERENCES missions(id)
        );

        CREATE TABLE IF NOT EXISTS mission_commands (
            id          TEXT PRIMARY KEY,
            module_id   TEXT NOT NULL,
            mission_id  TEXT NOT NULL,
            seq         INTEGER,
            t           REAL,
            kind        TEXT,
            label       TEXT,
            lr          REAL,
            fb          REAL,
            yaw         REAL,
            duration_s  REAL,
            degrees     REAL,
            FOREIGN KEY (module_id) REFERENCES mission_modules(id)
        );

        -- ── Telemetrie URCARE PE SCĂRI (tabele noi, aditive) ──────────────
        CREATE TABLE IF NOT EXISTS stair_climbs (
            id              TEXT PRIMARY KEY,
            mission_id      TEXT,
            target_floor    INTEGER,
            start_position  TEXT,
            signals         TEXT,          -- semnalele active ex: "sobel,gabor,da2"
            total_flights   INTEGER,
            flights_done    INTEGER DEFAULT 0,
            started_at      TEXT,
            ended_at        TEXT,
            duration_s      REAL,
            battery_start   INTEGER,
            battery_end     INTEGER,
            success         INTEGER DEFAULT 0,
            FOREIGN KEY (mission_id) REFERENCES missions(id)
        );

        CREATE TABLE IF NOT EXISTS stair_flights (
            id                  TEXT PRIMARY KEY,
            climb_id            TEXT NOT NULL,
            mission_id          TEXT,
            flight_index        INTEGER,
            search_duration_s   REAL,
            climbing_duration_s REAL,
            preland_duration_s  REAL,
            total_duration_s    REAL,
            outcome             TEXT,
            sample_count        INTEGER DEFAULT 0,
            FOREIGN KEY (climb_id) REFERENCES stair_climbs(id)
        );

        CREATE TABLE IF NOT EXISTS stair_samples (
            id           TEXT PRIMARY KEY,
            flight_id    TEXT NOT NULL,
            climb_id     TEXT,
            seq          INTEGER,
            t            REAL,          -- secunde de la începutul zborului
            state        TEXT,          -- SEARCH / CLIMBING / PRE_LAND / SEARCH_NEXT
            grad_score   REAL,          -- Sobel
            gabor_score  REAL,          -- Gabor
            depth_stair  REAL,          -- DA2
            cov          REAL,
            stair_conf   REAL,
            flat_conf    REAL,
            fwd          REAL,
            up           REAL,
            lat          REAL,
            FOREIGN KEY (flight_id) REFERENCES stair_flights(id)
        );

        CREATE INDEX IF NOT EXISTS idx_room_scans_mission ON room_scans(mission_id);
        CREATE INDEX IF NOT EXISTS idx_persons_room_scan  ON persons(room_scan_id);
        CREATE INDEX IF NOT EXISTS idx_videos_mission     ON videos(mission_id);
        CREATE INDEX IF NOT EXISTS idx_modules_mission    ON mission_modules(mission_id);
        CREATE INDEX IF NOT EXISTS idx_commands_module    ON mission_commands(module_id);
        CREATE INDEX IF NOT EXISTS idx_stair_climbs_mission ON stair_climbs(mission_id);
        CREATE INDEX IF NOT EXISTS idx_stair_flights_climb  ON stair_flights(climb_id);
        CREATE INDEX IF NOT EXISTS idx_stair_samples_flight ON stair_samples(flight_id);
    """)

    conn.commit()
    conn.close()
    print(f"✅ Database inițializat: {_DB_PATH}")
