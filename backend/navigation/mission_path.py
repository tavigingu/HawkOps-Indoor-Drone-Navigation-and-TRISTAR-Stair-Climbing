import json
import math
import os
import threading
import time
from datetime import datetime


_lock = threading.Lock()
# Sink opțional apelat cu rezumatul unei faze IMEDIAT ce se termină (end_phase).
# Setat de mission_tracker pentru salvare incrementală în DB. Apelat ÎN AFARA _lock.
_phase_sink = None
_state = {
    "active": False,
    "scan_mode": "medium",
    "room_count": 1,
    "current_room": None,
    "start_ts": None,
    "x_cm": 0.0,
    "y_cm": 0.0,
    "heading_deg": 0.0,
    "points": [],
    "last_saved": None,
    # --- Telemetry (comenzi + metrici per modul/fază) ---
    # Nu afectează calculul traseului; e folosit doar pentru statistici în DB/frontend.
    "phases": [],          # listă ordonată de faze (vezi _new_phase)
    "active_phase": None,  # faza deschisă explicit prin begin_phase
    "cmd_seq": 0,          # contor global de comenzi
    "last_telemetry": None,
}


# ---------------------------------------------------------------------------
# Telemetry — maparea etichetelor pe module logice
# ---------------------------------------------------------------------------

# Etichetele comenzilor (label= din record_*) sunt mapate pe "module" lizibile
# pentru frontend. Folosit doar când nu există o fază deschisă explicit.
_LABEL_MODULE_MAP = (
    ("phase1_centering",        ("centering", "Centrare ușă")),
    ("post_ocr_micro_center",   ("centering", "Centrare ușă")),
    ("post-centrare",           ("centering", "Centrare ușă")),
    ("pre_entry_distance_hold", ("distance_hold", "Menținere distanță")),
    ("pre_entry_align",         ("lateral_align", "Aliniere laterală")),
    ("pre_entry_ocr",           ("ocr_scan", "Citire etichetă (OCR)")),
    ("pre-OCR",                 ("ocr_scan", "Citire etichetă (OCR)")),
    ("phase0_search",           ("door_search", "Căutare ușă")),
    ("phase2_entry",            ("door_entry", "Intrare pe ușă")),
    ("transition",              ("transition", "Tranziție cameră")),
    ("stairwell",               ("stairwell", "Navigare casa scării")),
    ("medium_",                 ("scan", "Scanare")),
    ("fast_",                   ("scan", "Scanare")),
    ("Segment",                 ("scan", "Scanare")),
    ("Rotație",                 ("scan", "Scanare")),
    ("Orientare",               ("scan", "Scanare")),
    ("Revenire",                ("scan", "Scanare")),
)


def _module_for_label(label):
    """Returnează (module_key, module_label) pentru o etichetă de comandă."""
    text = str(label) if label else ""
    for prefix, mapped in _LABEL_MODULE_MAP:
        if text.startswith(prefix) or prefix in text:
            return mapped
    return ("other", "Altele")


def _new_phase(module_key, module_label, room, auto, start_ts):
    _state["phases"].append(
        {
            "seq": len(_state["phases"]),
            "module_key": module_key,
            "module_label": module_label,
            "room": int(room) if room is not None else None,
            "auto": bool(auto),
            "start_ts": float(start_ts),
            "end_ts": float(start_ts),
            "commands": [],
            "samples": [],
        }
    )
    return _state["phases"][-1]


def _attribute_command(cmd):
    """Atașează o comandă la faza activă sau la o fază auto derivată din label.

    Apelat din interiorul lock-ului. Eșecurile sunt prinse de apelant.
    """
    ts = cmd["t"]
    room = cmd.get("room")
    active = _state["active_phase"]

    if active is not None:
        phase = active
    else:
        key, label = _module_for_label(cmd.get("label"))
        last = _state["phases"][-1] if _state["phases"] else None
        if (
            last is not None
            and last.get("auto")
            and last["module_key"] == key
            and last["room"] == room
        ):
            phase = last
        else:
            phase = _new_phase(key, label, room, auto=True, start_ts=ts)

    phase["commands"].append(cmd)
    phase["end_ts"] = ts


