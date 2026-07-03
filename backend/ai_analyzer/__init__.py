"""
Pachetul ai_analyzer — punct de intrare public.
Expune clasa MultiThreadedAIAnalyzer și funcția singleton get_analyzer().

Toate metodele publice delegă la modulele specializate:
  state   → stare globală partajată
  session → start/stop sesiune scanare
  workers → dispatch frame-uri, live overlay
  report  → rapoarte, label-uri OCR, analiză pre-entry
"""

import os
import threading

import ai_analyzer.state as state
import ai_analyzer.session as session
import ai_analyzer.workers as workers
import ai_analyzer.report as report


class MultiThreadedAIAnalyzer:
    """
    Orchestrează cele 3 thread-uri background (pose, hazard, live) și expune
    aceeași interfață publică ca versiunea monolitică originală.
    """

    def __init__(self):
        # Directorul `backend/` este părintele directorului acestui pachet
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        state.init(base_dir)
        state.session_data = session.create_empty_session()

        self._pose_thread = threading.Thread(
            target=workers.pose_worker_loop,
            name="ai-pose-worker",
            daemon=True,
        )
        self._hazard_thread = threading.Thread(
            target=workers.hazard_worker_loop,
            name="ai-hazard-worker",
            daemon=True,
        )
        self._live_thread = threading.Thread(
            target=workers.live_worker_loop,
            name="ai-live-worker",
            daemon=True,
        )

        self._pose_thread.start()
        self._hazard_thread.start()
        self._live_thread.start()

        print("🧠 Sistem AI multi-threaded inițializat.")

    # ------------------------------------------------------------------
    # Sesiune scanare
    # ------------------------------------------------------------------

    def start_scan_session(self, room_index, scan_mode="medium"):
        session.start_scan_session(room_index, scan_mode)

    def stop_scan_session_and_report(self):
        return session.stop_scan_session_and_report()

    # ------------------------------------------------------------------
    # Procesare frame-uri
    # ------------------------------------------------------------------

    def process_frame(self, frame):
        workers.process_frame(frame)

    def set_person_capture_active(self, is_active):
        workers.set_person_capture_active(is_active)

    def annotate_live_frame(self, frame):
        return workers.annotate_live_frame(frame)

    def apply_latest_annotations(self, frame):
        return workers.apply_latest_annotations(frame)

    # ------------------------------------------------------------------
    # Label cameră (OCR) și analiză pre-entry
    # ------------------------------------------------------------------

    def set_room_label(self, room_index, room_label, ocr_results=None, ocr_frame_paths=None):
        report.set_room_label(room_index, room_label, ocr_results, ocr_frame_paths=ocr_frame_paths)

    def set_room_ocr_frame_paths(self, room_index, ocr_frame_paths):
        report.set_room_ocr_frame_paths(room_index, ocr_frame_paths)

    def set_room_pre_entry_analysis(self, room_index, analysis_payload):
        report.set_room_pre_entry_analysis(room_index, analysis_payload)

    # ------------------------------------------------------------------
    # Citire rapoarte
    # ------------------------------------------------------------------

    def get_room_report_snapshot(self, room_index):
        return report.get_room_report_snapshot(room_index)

    def get_multi_room_report_snapshots(self, room_count=5):
        return report.get_multi_room_report_snapshots(room_count)

    # ------------------------------------------------------------------
    # Oprire gracefully
    # ------------------------------------------------------------------

    def shutdown(self):
        """Semnalizează thread-urilor să se oprească și așteaptă terminarea lor."""
        state.thread_active = False

        # Deblochează queue.get(timeout=...) cu un sentinel None
        for q in (state.pose_queue, state.hazard_queue, state.live_queue):
            try:
                q.put_nowait(None)
            except Exception:
                pass

        for t in (self._pose_thread, self._hazard_thread, self._live_thread):
            if t and t.is_alive():
                t.join(timeout=1.5)

        print("🛑 Sistem AI oprit.")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_analyzer_instance = None
_analyzer_lock = threading.Lock()


def get_analyzer():
    """Returnează instanța singleton a MultiThreadedAIAnalyzer (lazy init)."""
    global _analyzer_instance
    if _analyzer_instance is None:
        with _analyzer_lock:
            if _analyzer_instance is None:
                _analyzer_instance = MultiThreadedAIAnalyzer()
    return _analyzer_instance
