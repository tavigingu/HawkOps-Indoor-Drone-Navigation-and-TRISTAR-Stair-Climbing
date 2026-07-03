import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from .config import *
from . import config as cfg

# ═══════════════════════════════════════════════════════════════════════════════
#  GLOBAL VARIABLES — Image Analysis
# ═══════════════════════════════════════════════════════════════════════════════

_TRAP_MASK: np.ndarray = None   # initializat la prima folosire

_GABOR_KERNELS = [
    cv2.getGaborKernel(
        (GABOR_KSIZE, GABOR_KSIZE),
        GABOR_SIGMA,
        GABOR_THETA,
        float(lam),
        GABOR_GAMMA,
        0,
        ktype=cv2.CV_32F,
    )
    for lam in GABOR_LAMBDAS
]


# ═══════════════════════════════════════════════════════════════════════════════
#  ANALIZA IMAGINE — GRADIENT SOBEL
# ═══════════════════════════════════════════════════════════════════════════════

def _gradient_orientation_score(gray_small: np.ndarray) -> float:
    """
    Row-profile method cu masca trapezoidala + coverage + penalizare verticale.

    Imbunatatiri fata de versiunea anterioara:
    1. Masca /_\\ : exclude marginile (balustrade, pereti) tinand cont de
       perspectiva — mai ingusta sus, mai lata jos.
    2. Coverage score: treptele trebuie sa fie distribuite pe toata inaltimea
       framului, nu toate concentrate intr-o zona mica.
    3. Penalizare linii verticale: daca Gx domina in zona centrala (fara 15%
       margini) inseamna ca au aparut alte detalii → posibil sfarsit scari.
    4. ROW_MIN_PEAKS = 3 (3 trepte = minim credibil).
    """
    gy = cv2.Sobel(gray_small, cv2.CV_32F, 0, 1, ksize=3)
    gx = cv2.Sobel(gray_small, cv2.CV_32F, 1, 0, ksize=3)
    mag_gy = np.abs(gy)
    mag_gx = np.abs(gx)
    h, w   = mag_gy.shape

    # Aplica masca trapezoidala — zerifica pixelii din zone excluse
    trap = _get_trap_mask()
    mag_gy_m = mag_gy.copy()
    mag_gy_m[trap == 0] = 0.0

    # Profil 1D: media pe latime per linie (in zona mascata)
    row_profile = mag_gy_m.mean(axis=1).astype(np.float32)
    k1d = cv2.getGaussianKernel(max(3, ROW_SMOOTH_SIGMA * 2 + 1), ROW_SMOOTH_SIGMA).flatten()
    row_profile = np.convolve(row_profile, k1d, mode='same')

    if row_profile.max() < 1e-6:
        return 0.0
    row_profile = row_profile / row_profile.max()

    # Detectie varfuri cu NMS
    peaks = []
    for i in range(1, h - 1):
        if (row_profile[i] > row_profile[i - 1] and
                row_profile[i] > row_profile[i + 1] and
                row_profile[i] >= ROW_PEAK_THRESH):
            if peaks and (i - peaks[-1]) < ROW_PEAK_MIN_DIST:
                if row_profile[i] > row_profile[peaks[-1]]:
                    peaks[-1] = i
            else:
                peaks.append(i)

    # Filtreaza: linia trebuie sa acopere ≥ ROW_MIN_LINE_WIDTH din latime
    valid_peaks = []
    for pk in peaks:
        row_data = mag_gy_m[pk].astype(np.float32)
        row_max  = row_data.max()
        if row_max < 1e-6:
            continue
        active_frac = float(np.count_nonzero(row_data >= row_max * 0.15)) / w
        if active_frac >= ROW_MIN_LINE_WIDTH:
            valid_peaks.append(pk)

    peaks   = valid_peaks
    n_peaks = len(peaks)
    if n_peaks < ROW_MIN_PEAKS:
        return 0.0

    # Uniformitate spacing cu toleranta perspectiva
    # Spre partea de sus a framului treptele apar mai mici → spacing scade natural
    spacings = np.diff(np.array(peaks, dtype=np.float32))
    spacing_mean = float(spacings.mean())
    if spacing_mean < 1:
        return 0.0
    # Corectam tendinta descrescatoare (perspectiva normala)
    n_sp = len(spacings)
    if n_sp >= 2:
        x = np.arange(n_sp, dtype=np.float32)
        slope = float(np.polyfit(x, spacings, 1)[0])
        if slope < 0:  # spacing scade spre sus = perspectiva normala
            correction = slope * x
            spacings_corr = spacings - correction
        else:
            spacings_corr = spacings
    else:
        spacings_corr = spacings
    spacing_cv  = float(spacings_corr.std()) / (float(spacings_corr.mean()) + 1e-6)
    uniformity  = float(np.clip(1.0 - spacing_cv / ROW_SPACING_CV, 0.0, 1.0))

    # Coverage: treptele sa fie distribuite pe ≥50% din inaltimea framului
    # (daca toate treptele sunt ingramadite intr-o zona = geam/podea, nu scari)
    coverage = float(np.clip((peaks[-1] - peaks[0]) / (h * 0.5), 0.0, 1.0))

    # Densitate varfuri
    peak_density = float(np.clip((n_peaks - ROW_MIN_PEAKS) / 3.0, 0.0, 1.0))

    # Penalizare linii verticale: daca Gx > Gy in zona centrala (fara 15% margini)
    # → alte detalii in frame (usi, ferestre, pereti) → posibil sfarsit scari
    cx0 = int(0.15 * w)
    cx1 = int(0.85 * w)
    mean_gx   = float(np.mean(mag_gx[:, cx0:cx1]))
    mean_gy_c = float(np.mean(mag_gy[:, cx0:cx1])) + 1e-6
    vert_ratio   = mean_gx / mean_gy_c
    # <0.8: orizontal domina (scari) → vert_penalty=1.0
    # >1.5: vertical domina (alte detalii) → vert_penalty=0.0
    vert_penalty = float(np.clip(1.0 - (vert_ratio - 0.8) / 0.7, 0.0, 1.0))

    score = (0.40 * uniformity +
             0.35 * coverage   +
             0.25 * peak_density)
    return float(np.clip(score, 0.0, 1.0))


