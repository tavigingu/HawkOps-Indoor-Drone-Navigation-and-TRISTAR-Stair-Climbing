"""
Generare, salvare și citire rapoarte JSON + gestionare label OCR și analiză pre-entry.
Depinde de: state
"""

import os
import json
from datetime import datetime

import ai_analyzer.state as state


# ---------------------------------------------------------------------------
# URL-uri publice pentru assets
# ---------------------------------------------------------------------------

def public_asset_url(path_value):
    """Convertește o cale absolută din reports/ în URL public /reports/assets/..."""
    if not path_value or not isinstance(path_value, str):
        return None
    if path_value.startswith('/reports/assets/'):
        return path_value
    try:
        abs_path = os.path.abspath(path_value)
        reports_abs = os.path.abspath(state.reports_dir)
        if not abs_path.startswith(reports_abs):
            return None
        rel_path = os.path.relpath(abs_path, reports_abs).replace(os.sep, '/')
        if rel_path.startswith('..'):
            return None
        return f"/reports/assets/{rel_path}"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Label cameră (OCR)
# ---------------------------------------------------------------------------

def set_room_label(room_index, room_label, ocr_results=None, ocr_frame_paths=None):
    """Setează numele camerei (din OCR) pentru raportul AI."""
    if room_index is None or room_label is None:
        return

    normalized_label = str(room_label).strip()
    if not normalized_label:
        return

    room_idx = int(room_index)
    results = list(ocr_results or [])
    top_conf = None
    if results and isinstance(results[0], dict):
        try:
            top_conf = float(results[0].get("confidence", 0.0))
        except Exception:
            top_conf = None

    print(
        f"🏷️ AI Analyzer: set_room_label camera={room_idx} label='{normalized_label}' "
        f"candidates={len(results)}"
        + (f" top_conf={top_conf:.2f}" if top_conf is not None else "")
    )

    with state.lock:
        state.pending_room_labels[room_idx] = {
            "label": normalized_label,
            "results": results,
            "ocr_frame_paths": dict(ocr_frame_paths) if ocr_frame_paths else {},
        }

        update_live_session = state.is_scanning and state.current_room == room_idx
        if update_live_session:
            state.session_data["room_label"] = normalized_label
            state.session_data["room_label_candidates"] = list(results)

        report_path = state.latest_report_path_by_room.get(room_idx)

    if report_path and not update_live_session:
        print(f"📝 AI Analyzer: aplic label în raport deja salvat pentru camera {room_idx}")
        update_saved_report_room_label(report_path, normalized_label, results)


def set_room_ocr_frame_paths(room_index, ocr_frame_paths):
    """Atașează frame-urile trimise la OCR (crop + full frame cu bbox) la raportul
    camerei, INDEPENDENT de faptul că OCR-ul a găsit sau nu text. Util pentru debug:
    vrem să vedem mereu ce s-a trimis la OCR, chiar dacă nu s-a detectat niciun label."""
    if room_index is None or not ocr_frame_paths:
        return

    room_idx = int(room_index)
    paths = dict(ocr_frame_paths)

    with state.lock:
        existing = state.pending_room_labels.get(room_idx) or {}
        existing_paths = dict(existing.get("ocr_frame_paths") or {})
        existing_paths.update(paths)
        existing["ocr_frame_paths"] = existing_paths
        state.pending_room_labels[room_idx] = existing

        report_path = state.latest_report_path_by_room.get(room_idx)

    print(
        f"🖼️ AI Analyzer: set_room_ocr_frame_paths camera={room_idx} "
        f"({', '.join(paths.keys())})"
    )

    if report_path:
        update_saved_report_ocr_frame_paths(report_path, paths)


def update_saved_report_ocr_frame_paths(report_path, ocr_frame_paths):
    """Actualizează câmpul ocr_frame_paths într-un raport JSON deja salvat pe disc."""
    try:
        with open(report_path, 'r') as f:
            report_data = json.load(f)

        merged = dict(report_data.get("ocr_frame_paths") or {})
        merged.update(ocr_frame_paths or {})
        report_data["ocr_frame_paths"] = merged

        with open(report_path, 'w') as f:
            json.dump(report_data, f, indent=4)

        print(f"📝 Raport actualizat cu frame-uri OCR: {report_path}")
    except Exception as update_error:
        print(f"⚠️ Eroare actualizare frame-uri OCR în raport ({report_path}): {update_error}")


def update_saved_report_room_label(report_path, room_label, ocr_results):
    """Actualizează câmpul room_label într-un raport JSON deja salvat pe disc."""
    try:
        with open(report_path, 'r') as f:
            report_data = json.load(f)

        report_data["room_label"] = room_label
        report_data["room_label_candidates"] = list(ocr_results or [])

        with open(report_path, 'w') as f:
            json.dump(report_data, f, indent=4)

        print(
            f"📝 Raport actualizat cu OCR întârziat: {report_path} "
            f"label='{room_label}' candidates={len(ocr_results or [])}"
        )
    except Exception as update_error:
        print(f"⚠️ Eroare actualizare raport OCR întârziat ({report_path}): {update_error}")


