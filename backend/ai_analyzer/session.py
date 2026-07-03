"""
Ciclul de viață al unei sesiuni de scanare: creare, start, stop + generare raport JSON.
Depinde de: state, tracking (person_qualifies_for_report via state), medical, report
"""

import os
import json
from datetime import datetime

import ai_analyzer.state as state
import ai_analyzer.medical as medical
import ai_analyzer.report as report


def create_empty_session(room_index=None):
    """Returnează un dicționar gol de sesiune (date inițiale pentru o cameră nouă)."""
    return {
        "room_index": room_index,
        "start_time": datetime.now().isoformat() if room_index is not None else None,
        "room_label": None,
        "room_label_candidates": [],
        "pre_entry_ai_analysis": None,
        "persons": {},
        "hazards": {"fire": 0, "smoke": 0},
        "frames_processed": 0,
        "person_frames": [],
    }


def start_scan_session(room_index, scan_mode="medium"):
    """
    Inițializează starea pentru o nouă scanare a camerei room_index.
    Aplică automat label-urile și analizele pre-entry în așteptare.
    """
    print(f"🕵️ AI Analyzer: START Scan pentru CAMERA {room_index} (mode={scan_mode})")

    with state.lock:
        state.current_room = room_index
        state.scan_mode = str(scan_mode or "medium")
        state.session_data = create_empty_session(room_index)

        session_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        state.person_frames_dir = os.path.join(
            state.person_frames_root_dir,
            f"room_{room_index}_{session_ts}",
        )
        os.makedirs(state.person_frames_dir, exist_ok=True)
        state.last_person_frame_save_ts = 0.0

        pending = state.pending_room_labels.get(int(room_index))
        if pending:
            state.session_data["room_label"] = pending.get("label")
            state.session_data["room_label_candidates"] = list(pending.get("results") or [])

        pending_pre_entry = state.pending_pre_entry_analysis.get(int(room_index))
        if pending_pre_entry:
            state.session_data["pre_entry_ai_analysis"] = dict(pending_pre_entry)

        state.person_capture_active = True
        state.is_scanning = True