# ═══════════════════════════════════════════════════════════════════════════════
#  MASCA TRAPEZOIDALA — exclude marginile laterale si balustradele
# ═══════════════════════════════════════════════════════════════════════════════

def _get_trap_mask() -> np.ndarray:
    """
    Masca /_\\ : mai lata la baza (5% margine) si mai ingusta sus (15% margine).
    Tine cont de perspectiva: balustradele converg spre centru la distanta.
    Exclude si peretii laterali care ar genera linii verticale false.
    """
    global _TRAP_MASK
    if _TRAP_MASK is None:
        h, w = ANALYSIS_H, ANALYSIS_W
        mask = np.zeros((h, w), dtype=np.uint8)
        pts = np.array([
            [int(0.15 * w), 0],          # sus-stanga:   15% in
            [int(0.85 * w), 0],          # sus-dreapta:  15% in
            [int(0.95 * w), h - 1],      # jos-dreapta:   5% in
            [int(0.05 * w), h - 1],      # jos-stanga:    5% in
        ], dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)
        _TRAP_MASK = mask
    return _TRAP_MASK


# ═══════════════════════════════════════════════════════════════════════════════
#  CORECTIE LATERALA — extinderea liniilor pe latime frame
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_lateral_error(gray_small: np.ndarray) -> tuple:
    """
    Detecteaza eroarea laterala din cat de mult se extind liniile orizontale
    (treptele) spre marginile stanga/dreapta ale framului.

    Fizic:
      - Drone centrata: liniile ating ambele margini → gap stanga ≈ gap dreapta
      - Deriva dreapta: liniile mai mult spre stanga → right_gap mare → du-te stanga
      - Deriva stanga:  liniile mai mult spre dreapta → left_gap mare → du-te dreapta
      - Linii inguste (distanta mare): ambele gap-uri mari → centreaza dupa mijlocul lor

    Returns:
        error      : float [-1..+1]  (>0 = du-te dreapta, <0 = du-te stanga)
        confidence : float [0..1]   (cat de sigura e corectia)
        left_gap   : float [0..1]   (fractia din stanga fara trepte)
        right_gap  : float [0..1]   (fractia din dreapta fara trepte)
    """
    gy      = cv2.Sobel(gray_small, cv2.CV_32F, 0, 1, ksize=3)
    mag_gy  = np.abs(gy)
    h, w    = mag_gy.shape

    # Profil + varfuri (identic cu _gradient_orientation_score)
    row_profile = mag_gy.mean(axis=1).astype(np.float32)
    k1d = cv2.getGaussianKernel(max(3, ROW_SMOOTH_SIGMA * 2 + 1), ROW_SMOOTH_SIGMA).flatten()
    row_profile = np.convolve(row_profile, k1d, mode='same')
    prof_max = row_profile.max()
    if prof_max < 1e-6:
        return 0.0, 0.0, 0.5, 0.5
    row_profile_n = row_profile / prof_max

    peaks = []
    for i in range(1, h - 1):
        if (row_profile_n[i] > row_profile_n[i - 1] and
                row_profile_n[i] > row_profile_n[i + 1] and
                row_profile_n[i] >= ROW_PEAK_THRESH):
            if peaks and (i - peaks[-1]) < ROW_PEAK_MIN_DIST:
                if row_profile_n[i] > row_profile_n[peaks[-1]]:
                    peaks[-1] = i
            else:
                peaks.append(i)

    if len(peaks) < ROW_MIN_PEAKS:
        return 0.0, 0.0, 0.5, 0.5

    # Pentru fiecare treapta, gasim primul si ultimul pixel activ pe orizontala
    EDGE_THRESH = 0.15   # 15% din maximul randului = muchia activa
    left_gaps, right_gaps = [], []

    for pk in peaks:
        row_data = mag_gy[pk].astype(np.float32)
        row_max  = row_data.max()
        if row_max < 1e-6:
            continue
        above = row_data >= (row_max * EDGE_THRESH)
        cols  = np.where(above)[0]
        if len(cols) < 4:
            continue
        left_gaps.append(float(cols[0]) / w)           # fractie din stanga fara semnal
        right_gaps.append(float(w - 1 - cols[-1]) / w) # fractie din dreapta fara semnal

    if not left_gaps:
        return 0.0, 0.0, 0.5, 0.5

    avg_lg = float(np.mean(left_gaps))
    avg_rg = float(np.mean(right_gaps))

    # error = avg_lg - avg_rg
    #   avg_lg > avg_rg: linii mai spre dreapta → drona deriva stanga → du-te dreapta → error > 0
    #   avg_rg > avg_lg: linii mai spre stanga  → drona deriva dreapta → du-te stanga → error < 0
    error      = float(np.clip(avg_lg - avg_rg, -1.0, 1.0))
    confidence = float(np.clip(abs(error) / 0.20, 0.0, 1.0))

    return error, confidence, avg_lg, avg_rg