# ---------------------------------------------------------------------------
# Analiză pre-entry (AI serviciu extern)
# ---------------------------------------------------------------------------

def set_room_pre_entry_analysis(room_index, analysis_payload):
    """Setează analiza AI de pre-intrare pentru raportul camerei."""
    if room_index is None or not isinstance(analysis_payload, dict):
        return

    room_idx = int(room_index)
    analysis = {
        "level": analysis_payload.get("level"),
        "hazards_identified": list(analysis_payload.get("hazards_identified") or []),
        "description": analysis_payload.get("description"),
        "image_url": analysis_payload.get("image_url"),
        "source": analysis_payload.get("source", "pre_entry_ai_service"),
        "captured_at": analysis_payload.get("captured_at") or datetime.now().isoformat(),
        "status": analysis_payload.get("status", "success"),
        "request_id": analysis_payload.get("request_id"),
        "response_received": bool(analysis_payload.get("response_received", False)),
        "http_status": analysis_payload.get("http_status"),
        "error": analysis_payload.get("error"),
    }

    print(
        f"🧠 AI Analyzer: set_room_pre_entry_analysis camera={room_idx} "
        f"level='{analysis.get('level')}' hazards={len(analysis.get('hazards_identified') or [])}"
    )

    with state.lock:
        state.pending_pre_entry_analysis[room_idx] = dict(analysis)

        update_live_session = state.is_scanning and state.current_room == room_idx
        if update_live_session:
            state.session_data["pre_entry_ai_analysis"] = dict(analysis)

        report_path = state.latest_report_path_by_room.get(room_idx)

    if report_path and not update_live_session:
        update_saved_report_pre_entry_analysis(report_path, analysis)


def update_saved_report_pre_entry_analysis(report_path, analysis_payload):
    """Actualizează câmpul pre_entry_ai_analysis într-un raport JSON deja salvat."""
    try:
        with open(report_path, 'r') as f:
            report_data = json.load(f)

        report_data["pre_entry_ai_analysis"] = dict(analysis_payload or {})

        with open(report_path, 'w') as f:
            json.dump(report_data, f, indent=4)

        print(
            f"📝 Raport actualizat cu analiza pre-entry: {report_path} "
            f"level='{report_data.get('pre_entry_ai_analysis', {}).get('level')}'"
        )
    except Exception as update_error:
        print(f"⚠️ Eroare actualizare raport pre-entry ({report_path}): {update_error}")


# ---------------------------------------------------------------------------
# Citire raport salvat + snapshot live
# ---------------------------------------------------------------------------

