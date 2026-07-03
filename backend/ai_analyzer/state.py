"""
Starea globală partajată între toate modulele ai_analyzer.
Același pattern ca navigation/state.py — date pure, nicio logică de business.
"""

import os
import threading
from queue import Queue

# ---------------------------------------------------------------------------
# Căi (setate de init())
# ---------------------------------------------------------------------------
models_dir = None
reports_dir = None
tracker_config = None
person_frames_root_dir = None

# ---------------------------------------------------------------------------
# Sincronizare thread-uri
# ---------------------------------------------------------------------------
lock = threading.Lock()
thread_active = True

# ---------------------------------------------------------------------------
# Praguri de configurare (citite din env vars de init())
# ---------------------------------------------------------------------------
person_conf_threshold = 0.60
person_report_min_hits = 2
person_report_min_keypoints = 3
hazard_conf_threshold = 0.80
hazard_frames_threshold = 7
person_frame_save_interval_s = 1.0
person_exit_timeout_s = 1.0

# ---------------------------------------------------------------------------
# Starea sesiunii curente
# ---------------------------------------------------------------------------
is_scanning = False
current_room = None
scan_mode = "medium"
person_capture_active = True
session_data = {}
person_frames_dir = None
last_person_frame_save_ts = 0.0
fallback_track_seq = 100000

# ---------------------------------------------------------------------------
# Date pending (sosesc async după ce scanarea a început/terminat)
# ---------------------------------------------------------------------------
pending_room_labels = {}         # {room_idx: {"label": str, "results": list}}
pending_pre_entry_analysis = {}  # {room_idx: dict}
latest_report_path_by_room = {}  # {room_idx: filepath}

# ---------------------------------------------------------------------------
# Cozi worker threads
# ---------------------------------------------------------------------------
pose_queue = Queue(maxsize=5)
hazard_queue = Queue(maxsize=5)
live_queue = Queue(maxsize=1)

# ---------------------------------------------------------------------------
# Stare live overlay (stream continuu)
# ---------------------------------------------------------------------------
live_enabled = True
live_infer_interval_s = 0.12
live_max_overlay_age_s = 0.28
last_live_infer_ts = 0.0
live_pose_model = None
live_hazard_model = None
live_person_detections = []
live_hazard_detections = []
live_overlay_updated_ts = 0.0
live_annotated_frame = None


# ---------------------------------------------------------------------------
# Inițializare
# ---------------------------------------------------------------------------

def init(base_dir):
    """Inițializează căile și pragurile configurabile (citite din env vars)."""
    global models_dir, reports_dir, tracker_config, person_frames_root_dir
    global person_conf_threshold, person_report_min_hits, person_report_min_keypoints
    global hazard_conf_threshold, person_exit_timeout_s

    models_dir = os.path.join(base_dir, 'models')
    reports_dir = os.path.join(base_dir, 'reports')
    tracker_config = os.path.join(base_dir, 'tracking_configs', 'bytetrack_persons.yaml')
    person_frames_root_dir = os.path.join(reports_dir, 'person_frames')

    os.makedirs(reports_dir, exist_ok=True)
    os.makedirs(person_frames_root_dir, exist_ok=True)

    try:
        person_conf_threshold = float(os.environ.get("AI_PERSON_CONF_THRESHOLD", "0.60"))
    except Exception:
        person_conf_threshold = 0.60

    try:
        person_report_min_hits = int(os.environ.get("AI_PERSON_REPORT_MIN_HITS", "2"))
    except Exception:
        person_report_min_hits = 2

    try:
        person_report_min_keypoints = int(os.environ.get("AI_PERSON_REPORT_MIN_KPTS", "3"))
    except Exception:
        person_report_min_keypoints = 3

    try:
        hazard_conf_threshold = float(os.environ.get("AI_HAZARD_CONF_THRESHOLD", "0.80"))
    except Exception:
        hazard_conf_threshold = 0.80

    try:
        person_exit_timeout_s = float(os.environ.get("AI_PERSON_EXIT_TIMEOUT_S", "1.0"))
    except Exception:
        person_exit_timeout_s = 1.0


# ---------------------------------------------------------------------------
# Funcție utilitară partajată (folosită atât de session cât și de report)
# — pusă în state pentru a evita importuri circulare
# ---------------------------------------------------------------------------

def person_qualifies_for_report(person_state):
    """Returnează True dacă o persoană tracked merită inclusă în raport."""
    if not isinstance(person_state, dict):
        return False

    hits = int(person_state.get("hits", 0))
    best_kpts = int(person_state.get("best_keypoints", 0))
    conf = float(person_state.get("conf", 0.0))
    image_path = person_state.get("best_image_path")

    if conf < max(0.1, person_conf_threshold * 0.8):
        return False
    if hits < person_report_min_hits:
        return False
    if best_kpts < person_report_min_keypoints:
        return False
    if not image_path or not isinstance(image_path, str) or not os.path.exists(image_path):
        return False
    return True