# ═══════════════════════════════════════════════════════════════════════════════
#  ANALIZA IMAGINE — FILTRU GABOR MULTI-SCALE ADAPTIV
# ═══════════════════════════════════════════════════════════════════════════════

def _gabor_energy_score(gray_small: np.ndarray,
                        depth: np.ndarray = None) -> tuple:
    """
    Edge-width coverage score Gabor — inlocuieste energia bruta.

    Problema cu energia bruta: un geam sau o margine de podea poate da
    energie mare la un lambda gresit (ales de DA2 adaptiv).

    Solutia (observatie utilizator):
      - Pe scari: liniile Gabor se intind EDGE-TO-EDGE (margine la margine)
      - Pe palier/geam/podea: liniile sunt SCURTE sau PARTIALE
      - Perspectiva: liniile mai sus pot fi putin mai scurte (permis)

    Score = fractia de randuri cu raspuns Gabor semnificativ
            care se intinde aproape de ambele margini ale framului.

    Returneaza (score: float [0,1], lambda_used: int).
    """
    f32 = gray_small.astype(np.float32)
    h, w = f32.shape

    # Selectam kernelul optim
    best_kernel = _GABOR_KERNELS[2]   # default: lambda median
    best_lambda = GABOR_LAMBDAS[2]
    use_depth   = depth is not None

    if use_depth:
        h_d, w_d = depth.shape
        d_center = depth[int(h_d*0.30):int(h_d*0.70), int(w_d*0.20):int(w_d*0.80)]
        valid = d_center[(d_center > 0.3) & (d_center < 8.0)]
        if valid.size > 40:
            d_avg      = float(np.median(valid))
            spacing_px = float(np.clip((STEP_HEIGHT_M / d_avg) * TELLO_FY,
                                       GABOR_LAMBDAS[0], GABOR_LAMBDAS[-1]))
            idx        = int(np.argmin([abs(lam - spacing_px) for lam in GABOR_LAMBDAS]))
            best_kernel = _GABOR_KERNELS[idx]
            best_lambda = GABOR_LAMBDAS[idx]
        else:
            use_depth = False

    if not use_depth:
        # Multi-scale: kernelul cu cea mai mare energie (proxy distanta)
        baseline   = float(np.mean(f32)) + 1e-6
        best_e     = 0.0
        for ki, (k, lam) in enumerate(zip(_GABOR_KERNELS, GABOR_LAMBDAS)):
            e = float(np.mean(np.abs(cv2.filter2D(f32, cv2.CV_32F, k)))) / baseline
            if e > best_e:
                best_e, best_lambda, best_kernel = e, lam, _GABOR_KERNELS[ki]

    filtered     = cv2.filter2D(f32, cv2.CV_32F, best_kernel)
    abs_filtered = np.abs(filtered)
    row_means    = abs_filtered.mean(axis=1)

    # Prag: un rand e "activ" daca raspunsul e ≥25% din maximul global
    global_thresh = float(row_means.max()) * 0.25 + 1e-6

    full_width_count = 0
    total_active     = 0

    for row_idx in range(h):
        if row_means[row_idx] < global_thresh:
            continue
        total_active += 1

        # Marginile cerute — perspectiva: mai permisiv sus, mai strict jos
        # row_idx=0 (sus): left_req=18%, right_req=82%  (linii mai scurte OK)
        # row_idx=h (jos): left_req=10%, right_req=90%  (linii trebuie sa acopere mai mult)
        t         = row_idx / h            # 0=sus, 1=jos
        left_req  = 0.18 - 0.08 * t       # 18%→10% de la stanga
        right_req = 0.82 + 0.08 * t       # 82%→90% pana la dreapta

        row_data   = abs_filtered[row_idx]
        row_max    = float(row_data.max())
        if row_max < 1e-6:
            continue
        active_cols = np.where(row_data >= row_max * 0.20)[0]
        if len(active_cols) < 2:
            continue

        first_col = active_cols[0]  / w
        last_col  = active_cols[-1] / w

        if first_col <= left_req and last_col >= right_req:
            full_width_count += 1

    if total_active == 0:
        return 0.0, best_lambda

    red_count = total_active - full_width_count

    # coverage_score = fractia randurilor bune (edge-to-edge)
    coverage_score = float(full_width_count) / float(total_active)

    # red_ratio = cat de multe linii rosii sunt (scurte / partiale)
    red_ratio = float(red_count) / float(total_active)

    # Scor combinat:
    # - coverage_score trebuie sa fie mare (>0.55 = scari)
    # - red_ratio penalizeaza agresiv (putere 0.35 = impact mult mai rapid)
    # - daca >20% din linii sunt rosii → scor sub 0.5
    # - daca >40% din linii sunt rosii → scor aproape 0
    score = coverage_score * (1.0 - red_ratio ** 0.35)
    score = float(np.clip(score, 0.0, 1.0))
    return score, best_lambda