def _normalize_heading(heading_deg):
    return ((float(heading_deg) + 180.0) % 360.0) - 180.0


def _append_point(label=None):
    _state["points"].append(
        {
            "t": time.time(),
            "x_cm": round(float(_state["x_cm"]), 3),
            "y_cm": round(float(_state["y_cm"]), 3),
            "heading_deg": round(float(_state["heading_deg"]), 3),
            "room": _state["current_room"],
            "label": str(label) if label else None,
        }
    )


def reset_mission(scan_mode="medium", room_count=1):
    with _lock:
        _state["active"] = True
        _state["scan_mode"] = str(scan_mode or "medium")
        _state["room_count"] = max(1, int(room_count))
        _state["current_room"] = None
        _state["start_ts"] = time.time()
        _state["x_cm"] = 0.0
        _state["y_cm"] = 0.0
        _state["heading_deg"] = 0.0
        _state["points"] = []
        _state["phases"] = []
        _state["active_phase"] = None
        _state["cmd_seq"] = 0
        _state["last_telemetry"] = None
        _append_point(label="mission_start")


def set_current_room(room_index):
    with _lock:
        if not _state["active"]:
            return
        _state["current_room"] = int(room_index) if room_index is not None else None
        _append_point(label=f"room_{_state['current_room']}_start")


def note_event(label):
    with _lock:
        if not _state["active"]:
            return
        _append_point(label=label)


def record_rotation(degrees, clockwise=True, label=None):
    with _lock:
        if not _state["active"]:
            return
        delta = abs(float(degrees))
        if not clockwise:
            delta = -delta
        _state["heading_deg"] = _normalize_heading(_state["heading_deg"] - delta)
        _append_point(label=label)
        _capture_command(
            kind="rotation",
            label=label,
            degrees=abs(float(degrees)),
            clockwise=bool(clockwise),
        )


def record_translation(forward_cm=0.0, lateral_cm=0.0, label=None):
    with _lock:
        if not _state["active"]:
            return

        forward_cm = float(forward_cm)
        lateral_cm = float(lateral_cm)
        heading_rad = math.radians(float(_state["heading_deg"]))

        dx = forward_cm * math.cos(heading_rad) + lateral_cm * math.sin(heading_rad)
        dy = forward_cm * math.sin(heading_rad) - lateral_cm * math.cos(heading_rad)

        _state["x_cm"] += dx
        _state["y_cm"] += dy
        _append_point(label=label)
        _capture_command(
            kind="translation",
            label=label,
            lr=lateral_cm,
            fb=forward_cm,
        )


def record_timed_rc(left_right_cm_s, forward_backward_cm_s, yaw_deg_s, duration_s, label=None):
    duration_s = float(duration_s)
    if duration_s <= 0:
        return

    with _lock:
        if not _state["active"]:
            return

        lr = float(left_right_cm_s)
        fb = float(forward_backward_cm_s)
        yaw = float(yaw_deg_s)

        # Yaw pozitiv în comenzi RC = rotație dreapta (clockwise),
        # iar heading-ul intern e pozitiv CCW.
        _state["heading_deg"] = _normalize_heading(_state["heading_deg"] - yaw * duration_s)

        heading_rad = math.radians(float(_state["heading_deg"]))
        forward_cm = fb * duration_s
        lateral_cm = lr * duration_s

        dx = forward_cm * math.cos(heading_rad) + lateral_cm * math.sin(heading_rad)
        dy = forward_cm * math.sin(heading_rad) - lateral_cm * math.cos(heading_rad)

        _state["x_cm"] += dx
        _state["y_cm"] += dy
        _append_point(label=label)
        _capture_command(
            kind="rc",
            label=label,
            lr=lr,
            fb=fb,
            yaw=yaw,
            duration=duration_s,
        )


