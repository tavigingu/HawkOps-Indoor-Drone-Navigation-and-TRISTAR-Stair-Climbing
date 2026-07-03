"""
Analiză medicală async a persoanelor detectate (via AI service extern).
Depinde de: state, report (pentru public_asset_url)
"""

import json
import time
import base64
import threading
import urllib.request
import urllib.error
from datetime import datetime

import ai_analyzer.state as state
import ai_analyzer.report as report


def update_saved_report_person_medical(report_path, track_id, medical_payload):
    """Actualizează câmpul medical_analysis al unei persoane într-un raport JSON salvat."""
    try:
        with open(report_path, 'r') as f:
            report_data = json.load(f)

        persons_details = report_data.get("persons_details") or []
        for person_item in persons_details:
            if not isinstance(person_item, dict):
                continue
            try:
                item_track_id = int(person_item.get("track_id"))
            except Exception:
                continue
            if item_track_id == int(track_id):
                person_item["medical_analysis"] = dict(medical_payload or {})
                break

        with open(report_path, 'w') as f:
            json.dump(report_data, f, indent=4)
    except Exception as update_error:
        print(f"⚠️ Eroare actualizare medical analysis ({report_path}): {update_error}")


def _analyze_person_medical_state_for_report(room_idx, track_id, image_path):
    """
    Trimite imaginea persoanei la serviciul AI și returnează analiza medicală.
    Rulează sincron (în thread dedicat).
    """
    import os
    request_id = f"ai-person-{room_idx}-{track_id}-{int(time.time() * 1000)}"
    image_url = report.public_asset_url(image_path)

    if not image_path or not isinstance(image_path, str) or not os.path.exists(image_path):
        return {
            "status": "error",
            "medical_state": "UNKNOWN",
            "indicators": [],
            "description": "Imaginea persoanei nu este disponibilă pentru analiză medicală.",
            "source": "person_medical_ai_service",
            "captured_at": datetime.now().isoformat(),
            "request_id": request_id,
            "response_received": False,
            "http_status": None,
            "error": "missing_image",
            "image_url": image_url,
        }

    try:
        with open(image_path, "rb") as image_file:
            image_bytes = image_file.read()
    except Exception as read_error:
        return {
            "status": "error",
            "medical_state": "UNKNOWN",
            "indicators": [],
            "description": "Nu am putut citi imaginea persoanei pentru analiză medicală.",
            "source": "person_medical_ai_service",
            "captured_at": datetime.now().isoformat(),
            "request_id": request_id,
            "response_received": False,
            "http_status": None,
            "error": str(read_error),
            "image_url": image_url,
        }

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = json.dumps({"image_base64": image_b64}).encode("utf-8")

    import os
    ai_url = os.environ.get(
        "AI_PERSON_ANALYSIS_URL",
        "http://127.0.0.1:8000/api/v1/analysis/person-medical",
    )

    ai_timeout_s = 20.0
    ai_retries = 2
    try:
        ai_timeout_s = float(os.environ.get("AI_PERSON_ANALYSIS_TIMEOUT_S", "20"))
    except Exception:
        pass
    try:
        ai_retries = int(os.environ.get("AI_PERSON_ANALYSIS_RETRIES", "2"))
    except Exception:
        pass
    if ai_retries < 1:
        ai_retries = 1

    response_data = None
    for attempt_idx in range(ai_retries):
        request = urllib.request.Request(
            ai_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-AI-Request-ID": request_id,
                "X-Room-Index": str(room_idx),
                "X-Track-ID": str(track_id),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=ai_timeout_s) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            break
        except Exception as request_error:
            if attempt_idx < ai_retries - 1:
                time.sleep(0.25)
            else:
                error_text = str(request_error)
                status_code = None
                response_received = False
                if isinstance(request_error, urllib.error.HTTPError):
                    status_code = getattr(request_error, "code", None)
                    response_received = True
                    try:
                        error_body = request_error.read().decode("utf-8", errors="ignore").strip()
                        if error_body:
                            error_text = f"{error_text} | body={error_body[:350]}"
                    except Exception:
                        pass
                return {
                    "status": "error",
                    "medical_state": "UNKNOWN",
                    "indicators": [],
                    "description": "Analiza medicală a persoanei a eșuat.",
                    "source": "person_medical_ai_service",
                    "captured_at": datetime.now().isoformat(),
                    "request_id": request_id,
                    "response_received": response_received,
                    "http_status": status_code,
                    "error": error_text,
                    "image_url": image_url,
                }

    if not isinstance(response_data, dict):
        return {
            "status": "error",
            "medical_state": "UNKNOWN",
            "indicators": [],
            "description": "Serviciul medical AI a răspuns cu format invalid.",
            "source": "person_medical_ai_service",
            "captured_at": datetime.now().isoformat(),
            "request_id": request_id,
            "response_received": True,
            "http_status": 200,
            "error": "invalid_response_format",
            "image_url": image_url,
        }

    medical_state = response_data.get("medical_state") or response_data.get("state") or "UNKNOWN"
    indicators = list(response_data.get("indicators") or [])
    description = response_data.get("description") or "Serviciul medical AI nu a returnat descriere."

    return {
        "status": "success",
        "medical_state": medical_state,
        "indicators": indicators,
        "description": description,
        "source": "person_medical_ai_service",
        "captured_at": datetime.now().isoformat(),
        "request_id": request_id,
        "response_received": True,
        "http_status": 200,
        "error": None,
        "image_url": image_url,
    }


def dispatch_person_medical_analysis_async(room_idx, track_id):
    """
    Pornește asincron analiza medicală pentru o persoană care a ieșit din cadru.
    Closure-ul intern (_worker) capturează room_idx, track_id, image_path din contextul curent.
    """
    with state.lock:
        person_state = state.session_data.get("persons", {}).get(track_id)
        if not isinstance(person_state, dict):
            return False
        if person_state.get("medical_dispatched"):
            return False

        image_path = person_state.get("best_image_path")
        person_state["medical_dispatched"] = True
        person_state["in_frame"] = False
        person_state["medical_analysis"] = {
            "status": "pending",
            "medical_state": "UNKNOWN",
            "indicators": [],
            "description": "Analiza medicală este în curs.",
            "source": "person_medical_ai_service",
            "captured_at": datetime.now().isoformat(),
            "request_id": None,
            "response_received": False,
            "http_status": None,
            "error": None,
            "image_url": report.public_asset_url(image_path),
        }

    def _worker():
        result = _analyze_person_medical_state_for_report(
            room_idx=room_idx,
            track_id=track_id,
            image_path=image_path,
        )
        with state.lock:
            person_state_after = state.session_data.get("persons", {}).get(track_id)
            if isinstance(person_state_after, dict):
                person_state_after["medical_analysis"] = dict(result)
            report_path = state.latest_report_path_by_room.get(int(room_idx))

        if report_path:
            update_saved_report_person_medical(report_path, track_id, result)

    worker = threading.Thread(
        target=_worker,
        name=f"medical-person-{room_idx}-{track_id}",
        daemon=True,
    )
    worker.start()
    return True
