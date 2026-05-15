from __future__ import annotations

"""Lead scoring — additiv modell, vist score 0–100. Vekter lastes fra data/settings.json.

Råpoeng = sum av signalvekter (høyeste per type) + ev. kryss- og flere-ankere-tillegg.
**Vist score** = myk metning av råpoeng (lineær opp til ``score_softcap_knee``, deretter asymptotisk
mot 100) + eventuelle synergy-tillegg (også begrenset til 100 til sammen). Under knee-punktet er
råvektene på samme «poengskala» som totalsummen: ett svakt signal alene (f.eks. kommune = 6) gir
6/100, ikke 100 fordi leaden ikke har andre signaltyper. Over knee-punktet får ekstra råpoeng
avtagende uttelling, så 100 reserveres for de virkelig sterkeste leadene.

**Teoretisk maks-råpoeng** (``theoretical_max_raw_points``) brukes i innstillinger-UI som øvre referanse for sliderne.

Geo (uavhengig av forhåndsvalg): samme besøksadresse+postnr som anker veier tyngre enn kun samme postnr,
som veier tyngre enn samme kommune (justeres under thresholds: geo_postnr_addr_mult, geo_kommune_vs_postnr_cap;
standard tilsvarer de gamle konstantene).

I tillegg (standard): små faste «synergy»-tillegg når kryss (bransje+geo) og/eller flere ankere faktisk gir bonus.

score_breakdown lagrer **råpoeng** per signal/kryss/multi (ikke 0–100-skalerte deler), så UI matcher vekter.
"""
import json
from pathlib import Path

DATA = Path(__file__).parent / "data"
SETTINGS_FILE = DATA / "settings.json"

# Standardvekter (råpoeng). Vist score følger råsummen (maks 100) + synergy; teoretisk maks brukes i innstillinger-UI.
DEFAULT_WEIGHTS = {
    "felles_styreleder": 26,
    "felles_styremedlem": 18,
    "samme_bransje": 14,
    "nabobedrift_kommune": 8,
    "selskap_i_vekst": 8,
    "nabobedrift_postnummer": 12,
    "kunde_morselskap": 22,
    "kunde_konserntre": 18,
    "kunde_aksjeeierbok": 20,
    "combo_bransje_postnr": 18,
    "combo_bransje_kommune": 12,
    "multi_anchor_2": 10,
    "multi_anchor_3": 18,
}

DEFAULT_THRESHOLDS = {
    "small_anchor_threshold": 50,    # < N ansatte = "lite anker"
    "small_anchor_factor": 50,       # prosent av vekt for ikke-geo-signaler fra små ankere (50 = halvert)
    "min_lead_ansatte": 4,           # leads med færre ansatte filtreres bort (effektive ansatte = self + underenheter)
    "min_anchor_ansatte": 0,         # ankere (kunder) med færre effektive ansatte ekskluderes fra analyse — 0 = av
    "nabobedrift_postnr_distance_max_m": 8000,  # lineær nedskalering av postnr-signal: 0 m = full vekt, ≥ denne = 0
    # Geo-hierarki i score (adresse = postnr-vekt × mult; kommune begrenses mot sterkest postnr-nivå).
    "geo_postnr_addr_mult": 1.38,
    "geo_kommune_vs_postnr_cap": 0.88,
    # Aksjeeierbok / «kunde som aksjonær»: kun andeler i [min, max] % gir signal og vises i piller (standard 5–100).
    "kunde_aksjeeierbok_min_pct": 5.0,
    "kunde_aksjeeierbok_max_pct": 100.0,
    # Ekstra heltallspoeng (0–100-skala) lagt til etter skalering når bonus faktisk utløses.
    "score_boost_combo_points": 4,
    "score_boost_multi_points": 3,
    # Knee-punkt for myk metning av råpoeng: lineær under, asymptotisk mot 100 over.
    "score_softcap_knee": 70,
}


def _effective_thresholds(thresholds: dict | None) -> dict:
    return THRESHOLDS if thresholds is None else thresholds


def _effective_weights(weights: dict | None) -> dict:
    return SIGNAL_WEIGHTS if weights is None else weights