# ---------------------------------------------------------------------------
# Telemetry — API public (apelat din navigation/core.py)
# ---------------------------------------------------------------------------

def _capture_command(kind, label=None, lr=0.0, fb=0.0, yaw=0.0,
                     duration=0.0, degrees=0.0, clockwise=True):
    """Înregistrează o comandă în telemetrie. Apelat din interiorul _lock.

    Orice eroare e ignorată ca să nu afecteze niciodată navigația.
    """
    try:
        _state["cmd_seq"] += 1
        cmd = {
            "seq": _state["cmd_seq"],
            "t": time.time(),
            "kind": str(kind),
            "label": str(label) if label else None,
            "room": _state["current_room"],
            "lr": round(float(lr), 3),
            "fb": round(float(fb), 3),
            "yaw": round(float(yaw), 3),
            "duration": round(float(duration), 3),
            "degrees": round(float(degrees), 3),
            "clockwise": bool(clockwise),
        }
        _attribute_command(cmd)
    except Exception:
        pass


def begin_phase(module_key, module_label, room=None):
    """Deschide explicit o fază (modul) — comenzile următoare i se atașează.

    Auto-închide faza explicită anterioară. Sigur de apelat oricând.
    """
    with _lock:
        if not _state["active"]:
            return
        try:
            now = time.time()
            if _state["active_phase"] is not None:
                _state["active_phase"]["end_ts"] = now
            target_room = room if room is not None else _state["current_room"]
            phase = _new_phase(
                str(module_key), str(module_label), target_room,
                auto=False, start_ts=now,
            )
            _state["active_phase"] = phase
        except Exception:
            pass


def end_phase():
    """Închide faza deschisă explicit cu begin_phase. Sigur dacă nu există.

    Dacă există un phase sink înregistrat, trimite rezumatul fazei imediat (salvare
    incrementală în DB). Sink-ul e apelat ÎN AFARA _lock ca să nu ținem lock-ul în
    timpul scrierii în baza de date."""
    module = None
    sink = _phase_sink
    with _lock:
        try:
            phase = _state["active_phase"]
            if phase is not None:
                phase["end_ts"] = time.time()
                if phase["commands"] or phase["samples"]:
                    module = _summarize_one(phase)
            _state["active_phase"] = None
        except Exception:
            _state["active_phase"] = None

    if sink is not None and module is not None:
        try:
            sink(module)
        except Exception:
            pass


def record_metric_sample(key, value, room=None):
    """Înregistrează un eșantion de metrică (ex: EMA distanță) în faza curentă."""
    with _lock:
        if not _state["active"]:
            return
        try:
            if value is None:
                return
            fval = float(value)
            phase = _state["active_phase"]
            if phase is None and _state["phases"]:
                phase = _state["phases"][-1]
            if phase is None:
                return
            phase["samples"].append(
                {"t": time.time(), "key": str(key), "value": round(fval, 4)}
            )
        except Exception:
            pass


def _summarize_one(phase):
    """Construiește rezumatul unui singur modul/fază. Apelat din interiorul _lock."""
    cmds = phase["commands"]
    start = phase.get("start_ts")
    end = phase.get("end_ts") or start
    duration = max(0.0, float(end) - float(start)) if (start and end) else 0.0
    total_cmd_time = sum(float(c.get("duration") or 0.0) for c in cmds)

    ema_vals = [s["value"] for s in phase["samples"] if s["key"] == "ratio_ema"]
    ema_min = min(ema_vals) if ema_vals else None
    ema_max = max(ema_vals) if ema_vals else None
    ema_final = ema_vals[-1] if ema_vals else None
    ema_variation = (ema_max - ema_min) if ema_vals else None

    return {
        "seq": phase["seq"],
        "module_key": phase["module_key"],
        "module_label": phase["module_label"],
        "room": phase["room"],
        "start_ts": start,
        "end_ts": end,
        "duration_s": round(duration, 3),
        "command_count": len(cmds),
        "total_command_time_s": round(total_cmd_time, 3),
        "ema_min": ema_min,
        "ema_max": ema_max,
        "ema_final": ema_final,
        "ema_variation": round(ema_variation, 4) if ema_variation is not None else None,
        "commands": [
            {
                "seq": c["seq"],
                "t": c["t"],
                "kind": c["kind"],
                "label": c["label"],
                "lr": c["lr"],
                "fb": c["fb"],
                "yaw": c["yaw"],
                "duration": c["duration"],
                "degrees": c["degrees"],
                "clockwise": c["clockwise"],
            }
            for c in cmds
        ],
        "samples": list(phase["samples"]),
    }