def read_saved_report(report_path):
    """Citește un raport JSON de pe disc (sau None dacă nu există/e invalid)."""
    if not report_path:
        return None
    try:
        with open(report_path, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def _build_person_image_map(person_frame_paths):
    """Construiește un dict {track_id: public_url} din lista de căi salvate."""
    image_by_track = {}
    if not isinstance(person_frame_paths, list):
        return image_by_track

    for raw_path in reversed(person_frame_paths):
        if not isinstance(raw_path, str):
            continue
        url = public_asset_url(raw_path)
        if not url:
            continue

        file_name = os.path.basename(raw_path)
        marker = 'tracks_'
        marker_idx = file_name.find(marker)
        if marker_idx < 0:
            continue

        track_part = file_name[marker_idx + len(marker):]
        track_part = track_part.split('_', 1)[0]
        for token in track_part.split('-'):
            token = token.strip()
            if not token.isdigit():
                continue
            image_by_track.setdefault(int(token), url)

    return image_by_track


def get_room_report_snapshot(room_index):
    """Returnează un snapshot live + raport salvat pentru o cameră."""
    room_idx = int(room_index)

    with state.lock:
        is_scanning_room = state.is_scanning and state.current_room == room_idx
        current_room = state.current_room

        pending = state.pending_room_labels.get(room_idx) or {}
        pending_label = pending.get("label")
        pending_candidates = list(pending.get("results") or [])
        pending_ocr_frame_paths = dict(pending.get("ocr_frame_paths") or {})

        pending_pre_entry_analysis = state.pending_pre_entry_analysis.get(room_idx)

        report_path = state.latest_report_path_by_room.get(room_idx)

        live_data = None
        if is_scanning_room:
            live_persons_details = []
            for track_id, p_data in state.session_data.get("persons", {}).items():
                if not isinstance(p_data, dict):
                    continue
                if not state.person_qualifies_for_report(p_data):
                    continue
                live_persons_details.append({
                    "track_id": track_id,
                    "posture": p_data.get("posture"),
                    "confidence": round(float(p_data.get("conf", 0.0)), 2),
                    "hits": int(p_data.get("hits", 0)),
                    "position": p_data.get("position"),
                    "best_keypoints": int(p_data.get("best_keypoints", 0)),
                    "image_path": p_data.get("best_image_path"),
                    "image_url": public_asset_url(p_data.get("best_image_path")),
                    "medical_analysis": p_data.get("medical_analysis"),
                })

            live_data = {
                "frames_analyzed": int(state.session_data.get("frames_processed", 0)),
                "persons_detected": int(len(live_persons_details)),
                "hazards_counts": {
                    "fire": int(state.session_data.get("hazards", {}).get("fire", 0)),
                    "smoke": int(state.session_data.get("hazards", {}).get("smoke", 0)),
                },
                "scan_start": state.session_data.get("start_time"),
                "room_label": state.session_data.get("room_label"),
                "room_label_candidates": list(state.session_data.get("room_label_candidates", [])),
                "pre_entry_ai_analysis": state.session_data.get("pre_entry_ai_analysis"),
                "persons_details": live_persons_details,
            }

    saved_report = read_saved_report(report_path)
    if isinstance(saved_report, dict):
        pre_entry_data = saved_report.get("pre_entry_ai_analysis")
        if isinstance(pre_entry_data, dict):
            pre_entry_image = public_asset_url(pre_entry_data.get("image_url"))
            if pre_entry_image:
                pre_entry_data["image_url"] = pre_entry_image

        person_frame_paths = saved_report.get("person_frame_paths") or []
        public_person_paths = []
        for frame_path in person_frame_paths:
            url = public_asset_url(frame_path)
            if url:
                public_person_paths.append(url)
        saved_report["person_frame_paths"] = public_person_paths

        image_by_track = _build_person_image_map(person_frame_paths)
        persons_details = saved_report.get("persons_details") or []
        if isinstance(persons_details, list):
            for person_item in persons_details:
                if not isinstance(person_item, dict):
                    continue
                explicit_image_url = public_asset_url(person_item.get("image_path"))
                if explicit_image_url:
                    person_item["image_url"] = explicit_image_url

                track_id = person_item.get("track_id")
                try:
                    track_int = int(track_id)
                except Exception:
                    track_int = None

                if "image_url" not in person_item and track_int is not None and track_int in image_by_track:
                    person_item["image_url"] = image_by_track[track_int]

    room_label = None
    room_label_candidates = []

    if live_data and live_data.get("room_label"):
        room_label = live_data.get("room_label")
        room_label_candidates = list(live_data.get("room_label_candidates") or [])
    elif pending_label:
        room_label = pending_label
        room_label_candidates = list(pending_candidates)
    elif saved_report and saved_report.get("room_label"):
        room_label = saved_report.get("room_label")
        room_label_candidates = list(saved_report.get("room_label_candidates") or [])

    pre_entry_response = (
        (live_data.get("pre_entry_ai_analysis") if live_data else None)
        or pending_pre_entry_analysis
        or (saved_report.get("pre_entry_ai_analysis") if isinstance(saved_report, dict) else None)
    )
    if isinstance(pre_entry_response, dict):
        pre_entry_image = public_asset_url(pre_entry_response.get("image_url"))
        if pre_entry_image:
            pre_entry_response["image_url"] = pre_entry_image

    # URL-uri publice pentru frame-urile OCR (frame complet cu bbox + crop trimis la OCR)
    ocr_frames = {}
    raw_ocr_paths = (
        pending_ocr_frame_paths
        or (saved_report.get("ocr_frame_paths") if isinstance(saved_report, dict) else None)
        or {}
    )
    full_frame_url = public_asset_url(raw_ocr_paths.get("full_frame_path"))
    crop_url = public_asset_url(raw_ocr_paths.get("crop_path"))
    if full_frame_url:
        ocr_frames["full_frame_url"] = full_frame_url
    if crop_url:
        ocr_frames["crop_url"] = crop_url

    return {
        "room_index": room_idx,
        "is_scanning": bool(is_scanning_room),
        "current_scanning_room": current_room,
        "room_label": room_label,
        "room_label_candidates": room_label_candidates,
        "ocr_frames": ocr_frames,
        "has_saved_report": saved_report is not None,
        "report_path": report_path,
        "pre_entry_ai_analysis": pre_entry_response,
        "live": live_data,
        "saved_report": saved_report,
        "updated_at": datetime.now().isoformat(),
    }


def get_multi_room_report_snapshots(room_count=5):
    """Returnează snapshot-uri pentru camerele 1..room_count."""
    count = max(1, int(room_count))
    return [get_room_report_snapshot(room_idx) for room_idx in range(1, count + 1)]