def ownership_signal_pct_bounds(thresholds: dict | None = None) -> tuple[float, float]:
    """Normalisert [min, max] for kunde_aksjeeierbok og tilhørende mor-andel i aksjeeierbok."""
    t = _effective_thresholds(thresholds)
    lo = float(t.get("kunde_aksjeeierbok_min_pct", 5.0) or 5.0)
    hi = float(t.get("kunde_aksjeeierbok_max_pct", 100.0) or 100.0)
    lo = max(0.0, min(100.0, lo))
    hi = max(0.0, min(100.0, hi))
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def load_settings():
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return {
                "weights": {**DEFAULT_WEIGHTS, **(data.get("weights") or {})},
                "thresholds": {**DEFAULT_THRESHOLDS, **(data.get("thresholds") or {})},
            }
        except Exception:
            pass
    return {"weights": dict(DEFAULT_WEIGHTS), "thresholds": dict(DEFAULT_THRESHOLDS)}


def save_settings(weights: dict = None, thresholds: dict = None):
    cur = load_settings()
    # None = felt utelatt i API-kallet; tom dict oppdaterer ingenting men er eksplisitt «ingen endring».
    if weights is not None:
        cur["weights"].update(weights)
    if thresholds is not None:
        cur["thresholds"].update(thresholds)
    t = cur["thresholds"]
    lo = float(t.get("kunde_aksjeeierbok_min_pct", 5.0) or 5.0)
    hi = float(t.get("kunde_aksjeeierbok_max_pct", 100.0) or 100.0)
    lo = max(0.0, min(100.0, lo))
    hi = max(0.0, min(100.0, hi))
    if lo > hi:
        lo, hi = hi, lo
    t["kunde_aksjeeierbok_min_pct"] = lo
    t["kunde_aksjeeierbok_max_pct"] = hi
    for bk in ("score_boost_combo_points", "score_boost_multi_points"):
        if bk in t:
            t[bk] = max(0, min(25, int(float(t[bk]) or 0)))
    if "score_softcap_knee" in t:
        try:
            knee = int(float(t["score_softcap_knee"]))
        except (TypeError, ValueError):
            knee = int(DEFAULT_THRESHOLDS["score_softcap_knee"])
        t["score_softcap_knee"] = max(30, min(100, knee))
    if "geo_postnr_addr_mult" in t:
        try:
            gm = float(t["geo_postnr_addr_mult"])
        except (TypeError, ValueError):
            gm = float(DEFAULT_THRESHOLDS["geo_postnr_addr_mult"])
        t["geo_postnr_addr_mult"] = max(1.0, min(2.5, gm))
    if "geo_kommune_vs_postnr_cap" in t:
        try:
            gc = float(t["geo_kommune_vs_postnr_cap"])
        except (TypeError, ValueError):
            gc = float(DEFAULT_THRESHOLDS["geo_kommune_vs_postnr_cap"])
        t["geo_kommune_vs_postnr_cap"] = max(0.25, min(1.0, gc))
    DATA.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    return cur


_current = load_settings()
SIGNAL_WEIGHTS = _current["weights"]
THRESHOLDS = _current["thresholds"]


def _reload():
    global SIGNAL_WEIGHTS, THRESHOLDS, _current
    _current = load_settings()
    SIGNAL_WEIGHTS = _current["weights"]
    THRESHOLDS = _current["thresholds"]


GEO_SIGNALS = {"nabobedrift_postnummer", "nabobedrift_kommune"}

# Geo-hierarki i score (uavhengig av forhåndsvalg): adresse > postnummer > kommune.
# «Adresse» = samme normaliserte besøksadresse + postnr som anker (se lead_geo.attach_postnummer_signal_geo_match_tiers).
# Faktiske verdier kommer fra THRESHOLDS (med disse som standard ved manglende nøkkel).
GEO_POSTNR_ADDR_MULT = 1.38
GEO_KOMMUNE_vs_POSTNR_CAP = 0.88  # når lead har begge typer og postnr-poeng > 0


def _geo_postnr_addr_mult(thresholds: dict | None = None) -> float:
    t = _effective_thresholds(thresholds)
    v = t.get("geo_postnr_addr_mult")
    if v is None:
        return float(GEO_POSTNR_ADDR_MULT)
    try:
        x = float(v)
    except (TypeError, ValueError):
        return float(GEO_POSTNR_ADDR_MULT)
    return max(1.0, min(2.5, x))


