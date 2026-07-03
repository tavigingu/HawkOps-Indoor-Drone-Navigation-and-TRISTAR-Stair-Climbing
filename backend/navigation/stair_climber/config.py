import os
import numpy as np

# ── Viteze RC (unitati Tello: -100 … +100) ────────────────────────────────
FORWARD_SPEED   = 30
SLOPE_RATIO     = 0.62

TARGET_DIST_M   = 1.2
MIN_DIST_M      = 0.7

# ── Corectie laterala ─────────────────────────────────────────────────────
LATERAL_SPEED     = 18
LATERAL_MAX       = 25
LATERAL_DEAD_ZONE = 0.06
LATERAL_GAIN      = 1.25

# ── Detectie scari ────────────────────────────────────────────────────────
STAIR_CONF_THRESHOLD = 0.52
FLAT_CONF_THRESHOLD  = 0.40
STAIR_CONF_CEIL      = 0.60
FLAT_FRAMES_NEEDED   = 5

def _env_bool(name, default=True):
    v = os.environ.get(name, '').lower()
    if v in ('1', 'true', 'yes', 'on'):  return True
    if v in ('0', 'false', 'no', 'off'): return False
    return default

USE_SOBEL                = _env_bool('USE_SOBEL',   True)
USE_GABOR                = _env_bool('USE_GABOR',   True)
USE_DA2_COV              = _env_bool('USE_DA2_COV', True)
REQUIRE_ALL_FLAT_SENSORS = _env_bool('REQUIRE_ALL_FLAT_SENSORS', True)

# Selecție RUNTIME a semnalelor (suprascrie env-ul, fără restart server).
# vision.py citește din RUNTIME (nu din constantele de mai sus) ca să poată fi
# schimbată per-urcare din frontend/API.
RUNTIME = {
    "sobel": USE_SOBEL,
    "gabor": USE_GABOR,
    "da2": USE_DA2_COV,
    "require_all_flat": REQUIRE_ALL_FLAT_SENSORS,
}


def set_active_signals(sobel=None, gabor=None, da2=None, require_all_flat=None):
    """Setează la runtime ce semnale sunt active pentru urcare. None = nemodificat.
    Dacă toate trei ar fi False, ignorăm (lăsăm setarea anterioară) ca să nu blocăm zborul."""
    new = dict(RUNTIME)
    if sobel is not None:
        new["sobel"] = bool(sobel)
    if gabor is not None:
        new["gabor"] = bool(gabor)
    if da2 is not None:
        new["da2"] = bool(da2)
    if require_all_flat is not None:
        new["require_all_flat"] = bool(require_all_flat)
    if not (new["sobel"] or new["gabor"] or new["da2"]):
        print("⚠️ set_active_signals: cel puțin un semnal trebuie activ — ignor setarea goală.")
        return
    RUNTIME.update(new)
    print(f"🪜 Semnale urcare active: sobel={RUNTIME['sobel']} gabor={RUNTIME['gabor']} "
          f"da2={RUNTIME['da2']} require_all_flat={RUNTIME['require_all_flat']}")


def active_signals_str():
    """Returnează semnalele active ca string scurt, ex: 'sobel,gabor,da2'."""
    parts = [k for k in ("sobel", "gabor", "da2") if RUNTIME.get(k)]
    return ",".join(parts) if parts else "none"

CLIMB_TIMEOUT_S  = 50
MIN_BATTERY      = 20
LAND_BATTERY     = 30
TAKEOFF_WAIT_S   = 3.0
CTRL_HZ          = 12

PRELAND_DASH_DISTANCE_M = 1
PRELAND_DASH_SPEED      = 30
PRELAND_DASH_DT         = 0.2
PRELAND_PULSE_ON_S      = 0.30
PRELAND_PULSE_OFF_S     = 0.10

CRAB_SEARCH_SPEED    = 32
CRAB_INITIAL_DIST_M  = 1.6
CRAB_STEP_DIST_M     = 0.15

PRELAND_TURN_DEG      = 205
PRELAND_YAW_SPEED     = 80
PRELAND_ROT_TIME_90_S = 1.125

ANALYSIS_W       = 320
ANALYSIS_H       = 240

ROW_SMOOTH_SIGMA  = 3
ROW_PEAK_MIN_DIST = 25
ROW_PEAK_THRESH   = 0.12
ROW_MIN_PEAKS     = 3
ROW_SPACING_CV    = 0.75
ROW_MIN_LINE_WIDTH = 0.55

GABOR_THETA      = np.pi / 2
GABOR_SIGMA      = 4.0
GABOR_GAMMA      = 0.5
GABOR_KSIZE      = 29
GABOR_ENERGY_CAP = 0.55
GABOR_LAMBDAS    = [14, 22, 32, 45, 65]

DEPTH_HZ         = 4
DEPTH_COV_STAIR  = 0.28
DEPTH_COV_FLAT   = 0.12

STEP_HEIGHT_M    = 0.20
TELLO_FY         = (ANALYSIS_H / 2.0) / np.tan(np.radians(33.0))