def _summarize_telemetry():
    """Construiește rezumatul per-modul (apelat din finalize, în interiorul _lock)."""
    modules = [
        _summarize_one(phase)
        for phase in _state["phases"]
        if phase["commands"] or phase["samples"]
    ]
    return {
        "generated_at": datetime.now().isoformat(),
        "modules": modules,
    }


def set_phase_sink(callback):
    """Înregistrează un callback apelat cu rezumatul unei faze imediat ce se termină
    (din end_phase). Folosit de mission_tracker pentru salvare incrementală în DB."""
    global _phase_sink
    _phase_sink = callback


def get_last_telemetry():
    """Returnează ultimul rezumat de telemetrie calculat la finalize."""
    with _lock:
        return _state.get("last_telemetry")


def _save_plot_png(output_png, title):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [point["x_cm"] for point in _state["points"]]
    ys = [point["y_cm"] for point in _state["points"]]

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.plot(xs, ys, color="#0d9488", linewidth=2.0, marker="o", markersize=2.5)

    if xs and ys:
        ax.scatter([xs[0]], [ys[0]], color="#16a34a", s=45, label="Start")
        ax.scatter([xs[-1]], [ys[-1]], color="#dc2626", s=45, label="Final")

    ax.set_title(title)
    ax.set_xlabel("x (cm)")
    ax.set_ylabel("y (cm)")
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.6)
    ax.axis("equal")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_png, dpi=140)
    plt.close(fig)


def finalize_and_save(success=True, error=None):
    with _lock:
        if not _state["active"]:
            return _state.get("last_saved")

        # Închide orice fază rămasă deschisă și calculează telemetria.
        try:
            if _state["active_phase"] is not None:
                _state["active_phase"]["end_ts"] = time.time()
                _state["active_phase"] = None
            _state["last_telemetry"] = _summarize_telemetry()
        except Exception as telem_err:
            print(f"⚠️ mission_path: telemetrie eroare: {telem_err}")
            _state["last_telemetry"] = None

        _append_point(label="mission_end")

        base_dir = os.path.dirname(os.path.dirname(__file__))
        reports_dir = os.path.join(base_dir, "reports", "mission_paths")
        os.makedirs(reports_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"mission_path_{_state['scan_mode']}_{ts}"
        json_path = os.path.join(reports_dir, f"{base_name}.json")
        png_path = os.path.join(reports_dir, f"{base_name}.png")

        payload = {
            "generated_at": datetime.now().isoformat(),
            "scan_mode": _state["scan_mode"],
            "room_count": _state["room_count"],
            "success": bool(success),
            "error": str(error) if error else None,
            "start_ts": _state["start_ts"],
            "end_ts": time.time(),
            "points": list(_state["points"]),
        }

        with open(json_path, "w", encoding="utf-8") as output_file:
            json.dump(payload, output_file, indent=2)

        plot_error = None
        try:
            _save_plot_png(
                png_path,
                title=f"Mission Path ({_state['scan_mode']}, rooms={_state['room_count']})",
            )
        except Exception as err:
            plot_error = str(err)

        result = {
            "json_path": json_path,
            "png_path": png_path if plot_error is None else None,
            "plot_error": plot_error,
        }
        _state["last_saved"] = dict(result)
        _state["active"] = False
        return result