def _score_softcap_knee(thresholds: dict | None = None) -> int:
    t = _effective_thresholds(thresholds)
    v = t.get("score_softcap_knee")
    if v is None:
        return int(DEFAULT_THRESHOLDS["score_softcap_knee"])
    try:
        x = int(float(v))
    except (TypeError, ValueError):
        return int(DEFAULT_THRESHOLDS["score_softcap_knee"])
    return max(30, min(100, x))


def _soft_cap_raw(raw: float, knee: int) -> float:
    """Lineær opp til knee, asymptotisk mot 100 over. raw=knee+x → knee + (100-knee)·x/(x+(100-knee))."""
    if raw <= knee or knee >= 100:
        return max(0.0, raw)
    remaining = 100 - knee
    over = raw - knee
    return knee + remaining * over / (over + remaining)


def _geo_kommune_vs_postnr_cap(thresholds: dict | None = None) -> float:
    t = _effective_thresholds(thresholds)
    v = t.get("geo_kommune_vs_postnr_cap")
    if v is None:
        return float(GEO_KOMMUNE_vs_POSTNR_CAP)
    try:
        x = float(v)
    except (TypeError, ValueError):
        return float(GEO_KOMMUNE_vs_POSTNR_CAP)
    return max(0.25, min(1.0, x))

# Må matche signaltyper i frontend (SIGNAL_LABELS) for teoretisk maks / skalering.
_BASE_SIGNAL_WEIGHT_KEYS = (
    "felles_styreleder",
    "felles_styremedlem",
    "samme_bransje",
    "nabobedrift_kommune",
    "selskap_i_vekst",
    "nabobedrift_postnummer",
    "kunde_morselskap",
    "kunde_konserntre",
    "kunde_aksjeeierbok",
)


def _theoretical_weight_for_base_key(w: dict, key: str, thresholds: dict | None = None) -> float:
    """Teoretisk maks-råpoeng per basisnøkkel — speiler geo-hierarki (adresse/postnr/kommune)."""
    addr_m = _geo_postnr_addr_mult(thresholds)
    cap = _geo_kommune_vs_postnr_cap(thresholds)
    if key == "nabobedrift_postnummer":
        return float(w.get("nabobedrift_postnummer", 0) or 0) * addr_m
    if key == "nabobedrift_kommune":
        wk = float(w.get("nabobedrift_kommune", 0) or 0)
        wp = float(w.get("nabobedrift_postnummer", 0) or 0)
        if wp <= 0:
            return wk
        post_ceiling = wp * addr_m
        return min(wk, post_ceiling * cap)
    return float(w.get(key, 0) or 0)


def theoretical_max_raw_points(
    weights: dict | None = None, thresholds: dict | None = None
) -> float:
    """Øvre grense for råpoeng gitt gjeldende vekter (samme modell som innstillinger-UI)."""
    w = _effective_weights(weights)
    base = sum(_theoretical_weight_for_base_key(w, k, thresholds) for k in _BASE_SIGNAL_WEIGHT_KEYS)
    combo = max(
        float(w.get("combo_bransje_postnr", 0) or 0),
        float(w.get("combo_bransje_kommune", 0) or 0),
    )
    multi = max(
        float(w.get("multi_anchor_2", 0) or 0),
        float(w.get("multi_anchor_3", 0) or 0),
    )
    return base + combo + multi


def _include_signal_for_scoring(s: dict, thresholds: dict | None = None) -> bool:
    """Ignorer aksjonær-treff utenfor [min,max] % (innstilling). Manglende % telles med."""
    t = s.get("type")
    if t != "kunde_aksjeeierbok":
        return True
    opc = s.get("ownership_pct")
    if opc is None:
        return True
    lo, hi = ownership_signal_pct_bounds(thresholds)
    try:
        p = float(opc)
    except (TypeError, ValueError):
        return True
    return lo <= p <= hi