def stop_scan_session_and_report():
    """
    Oprește scanarea, construiește raportul JSON, îl salvează pe disc și
    declanșează asincron analiza medicală pentru persoanele rămase.
    Returnează calea către fișierul raport sau None dacă nu era activă scanarea.
    """
    with state.lock:
        if not state.is_scanning:
            return None

        print(f"🛑 AI Analyzer: STOP Scan pentru CAMERA {state.current_room}")
        state.is_scanning = False
        state.session_data["end_time"] = datetime.now().isoformat()

        # Aplică label OCR și analiza pre-entry pending (dacă nu au fost aplicate live)
        pending = state.pending_room_labels.get(int(state.current_room))
        if pending:
            state.session_data["room_label"] = pending.get("label")
            state.session_data["room_label_candidates"] = list(pending.get("results") or [])
            print(
                f"🧩 AI Analyzer: aplic pending label la stop_scan camera={state.current_room} "
                f"label='{state.session_data['room_label']}'"
            )
        else:
            print(f"⚠️ AI Analyzer: fără pending label la stop_scan camera={state.current_room}")

        pending_pre_entry = state.pending_pre_entry_analysis.get(int(state.current_room))
        if pending_pre_entry:
            state.session_data["pre_entry_ai_analysis"] = dict(pending_pre_entry)

        # Construiește structura de bază a raportului
        pending_ocr = state.pending_room_labels.get(int(state.current_room)) or {}
        scan_report = {
            "room_index": state.session_data["room_index"],
            "room_label": state.session_data.get("room_label"),
            "room_label_candidates": state.session_data.get("room_label_candidates", []),
            "ocr_frame_paths": dict(pending_ocr.get("ocr_frame_paths") or {}),
            "pre_entry_ai_analysis": state.session_data.get("pre_entry_ai_analysis"),
            "scan_start": state.session_data["start_time"],
            "scan_end": state.session_data["end_time"],
            "frames_analyzed": state.session_data["frames_processed"],
            "person_frames_saved": len(state.session_data.get("person_frames", [])),
            "person_frame_paths": list(state.session_data.get("person_frames", [])),
            "hazards_detected": {
                "fire": state.session_data["hazards"]["fire"] > state.hazard_frames_threshold,
                "smoke": state.session_data["hazards"]["smoke"] > state.hazard_frames_threshold,
            },
            "persons_detected": 0,
            "persons_details": [],
        }

        # --- DIAGNOSTIC: de ce intră / nu intră persoanele în raport ---
        # (Stream-ul live folosește alt model + doar pragul de confidence; raportul
        #  cere în plus min_hits, min_keypoints și un snapshot salvat. Aici vedem exact
        #  ce prag pică pentru fiecare track detectat în timpul scanării.)
        all_persons = state.session_data.get("persons", {})
        print(
            f"🔍 DIAG persoane camera={state.current_room}: {len(all_persons)} track-uri detectate "
            f"| praguri: conf≥{max(0.1, state.person_conf_threshold * 0.8):.2f}, "
            f"hits≥{state.person_report_min_hits}, kpts≥{state.person_report_min_keypoints}, imagine salvată"
        )
        for tid, pd in all_persons.items():
            hits = int(pd.get("hits", 0))
            bk = int(pd.get("best_keypoints", 0))
            cf = float(pd.get("conf", 0.0))
            has_img = bool(pd.get("best_image_path"))
            reasons = []
            if cf < max(0.1, state.person_conf_threshold * 0.8):
                reasons.append(f"conf {cf:.2f} prea mic")
            if hits < state.person_report_min_hits:
                reasons.append(f"hits {hits} < {state.person_report_min_hits}")
            if bk < state.person_report_min_keypoints:
                reasons.append(f"keypoints {bk} < {state.person_report_min_keypoints}")
            if not has_img:
                reasons.append("fără imagine salvată")
            verdict = "✅ ÎN RAPORT" if not reasons else f"⛔ respins ({', '.join(reasons)})"
            print(f"   • track #{tid}: hits={hits} max_kpts={bk} conf={cf:.2f} img={has_img} -> {verdict}")

        # Adaugă persoanele calificate pentru raport
        qualified_track_ids = []
        for track_id, p_data in state.session_data["persons"].items():
            if not state.person_qualifies_for_report(p_data):
                continue
            qualified_track_ids.append(track_id)
            if not p_data.get("medical_dispatched"):
                p_data["in_frame"] = False
            scan_report["persons_details"].append({
                "track_id": track_id,
                "posture": p_data["posture"],
                "confidence": round(p_data["conf"], 2),
                "hits": int(p_data.get("hits", 0)),
                "position": p_data.get("position"),
                "best_keypoints": int(p_data.get("best_keypoints", 0)),
                "image_path": p_data.get("best_image_path"),
                "medical_analysis": p_data.get("medical_analysis"),
            })

        # Elimină înregistrările fără imagine
        scan_report["persons_details"] = [
            person_item
            for person_item in scan_report["persons_details"]
            if isinstance(person_item, dict)
            and isinstance(person_item.get("image_path"), str)
            and person_item.get("image_path")
        ]

        # Deduplicare prin IoU bbox — aceeași persoană detectată cu mai multe track_id-uri
        def _bbox_iou(a, b):
            ax1, ay1, ax2, ay2 = a
            bx1, by1, bx2, by2 = b
            ix1, iy1 = max(ax1, bx1), max(ay1, by1)
            ix2, iy2 = min(ax2, bx2), min(ay2, by2)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            if inter == 0:
                return 0.0
            area_a = (ax2 - ax1) * (ay2 - ay1)
            area_b = (bx2 - bx1) * (by2 - by1)
            return inter / (area_a + area_b - inter)

        scan_report["persons_details"].sort(key=lambda p: p.get("best_keypoints", 0), reverse=True)
        deduped = []
        accepted_bboxes = []
        for person_item in scan_report["persons_details"]:
            bbox = person_item.get("position", {}).get("bbox") if person_item.get("position") else None
            if bbox and len(bbox) == 4:
                if any(_bbox_iou(bbox, kept) > 0.5 for kept in accepted_bboxes):
                    continue
                accepted_bboxes.append(bbox)
            deduped.append(person_item)
        scan_report["persons_details"] = deduped

        scan_report["persons_detected"] = len(scan_report["persons_details"])

        current_room_cache = state.current_room
        state.current_room = None
        state.person_frames_dir = None

    # Declanșează analiza medicală async pentru persoanele încă nedispatched
    for person_item in scan_report.get("persons_details", []):
        if not isinstance(person_item, dict):
            continue
        track_id = person_item.get("track_id")
        with state.lock:
            person_state = state.session_data.get("persons", {}).get(track_id)
            already_dispatched = (
                bool(person_state.get("medical_dispatched"))
                if isinstance(person_state, dict)
                else False
            )
        if not already_dispatched:
            medical.dispatch_person_medical_analysis_async(current_room_cache, track_id)

    # Salvează raportul pe disc
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"scan_report_room_{current_room_cache}_{timestamp}.json"
    filepath = os.path.join(state.reports_dir, filename)

    try:
        with open(filepath, 'w') as f:
            json.dump(scan_report, f, indent=4)
        print(f"📄 Raport AI salvat la: {filepath}")

        # Salvare în baza de date (non-blocking, fără să afecteze fluxul)
        try:
            import mission_tracker
            mission_tracker.save_room_scan_from_report(scan_report, filepath)
        except Exception as _db_err:
            print(f"⚠️ DB: nu pot salva room scan: {_db_err}")

        with state.lock:
            state.latest_report_path_by_room[int(current_room_cache)] = filepath

            pending_after_save = state.pending_room_labels.get(int(current_room_cache))
            pending_label = pending_after_save.get("label") if pending_after_save else None
            pending_results = (
                list(pending_after_save.get("results") or []) if pending_after_save else []
            )
            pending_pre_entry_after_save = state.pending_pre_entry_analysis.get(
                int(current_room_cache)
            )

        if pending_label:
            report.update_saved_report_room_label(filepath, pending_label, pending_results)
        if pending_pre_entry_after_save:
            report.update_saved_report_pre_entry_analysis(filepath, pending_pre_entry_after_save)

    except Exception as save_error:
        print(f"⚠️ Eroare la salvarea raportului AI: {save_error}")

    return filepath