# ═══════════════════════════════════════════════════════════════════════════════
#  ANALIZA DEPTH — CoV suprafata
# ═══════════════════════════════════════════════════════════════════════════════

def _depth_cov_score(depth: np.ndarray) -> tuple:
    """
    Monotonie adaptiva pe 100% din frame — fara benzi prestabilite.

    Logica (observatii utilizator):
    - Folosim TOT frame-ul (0-100%), fara taieri
    - Calculam per-row median depth => profil 1D de H valori
    - Pe scari: profilul creste monoton de jos in sus
        (treapta de jos = aproape = valoare mica,
         treapta de sus  = departe = valoare mare)
    - Pe palier: profilul plat sau neuniform — NU creste monoton
    - Suplimentar verificam latimea activa per-row:
        pe scari largimea benzilor scade de jos in sus (perspectiva)
        pe palier largimea e uniforma sau haotic
    """
    if depth is None:
        return 0.0, 0.0, 0.5, 0

    h, w = depth.shape

    # ── CoV pe 100% din frame ──────────────────────────────────────────────
    valid_all = depth[(depth > 0.2) & (depth < 12.0)]
    if valid_all.size < 60:
        return 0.0, 0.0, 0.5, 0

    mean_d = float(np.mean(valid_all))
    std_d  = float(np.std(valid_all))
    cov    = std_d / (mean_d + 1e-6)

    cov_stair = float(np.clip(
        (cov - DEPTH_COV_FLAT) / (DEPTH_COV_STAIR - DEPTH_COV_FLAT), 0.0, 1.0))
    cov_flat  = 1.0 - cov_stair

    # ── Profil depth per-row (median pe toata latimea) ────────────────────
    # row_depth[i] = adancimea medie la linia i din frame
    row_depth = np.array([
        float(np.median(r[(r > 0.2) & (r < 12.0)])) if np.any((r > 0.2) & (r < 12.0)) else 0.0
        for r in depth
    ])

    # Netezim profilul (sigma=5 linii) ca sa eliminam zgomotul fin
    from scipy.ndimage import gaussian_filter1d
    smooth = gaussian_filter1d(row_depth, sigma=5)

    # ── Monotonie depth ──────────────────────────────────────────────────
    # Pe scari: smooth[i] (sus) > smooth[i+1] (jos)  adica departe -> aproape
    # Ignoram randurile cu depth=0 (invalide)
    valid_rows = [i for i in range(h) if smooth[i] > 0.2]
    if len(valid_rows) < 4:
        monotonic_score = 0.5
        n_red_bands = 0
    else:
        # Impartim frame-ul in 5 benzi egale si verificam monotonia fiecareia
        # O banda e "rosie" daca depth-ul mediu al ei e MAI MARE (mai aproape)
        # decat banda de deasupra ei (care ar trebui sa fie mai departe)
        n_bands = 5
        band_h  = h // n_bands
        band_depths = []
        for b in range(n_bands):
            r0 = b * band_h
            r1 = r0 + band_h
            vals = smooth[r0:r1]
            valid = vals[vals > 0.2]
            band_depths.append(float(np.median(valid)) if len(valid) > 0 else 0.0)

        # Numara benzile rosii: banda b e rosie daca band_depths[b] < band_depths[b+1]
        # (sus mai aproape decat jos = inversie = rosu)
        n_red_bands = 0
        for b in range(n_bands - 1):
            if band_depths[b] > 0.1 and band_depths[b+1] > 0.1:
                if band_depths[b] < band_depths[b+1]:   # sus mai aproape decat jos = gresit
                    n_red_bands += 1

        # Scor bazat pe numarul de benzi rosii:
        # 0 rosii  → monotonic_score = 1.0
        # 1 rosie  → monotonic_score = 0.05  → stair_score capped la 0.50 max
        # 2+ rosii → monotonic_score = 0.0   → stair_score = 0
        if n_red_bands == 0:
            monotonic_score = 1.0
        elif n_red_bands == 1:
            monotonic_score = 0.05   # cu CoV+perspectiva max posibil = 0.50
        else:
            monotonic_score = 0.0

    # ── Verificare latime activa per-row (perspectiva) ────────────────────
    # Pe scari: latimea benzii active scade de jos in sus (perspectiva)
    # Calculam latimea activa (nr de px > prag) per row
    threshold = mean_d * 0.5
    row_width = np.array([
        float(np.sum(depth[r] > threshold)) / w
        for r in range(h)
    ])
    smooth_w = gaussian_filter1d(row_width, sigma=5)

    # Comparam jumatatea de sus vs jumatatea de jos
    # Pe scari: widths de sus < widths de jos (perspectiva)
    mid = h // 2
    width_top = float(np.mean(smooth_w[:mid][smooth_w[:mid] > 0.05])) if np.any(smooth_w[:mid] > 0.05) else 0.5
    width_bot = float(np.mean(smooth_w[mid:][smooth_w[mid:] > 0.05])) if np.any(smooth_w[mid:] > 0.05) else 0.5
    # scari: width_top <= width_bot  → perspective_score inalt
    # daca sunt egale (trepte edge-to-edge) → scor 1.0
    # daca top > bot (nenatural) → scor scade
    if width_bot > 0.05:
        ratio = width_top / width_bot
        if ratio <= 1.0:
            perspective_score = 1.0          # egal sau mai ingust sus → valid
        else:
            perspective_score = float(np.clip(2.0 - ratio, 0.0, 1.0))  # mai lat sus → penalizare
    else:
        perspective_score = 0.5

    # ── Score final: 50% CoV + 35% monotonie + 15% perspectiva ──────────
    stair_score = 0.50 * cov_stair + 0.35 * monotonic_score        + 0.15 * perspective_score
    flat_score  = 0.50 * cov_flat  + 0.35 * (1.0 - monotonic_score) + 0.15 * (1.0 - perspective_score)

    # Penalizare hard: 1 banda rosie → max 0.50  |  2+ benzi rosii → 0.0
    if n_red_bands >= 2:
        stair_score = 0.0
    elif n_red_bands == 1:
        stair_score = min(stair_score, 0.50)

    return cov, stair_score, flat_score, n_red_bands


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIDENCE COMPOZITA
# ═══════════════════════════════════════════════════════════════════════════════