def score_lead(lead: dict, weights: dict | None = None, thresholds: dict | None = None) -> dict:
    """Base = sum av unike signaltyper.
    + Combo-bonus per lead (bransje + postnr/kommune).
    + Multi-anker-bonus (antall ankere med 2+ signaltyper).
    Vekt dempes for ikke-geografiske signaler fra små ankere (<50 ansatte).
    Vist score 0–100: råpoeng (avrundet) toppet ved 100, pluss synergy — ingen oppblåsing for «tynne» leads.

    ``weights`` / ``thresholds`` er valgfrie; ved ``None`` brukes globale ``SIGNAL_WEIGHTS`` / ``THRESHOLDS``."""
    wmap = _effective_weights(weights)
    thr = _effective_thresholds(thresholds)
    signals = [s for s in (lead.get("signals") or []) if _include_signal_for_scoring(s, thr)]

    # 1) Base — høyeste vekt per unike signaltype, med dempning for små ankere
    seen = {}
    for s in signals:
        t = s.get("type")
        if not t:
            continue
        w = wmap.get(t, 0)
        if t == "nabobedrift_postnummer":
            if s.get("geo_match_tier") == "adresse":
                w = int(round(w * _geo_postnr_addr_mult(thr)))
            gf = s.get("geo_distance_factor")
            if gf is not None:
                w = int(round(w * float(gf)))
        # Dempning: små ankere gir mindre uttelling for ikke-geografiske signaler
        ansatte = s.get("anker_ansatte") or 0
        threshold = thr.get("small_anchor_threshold", 50)
        factor_pct = thr.get("small_anchor_factor", 50)
        if ansatte and ansatte < threshold and t not in GEO_SIGNALS:
            w = int(w * factor_pct / 100)
        if t not in seen or seen[t] < w:
            seen[t] = w
    post_pts = int(seen.get("nabobedrift_postnummer") or 0)
    if "nabobedrift_kommune" in seen and post_pts > 0:
        cap = int(round(float(post_pts) * _geo_kommune_vs_postnr_cap(thr)))
        if seen["nabobedrift_kommune"] > cap:
            seen["nabobedrift_kommune"] = max(0, cap)
    base = sum(seen.values())

    # 2) Per-anker kombo-bonus: samme_bransje + (postnr eller kommune)
    by_anchor = {}
    for s in signals:
        a = s.get("anker_orgnr")
        if not a:
            continue
        by_anchor.setdefault(a, set()).add(s.get("type"))

    # Combo-bonus gis ÉN gang per lead (postnr-kombo vinner over kommune-kombo)
    has_combo_postnr = any(
        "samme_bransje" in t and "nabobedrift_postnummer" in t
        for t in by_anchor.values()
    )
    has_combo_kommune = any(
        "samme_bransje" in t and "nabobedrift_kommune" in t
        for t in by_anchor.values()
    )
    if has_combo_postnr:
        combo_bonus = wmap.get("combo_bransje_postnr", 18)
    elif has_combo_kommune:
        combo_bonus = wmap.get("combo_bransje_kommune", 12)
    else:
        combo_bonus = 0

    # 3) Multi-anker bonus: antall ankere med 2+ unike signaltyper
    multi_count = sum(1 for types in by_anchor.values() if len(types) >= 2)
    if multi_count >= 3:
        multi_bonus = wmap.get("multi_anchor_3", 18)
    elif multi_count >= 2:
        multi_bonus = wmap.get("multi_anchor_2", 10)
    else:
        multi_bonus = 0

    raw = float(base + combo_bonus + multi_bonus)
    base_score = min(100, int(round(_soft_cap_raw(raw, _score_softcap_knee(thr)))))

    # score_breakdown = råpoeng per del (samme som i «vekter»-modellen).
    breakdown = {k: int(v) for k, v in seen.items()}
    if combo_bonus:
        breakdown["combo_bonus"] = int(combo_bonus)
        breakdown["combo_kind"] = "postnr" if has_combo_postnr else "kommune"
    if multi_bonus:
        breakdown["multi_anchor_bonus"] = int(multi_bonus)
    synergy = 0
    if combo_bonus:
        synergy += int(thr.get("score_boost_combo_points", 4) or 0)
    if multi_bonus:
        synergy += int(thr.get("score_boost_multi_points", 3) or 0)
    if synergy:
        lead["score"] = min(100, base_score + synergy)
        breakdown["synergy_boost"] = synergy
    else:
        lead["score"] = base_score
    lead["score_breakdown"] = breakdown
    lead["multi_anchor_count"] = multi_count
    return lead