def _analyze_frame(frame_bgr: np.ndarray, depth: np.ndarray) -> dict:
    """
    Calculeaza toti scorii de detectie pe frame-ul dat.
    Returneaza dict cu:
      stair_conf   — cat de sigur suntem ca sunt scari  (0..1)
      flat_conf    — cat de sigur suntem ca e palier     (0..1)
      grad_score   — grad. orientare orizontala          (0..1)
      gabor_score  — energie Gabor                       (0..1)
      cov          — CoV depth                           (float)
    """
    small = cv2.resize(frame_bgr, (ANALYSIS_W, ANALYSIS_H))
    gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    # Selecția RUNTIME a semnalelor (suprascrie env-ul; se poate schimba per-urcare)
    use_sobel = cfg.RUNTIME.get("sobel", USE_SOBEL)
    use_gabor = cfg.RUNTIME.get("gabor", USE_GABOR)
    use_da2   = cfg.RUNTIME.get("da2", USE_DA2_COV)
    require_all_flat = cfg.RUNTIME.get("require_all_flat", REQUIRE_ALL_FLAT_SENSORS)

    # Calculeaza doar senzorii activi
    grad_score  = _gradient_orientation_score(gray) if use_sobel  else 0.5
    gabor_lam   = 0
    if use_gabor:
        gabor_score, gabor_lam = _gabor_energy_score(gray, depth)
    else:
        gabor_score = 0.5

    cov, depth_stair, depth_flat, n_red_bands = _depth_cov_score(depth)
    has_depth = (depth is not None) and use_da2

    # Ponderi dinamice in functie de ce senzori sunt activi
    active = {
        "sobel": use_sobel,
        "gabor": use_gabor,
        "da2":   has_depth,
    }
    weights = {
        "sobel": 0.35 if active["sobel"] else 0.0,
        "gabor": 0.25 if active["gabor"] else 0.0,
        "da2":   0.40 if active["da2"]   else 0.0,
    }
    total_w = sum(weights.values())
    if total_w < 1e-6:
        # Niciun senzor activ — nu zburam
        stair_conf = 0.0
        flat_conf  = 0.0
    else:
        # Renormalizam ponderi la 1.0
        wS = weights["sobel"] / total_w
        wG = weights["gabor"] / total_w
        wD = weights["da2"]   / total_w

        stair_conf = wS * grad_score + wG * gabor_score + wD * depth_stair
        flat_conf  = wS * (1.0 - grad_score) + wG * (1.0 - gabor_score) + wD * depth_flat

    # Conditie de palier: AND strict sau OR, configurabil
    conditions_flat = []
    if use_sobel:
        conditions_flat.append(grad_score  < 0.40)   # Sobel: fara muchii orizontale
    if use_gabor:
        conditions_flat.append(gabor_score < 0.40)   # Gabor: fara pattern periodic
    if has_depth:
        conditions_flat.append(cov < DEPTH_COV_FLAT * 1.5)  # DA2: suprafata plata

    if not conditions_flat:
        all_flat = False
    elif require_all_flat:
        all_flat = all(conditions_flat)     # AND: toti senzorii activi confirma
    else:
        all_flat = any(conditions_flat)     # OR: destul un senzor

    # Corectie laterala (doar daca Sobel e activ — el produce row-profile-ul)
    lat_err, lat_conf, lat_lg, lat_rg = (
        _compute_lateral_error(gray) if use_sobel else (0.0, 0.0, 0.5, 0.5)
    )

    return {
        "stair_conf":  float(np.clip(stair_conf, 0.0, 1.0)),
        "flat_conf":   float(np.clip(flat_conf,  0.0, 1.0)),
        "grad_score":  grad_score,
        "gabor_score":  gabor_score,
        "gabor_lam":   gabor_lam,
        "cov":         cov,
        "depth_stair": float(depth_stair) if has_depth else 0.0,
        "has_depth":   has_depth,
        "all_flat":    all_flat,
        "active_sensors": active,
        "lat_err":     lat_err,
        "lat_conf":    lat_conf,
        "lat_lg":      lat_lg,
        "lat_rg":      lat_rg,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  OVERLAY FEREASTRA LIVE
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_overlay(
    frame_bgr: np.ndarray,
    r: dict,
    state: str,
    flat_count: int,
    elapsed: float,
    up_v: int,
    battery: int,
) -> np.ndarray:
    """Deseneaza overlay cu informatii de navigare pe frame-ul live."""
    img = frame_bgr.copy()
    h, w = img.shape[:2]

    # ── Header bar (stare + baterie) ──────────────────────────────────────
    STATE_COLORS = {
        "SEARCH":      (50, 160, 50),
        "CLIMBING":    (20, 130, 240),
        "PRE_LAND":    (30, 30, 200),
        "SEARCH_NEXT": (180, 100, 20),
        "DONE":        (120, 120, 120),
    }
    bar_color = STATE_COLORS.get(state, (100, 100, 100))
    cv2.rectangle(img, (0, 0), (w, 40), bar_color, -1)
    cv2.rectangle(img, (0, 0), (w, 40), (255, 255, 255), 1)

    if state == "CLIMBING":
        hdr = f"URCARE  t={elapsed:.1f}s   fwd={FORWARD_SPEED}  up={up_v}"
    elif state == "SEARCH":
        hdr = "CAUTARE SCARI ..."
    elif state == "PRE_LAND":
        hdr = "PALIER DETECTAT — ATERIZARE ..."
    else:
        hdr = state

    cv2.putText(img, hdr, (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.66, (255, 255, 255), 2, cv2.LINE_AA)

    bat_col = (0, 220, 0) if battery > 40 else (0, 160, 255) if battery > 20 else (0, 0, 220)
    cv2.putText(img, f"Bat:{battery}%", (w - 90, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.60, bat_col, 2, cv2.LINE_AA)

    # ── Panel jos semi-transparent ────────────────────────────────────────
    panel_h = 96
    panel_y = h - panel_h
    overlay = img.copy()
    cv2.rectangle(overlay, (0, panel_y), (w, h), (15, 15, 15), -1)
    cv2.addWeighted(overlay, 0.72, img, 0.28, 0, img)

    bar_max_w = w // 2 - 88

    def _bar(label: str, val: float, y: int, color: tuple):
        bw = int(bar_max_w * max(0.0, min(1.0, val)))
        cv2.putText(img, f"{label}:", (8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, (190, 190, 190), 1, cv2.LINE_AA)
        cv2.rectangle(img, (68, y - 12), (68 + bar_max_w, y + 3), (55, 55, 55), -1)
        if bw > 0:
            cv2.rectangle(img, (68, y - 12), (68 + bw, y + 3), color, -1)
        cv2.putText(img, f"{val:.2f}", (68 + bar_max_w + 6, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (210, 210, 210), 1, cv2.LINE_AA)

    _bar("SCARI",  r["stair_conf"],  panel_y + 18, (0, 200, 80))
    _bar("PALIER", r["flat_conf"],   panel_y + 38, (30, 120, 255))
    _bar("GRAD",   r["grad_score"],  panel_y + 58, (180, 180, 0))
    _bar("GABOR",  r["gabor_score"], panel_y + 78, (180, 80, 200))

    # ── Dreapta-jos: progress palier + sageti miscare ─────────────────────
    rx = w // 2 + 20
    rw = w // 2 - 30

    if state == "CLIMBING":
        # Progress palier
        cv2.putText(img, f"Palier: {flat_count}/{FLAT_FRAMES_NEEDED}",
                    (rx, panel_y + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (170, 170, 170), 1, cv2.LINE_AA)
        cv2.rectangle(img, (rx, panel_y + 24), (rx + rw, panel_y + 38), (55, 55, 55), -1)
        prog_w = int(rw * (flat_count / FLAT_FRAMES_NEEDED))
        if prog_w > 0:
            cv2.rectangle(img, (rx, panel_y + 24), (rx + prog_w, panel_y + 38), (30, 140, 255), -1)

        # Sageti directie (inainte + sus) in centrul frame-ului
        cx, cy = w // 2, panel_y // 2 + 20
        # Sus
        cv2.arrowedLine(img, (cx, cy + 12), (cx, cy - 38),
                        (0, 220, 90), 2, tipLength=0.30)
        # Inainte
        cv2.arrowedLine(img, (cx - 12, cy), (cx + 38, cy),
                        (30, 170, 255), 2, tipLength=0.30)

        # Indicator corectie laterala
        lat_err  = r.get("lat_err",  0.0)
        lat_lg   = r.get("lat_lg",   0.5)
        lat_rg   = r.get("lat_rg",   0.5)
        ind_y    = cy + 55
        ind_w    = 80
        ind_x0   = cx - ind_w // 2
        # Bara de fundal
        cv2.rectangle(img, (ind_x0, ind_y - 6), (ind_x0 + ind_w, ind_y + 6),
                      (50, 50, 50), -1)
        # Gap stanga (rosu) si gap dreapta (albastru)
        lg_w = int(ind_w * min(lat_lg, 0.5))
        rg_w = int(ind_w * min(lat_rg, 0.5))
        if lg_w > 0:
            cv2.rectangle(img, (ind_x0, ind_y - 5),
                          (ind_x0 + lg_w, ind_y + 5), (60, 60, 220), -1)
        if rg_w > 0:
            cv2.rectangle(img, (ind_x0 + ind_w - rg_w, ind_y - 5),
                          (ind_x0 + ind_w, ind_y + 5), (220, 60, 60), -1)
        # Linie centrala
        cv2.line(img, (cx, ind_y - 8), (cx, ind_y + 8), (200, 200, 200), 1)
        # Sageata corectie daca e semnificativa
        if abs(lat_err) > LATERAL_DEAD_ZONE:
            arr_len = int(30 * abs(lat_err))
            arr_col = (0, 220, 220)
            if lat_err > 0:   # du-te dreapta
                cv2.arrowedLine(img, (cx, ind_y), (cx + arr_len, ind_y),
                                arr_col, 2, tipLength=0.40)
            else:             # du-te stanga
                cv2.arrowedLine(img, (cx, ind_y), (cx - arr_len, ind_y),
                                arr_col, 2, tipLength=0.40)
        # Label
        lat_label = f"lat:{lat_err:+.2f}"
        cv2.putText(img, lat_label, (cx - 25, ind_y + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1, cv2.LINE_AA)

    # ── DA2 status ────────────────────────────────────────────────────────
    da2_col  = (80, 220, 80) if r.get("has_depth") else (100, 100, 100)
    da2_text = "DA2: ON" if r.get("has_depth") else "DA2: OFF"
    cv2.putText(img, da2_text, (rx, panel_y + 58),
                cv2.FONT_HERSHEY_SIMPLEX, 0.46, da2_col, 1, cv2.LINE_AA)

    if r.get("has_depth"):
        cov_str = f"CoV: {r['cov']:.3f}"
        cv2.putText(img, cov_str, (rx, panel_y + 78),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, (150, 150, 150), 1, cv2.LINE_AA)

    return img

def _compute_debug_visuals(frame_bgr: np.ndarray, depth, r: dict) -> tuple:
    PW, PH = 320, 240
    small = cv2.resize(frame_bgr, (PW, PH))
    gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    # Panel A: Sobel
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag_gy = np.abs(gy)
    row_profile_raw = mag_gy.mean(axis=1).astype(np.float32)
    k1d = cv2.getGaussianKernel(max(3, ROW_SMOOTH_SIGMA * 2 + 1), ROW_SMOOTH_SIGMA).flatten()
    row_profile_sm = np.convolve(row_profile_raw, k1d, mode='same')
    prof_max = row_profile_sm.max()
    row_profile_n = row_profile_sm / prof_max if prof_max > 1e-6 else row_profile_sm

    panel_a = np.zeros((PH, PW, 3), dtype=np.uint8)
    trap = _get_trap_mask()
    trap_rs = cv2.resize(trap.astype(np.uint8), (PW, PH), interpolation=cv2.INTER_NEAREST)
    for y in range(PH):
        if trap_rs[y].any():
            xs = np.where(trap_rs[y])[0]
            x0, x1 = int(xs[0]), int(xs[-1])
            panel_a[y, x0:x1] = (0, 40, 0)

    graph_x_max = PW - 10
    for y in range(PH):
        val = row_profile_n[y] if y < len(row_profile_n) else 0.0
        x_end = 10 + int(val * (graph_x_max - 10))
        cv2.line(panel_a, (10, y), (x_end, y), (0, 180, 0), 1)

    h_p = len(row_profile_n)
    peaks_vis = []
    for i in range(1, h_p - 1):
        if (row_profile_n[i] > row_profile_n[i - 1] and
                row_profile_n[i] > row_profile_n[i + 1] and
                row_profile_n[i] >= ROW_PEAK_THRESH):
            if peaks_vis and (i - peaks_vis[-1]) < ROW_PEAK_MIN_DIST:
                if row_profile_n[i] > row_profile_n[peaks_vis[-1]]:
                    peaks_vis[-1] = i
            else:
                peaks_vis.append(i)

    for pk in peaks_vis:
        cv2.line(panel_a, (0, pk), (PW, pk), (0, 220, 220), 1)

    h_trap, w_trap = PH, PW
    inset_bot = int(w_trap * 0.05)
    inset_top = int(w_trap * 0.15)
    pts = np.array([[inset_bot, h_trap - 1],
                    [w_trap - inset_bot, h_trap - 1],
                    [w_trap - inset_top, 0],
                    [inset_top, 0]], dtype=np.int32)
    cv2.polylines(panel_a, [pts], isClosed=True, color=(80, 80, 80), thickness=1)

    # Panel B: Gabor
    f32      = gray.astype(np.float32)
    lam_idx  = min(range(len(GABOR_LAMBDAS)),
                   key=lambda i: abs(GABOR_LAMBDAS[i] - r.get("gabor_lam", GABOR_LAMBDAS[2])))
    gabor_resp = cv2.filter2D(f32, cv2.CV_32F, _GABOR_KERNELS[lam_idx])       
    gabor_abs  = np.abs(gabor_resp)
    gabor_abs_rs   = cv2.resize(gabor_abs, (PW, PH), interpolation=cv2.INTER_LINEAR)
    row_means_b_rs = gabor_abs_rs.mean(axis=1)
    global_thresh_b = float(row_means_b_rs.max()) * 0.25 + 1e-6

    gabor_norm = cv2.normalize(gabor_abs_rs, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    panel_b    = cv2.applyColorMap(gabor_norm, cv2.COLORMAP_INFERNO)

    for row_idx in range(PH):
        if row_means_b_rs[row_idx] < global_thresh_b: continue
        row_data    = gabor_abs_rs[row_idx]
        row_max_b   = float(row_data.max())
        if row_max_b < 1e-6: continue
        active_cols = np.where(row_data >= row_max_b * 0.20)[0]
        if len(active_cols) < 2: continue

        t         = row_idx / PH
        left_req  = 0.18 - 0.08 * t
        right_req = 0.82 + 0.08 * t
        first_col = active_cols[0]  / PW
        last_col  = active_cols[-1] / PW

        if not (first_col <= left_req and last_col >= right_req):
            cv2.line(panel_b,
                     (int(first_col * PW), row_idx),
                     (int(last_col  * PW), row_idx),
                     (0, 50, 230), 1)

    for yi in range(0, PH, 4):
        t  = yi / PH
        lx = int((0.18 - 0.08 * t) * PW)
        rx = int((0.82 + 0.08 * t) * PW)
        cv2.line(panel_b, (lx, yi), (lx, yi), (200, 200, 0), 1)
        cv2.line(panel_b, (rx, yi), (rx, yi), (200, 200, 0), 1)

    # Panel C: DA2
    if depth is not None:
        d_clip   = np.clip(depth, 0.1, 10.0)
        d_norm   = cv2.normalize(d_clip, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        d_rs     = cv2.resize(d_norm, (PW, PH))
        panel_c  = cv2.applyColorMap(255 - d_rs, cv2.COLORMAP_TURBO)

        n_bands = 5
        band_h  = PH // n_bands
        d_rs_f  = cv2.resize(np.clip(depth, 0.1, 10.0).astype(np.float32),    
                             (PW, PH), interpolation=cv2.INTER_AREA)
        band_medians = []
        for bi in range(n_bands):
            y_s = bi * band_h
            y_e = y_s + band_h
            band_medians.append(float(np.median(d_rs_f[y_s:y_e, :])))

        band_colors = []
        for bi in range(n_bands):
            if bi == 0:
                band_colors.append((0, 200, 80))
            else:
                if band_medians[bi] <= band_medians[bi - 1]:
                    band_colors.append((0, 200, 80))
                else:
                    band_colors.append((0, 80, 220))

        for bi in range(n_bands):
            y_s = bi * band_h
            y_e = y_s + band_h
            cv2.rectangle(panel_c, (0, y_s), (PW - 1, y_e - 1), band_colors[bi], 1)
    else:
        panel_c = np.full((PH, PW, 3), 18, dtype=np.uint8)

    return panel_a, panel_b, panel_c
