# backend/rules_engine.py
# ------------------------------------------------------------
# Rule-driven Vedic engine: predicates + robust rule loader
# - JSON-only rules in /rulesets
# - Safe validation (bad files skipped, reported via /rules/reload)
# - Explainable signals with bool + strength
# ------------------------------------------------------------

import json
import os
from typing import Dict, Any, List, Tuple, Optional, Set

# ------------ Core tables ------------
SIGNS: List[str] = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]
SIGN_LORD: Dict[int, str] = {
    1: "Mars", 2: "Venus", 3: "Mercury", 4: "Moon", 5: "Sun", 6: "Mercury",
    7: "Venus", 8: "Mars", 9: "Jupiter", 10: "Saturn", 11: "Saturn", 12: "Jupiter"
}
EXALTATION: Dict[str, int]   = {"Sun": 1, "Moon": 2, "Mars": 10, "Mercury": 6, "Jupiter": 4, "Venus": 12, "Saturn": 7}
MOOLA: Dict[str, int]        = {"Sun": 5, "Moon": 2, "Mars": 1,  "Mercury": 6, "Jupiter": 9, "Venus": 7,  "Saturn": 11}
DEBILITATION: Dict[str, int] = {"Sun": 7, "Moon": 8, "Mars": 4, "Mercury": 12, "Jupiter": 10, "Venus": 6, "Saturn": 1}

# Natural karaka houses (from Asc)
KARAKA_HOUSES: Dict[str, List[int]] = {
    "Sun":     [1, 9, 10],
    "Moon":    [4],
    "Mars":    [3, 6],
    "Mercury": [3, 5, 10],
    "Jupiter": [2, 5, 9],
    "Venus":   [4, 7, 12],
    "Saturn":  [6, 8, 12],
}
HOUSE_GROUPS: Dict[str, List[int]] = {
    "kendra":   [1, 4, 7, 10],
    "trikona":  [1, 5, 9],
    "dusthana": [6, 8, 12],
    "upachaya": [3, 6, 10, 11],
}

# Sign-based special graha drishti (others: default 7th)
SPECIAL_SIGN_ASPECTS: Dict[str, Set[int]] = {
    "Mars":    {4, 7, 8},   # 4th, 7th, 8th
    "Jupiter": {5, 7, 9},   # 5th, 7th, 9th
    "Saturn":  {3, 7, 10},  # 3rd, 7th, 10th
}
# Degree-based angles for closeness scoring
ASPECT_ANGLES: Dict[str, List[float]] = {
    "Sun":     [180],
    "Moon":    [180],
    "Mercury": [180],
    "Venus":   [180],
    "Mars":    [90, 180, 240],
    "Jupiter": [120, 180, 240],
    "Saturn":  [60, 180, 300],
    "Rahu":    [180],
    "Ketu":    [180],
}

# ------------ tiny math/helpers ------------
def normalize(deg: float) -> float:
    return deg % 360.0

def degree_delta(a: float, b: float) -> float:
    """Signed forward arc from a → b (0..360)."""
    return (normalize(b) - normalize(a)) % 360.0

def abs_min_angle(a: float, b: float) -> float:
    """Smallest absolute angle between a and b (0..180)."""
    d = abs(a - b) % 360.0
    return d if d <= 180.0 else 360.0 - d

def asc_sign_num(chart: Dict[str, Any]) -> int:
    return int(chart["ascendant"]["sign_num"])

def planet_get(chart: Dict[str, Any], name: str) -> Dict[str, Any]:
    for p in chart["planets"]:
        if p["name"] == name:
            return p
    raise ValueError(f"Planet {name} not found")

def planet_sign_num(chart: Dict[str, Any], name: str) -> int:
    return int(planet_get(chart, name)["sign_num"])

def planet_lon(chart: Dict[str, Any], name: str) -> float:
    return float(planet_get(chart, name)["longitude"])

def lord_of_sign(sign_num: int) -> str:
    return SIGN_LORD[sign_num]

def owns_signs(planet_name: str) -> Set[int]:
    return {s for s, l in SIGN_LORD.items() if l == planet_name}

def karaka_places_for(planet_name: str) -> Set[int]:
    """Own signs + exaltation + moolatrikona (SIGN NUMBERS)."""
    s = set(owns_signs(planet_name))
    if planet_name in EXALTATION:
        s.add(EXALTATION[planet_name])
    if planet_name in MOOLA:
        s.add(MOOLA[planet_name])
    return s

def sign_distance(a: int, b: int) -> int:
    """Sign steps from a→b (1..12). 7 => opposition."""
    d = (b - a) % 12
    return 12 if d == 0 else d

def does_aspect_sign(planet_name: str, from_sign: int, to_sign: int) -> bool:
    """True if planet_name aspects to_sign from from_sign by sign-based rules."""
    allowed = SPECIAL_SIGN_ASPECTS.get(planet_name, {7})
    return sign_distance(from_sign, to_sign) in allowed

def aspects_deg(from_name: str, from_lon: float, to_lon: float, orb: float) -> Tuple[bool, float]:
    """
    Degree closeness to the planet's pattern (e.g., Saturn 60/180/300).
    Returns (within_orb, best_diff_deg).
    """
    delta = degree_delta(from_lon, to_lon)  # 0..360
    diffs = [abs_min_angle(delta, ang) for ang in ASPECT_ANGLES[from_name]]
    best = min(diffs)
    return (best <= orb), best

def signs_from_houses_whole(asc_num: int, houses: List[int]) -> List[int]:
    """Whole-sign: house 1 = asc sign; house n => asc+(n-1)."""
    return sorted([((asc_num - 1) + (h - 1)) % 12 + 1 for h in houses])

def sign_of_house_from_asc(chart: Dict[str, Any], house_num: int) -> int:
    asc = asc_sign_num(chart)
    return ((asc - 1) + (house_num - 1)) % 12 + 1

# ------------ token resolver ------------
def resolve_planet(chart: Dict[str, Any], token: str) -> str:
    """
    Supports tokens like 'Saturn' or 'lord(12th)'.
    'lord(n)' maps to the planetary lord of the sign in house n from Asc.
    """
    token = token.strip()
    if token.startswith("lord(") and token.endswith(")"):
        inside = token[5:-1].strip()  # e.g., '12th'
        house_num = int("".join(ch for ch in inside if ch.isdigit()))
        sign_num = sign_of_house_from_asc(chart, house_num)
        return lord_of_sign(sign_num)
    return token

# ---------- Benefic/Malefic helpers ----------
def is_moon_waxing(chart: Dict[str, Any]) -> bool:
    sun = planet_lon(chart, "Sun")
    moon = planet_lon(chart, "Moon")
    # waxing ≈ Moon ahead of Sun by 0..180°
    return degree_delta(sun, moon) < 180.0

def get_benefics(chart: Dict[str, Any], treat_mercury_benefic: bool = True) -> List[str]:
    ben: List[str] = ["Jupiter", "Venus"]
    if is_moon_waxing(chart):
        ben.append("Moon")
    if treat_mercury_benefic:
        ben.append("Mercury")
    return ben

def get_malefics(chart: Dict[str, Any], include_nodes: bool = True) -> List[str]:
    mal: List[str] = ["Sun", "Mars", "Saturn"]
    if not is_moon_waxing(chart):
        mal.append("Moon")
    if include_nodes:
        mal += ["Rahu", "Ketu"]
    return mal

def planets_aspect_sign(chart: Dict[str, Any], planets: List[str], target_sign: int) -> Tuple[bool, float]:
    """
    Sign-level aspect: any of planets aspect target_sign by graha drishti rules.
    Returns (bool, strength 0..1 by closeness in degrees for the best planet).
    """
    best_strength = 0.0
    hit = False
    # representative longitude in the target sign (midpoint)
    target_mid = (target_sign - 1) * 30 + 15.0
    for p in planets:
        p_sign = planet_sign_num(chart, p)
        p_lon  = planet_lon(chart, p)
        if does_aspect_sign(p, p_sign, target_sign):
            hit = True
            ok, diff = aspects_deg(p, p_lon, target_mid, 30.0)
            strength = max(0.0, 1.0 - (diff / 30.0))
            if strength > best_strength:
                best_strength = strength
    return hit, round(best_strength, 3)

def any_planet_in_sign(chart: Dict[str, Any], planets: List[str], target_sign: int) -> bool:
    return any(planet_sign_num(chart, p) == target_sign for p in planets)

# ---------- Yogakāraka helpers ----------
_YK_BY_ASC = {
    2: ["Saturn"],   # Taurus
    7: ["Saturn"],   # Libra
    4: ["Mars"],     # Cancer
    5: ["Mars"],     # Leo
    10: ["Venus"],   # Capricorn
    11: ["Venus"],   # Aquarius
}
def yogakaraka_planets(chart: Dict[str, Any]) -> List[str]:
    return _YK_BY_ASC.get(asc_sign_num(chart), [])

# ------------ predicates ------------
def pred_planet_in_karaka_houses_of(chart, params):
    # {"planet":"Saturn","of":"lord(12th)"}
    planet = resolve_planet(chart, params["planet"])
    of     = resolve_planet(chart, params["of"])
    target_houses = KARAKA_HOUSES.get(of, [])
    target_signs  = signs_from_houses_whole(asc_sign_num(chart), target_houses)
    ok = planet_sign_num(chart, planet) in set(target_signs)
    return {"bool": ok, "strength": 1.0 if ok else 0.0,
            "meta": {"target_houses": target_houses, "target_signs": target_signs}}

def pred_planet_in_karaka_places_of(chart, params):
    # {"planet":"Saturn","of":"lord(12th)"}
    planet = resolve_planet(chart, params["planet"])
    of     = resolve_planet(chart, params["of"])
    target_signs = sorted(list(karaka_places_for(of)))
    ok = planet_sign_num(chart, planet) in set(target_signs)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta": {"target_signs": target_signs}}

def pred_planet_in_signs(chart, params):
    # {"planet":"lord(12th)","signs":[10,11]}
    planet = resolve_planet(chart, params["planet"])
    signs  = set(params["signs"])
    ok = planet_sign_num(chart, planet) in signs
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta": {}}

def pred_mutual_aspect_hybrid(chart, params):
    # {"a":"Saturn","b":"lord(12th)","orb_deg":30}
    a = resolve_planet(chart, params["a"])
    b = resolve_planet(chart, params["b"])
    orb = float(params.get("orb_deg", 30.0))
    a_sign, b_sign = planet_sign_num(chart, a), planet_sign_num(chart, b)
    a_lon,  b_lon  = planet_lon(chart, a),      planet_lon(chart, b)

    sign_mut = does_aspect_sign(a, a_sign, b_sign) and does_aspect_sign(b, b_sign, a_sign)
    a_ok, a_diff = aspects_deg(a, a_lon, b_lon, orb)
    b_ok, b_diff = aspects_deg(b, b_lon, a_lon, orb)
    closeness = min(a_diff, b_diff)
    strength = max(0.0, 1.0 - (closeness / max(orb, 30.0)))
    return {"bool": sign_mut, "strength": round(strength, 3),
            "meta": {"deg_ok": (a_ok and b_ok), "angle_diff": round(closeness, 2)}}

def pred_conjunction(chart, params):
    # {"a":"lord(2)","b":"lord(9)","orb_deg":8}
    a = resolve_planet(chart, params["a"])
    b = resolve_planet(chart, params["b"])
    orb = float(params.get("orb_deg", 8.0))
    a_lon, b_lon = planet_lon(chart, a), planet_lon(chart, b)
    delta = abs_min_angle(a_lon, b_lon)  # 0..180
    ok = delta <= orb
    strength = max(0.0, 1.0 - (delta / max(orb, 1e-6)))
    return {"bool": ok, "strength": round(strength, 3), "meta": {"sep_deg": round(delta, 2)}}

def pred_any_connection(chart, params):
    """
    True if a and b are conjunct (within orb) OR in mutual aspect (sign-based),
    strength reflects the closer of the two mechanisms.
    """
    a = params["a"]; b = params["b"]; orb = float(params.get("orb_deg", 8.0))
    cj = pred_conjunction(chart, {"a": a, "b": b, "orb_deg": orb})
    ma = pred_mutual_aspect_hybrid(chart, {"a": a, "b": b, "orb_deg": max(orb, 15.0)})
    ok = cj["bool"] or ma["bool"]
    closeness = min(cj["meta"]["sep_deg"], ma["meta"]["angle_diff"])
    strength = max(cj["strength"], ma["strength"])
    return {"bool": ok, "strength": round(strength, 3), "meta": {"closest_deg": round(closeness, 2)}}

def pred_planet_in_house_group_from_asc(chart, params):
    # {"planet":"lord(6)","group":"dusthana"}
    planet = resolve_planet(chart, params["planet"])
    houses = HOUSE_GROUPS[params["group"]]
    target_signs = signs_from_houses_whole(asc_sign_num(chart), houses)
    ok = planet_sign_num(chart, planet) in set(target_signs)
    return {"bool": ok, "strength": 1.0 if ok else 0.0,
            "meta": {"houses": houses, "target_signs": target_signs}}

def pred_planet_in_house_from_asc(chart, params):
    # {"planet":"lord(6)","house":8}
    planet = resolve_planet(chart, params["planet"])
    house = int(params["house"])
    target_sign = sign_of_house_from_asc(chart, house)
    ok = planet_sign_num(chart, planet) == target_sign
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta": {"target_sign": target_sign}}

def pred_planet_in_own_sign(chart, params):
    # {"planet":"Venus"}
    planet = resolve_planet(chart, params["planet"])
    p_sign = planet_sign_num(chart, planet)
    ok = p_sign in owns_signs(planet)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta": {}}

def pred_planet_in_exaltation(chart, params):
    planet = resolve_planet(chart, params["planet"])
    ok = planet_sign_num(chart, planet) == EXALTATION.get(planet)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta": {}}

def pred_planet_debilitated(chart, params):
    planet = resolve_planet(chart, params["planet"])
    ok = planet_sign_num(chart, planet) == DEBILITATION.get(planet)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta": {}}

def pred_exaltation_lord_support(chart, params):
    # {"planet":"Venus","orb_deg":10}
    planet = resolve_planet(chart, params["planet"])
    ex_sign = EXALTATION[planet]
    ex_lord = SIGN_LORD[ex_sign]
    return pred_any_connection(chart, {"a": ex_lord, "b": planet, "orb_deg": params.get("orb_deg", 30)})

def pred_debilitation_lord_support(chart, params):
    # {"planet":"Venus","orb_deg":10}
    planet = resolve_planet(chart, params["planet"])
    d_sign = DEBILITATION[planet]
    d_lord = SIGN_LORD[d_sign]
    return pred_any_connection(chart, {"a": d_lord, "b": planet, "orb_deg": params.get("orb_deg", 30)})

def pred_lord_exchange(chart, params):
    # {"a":"lord(2)","b":"lord(11)"}
    a = resolve_planet(chart, params["a"])
    b = resolve_planet(chart, params["b"])
    a_sign = planet_sign_num(chart, a)
    b_sign = planet_sign_num(chart, b)
    ok = (SIGN_LORD[a_sign] == b) and (SIGN_LORD[b_sign] == a)
    return {"bool": ok, "strength": 1.0 if ok else 0.0,
            "meta": {"a_sign": a_sign, "b_sign": b_sign}}

def pred_kendra_from(chart, params):
    """
    Is planet A in a kendra (1/4/7/10) from planet B?
    Strength uses degree closeness to 0/90/180/270 from B's longitude.
    params: {"a":"Jupiter","b":"Moon","include_conjunction":true,"orb_deg":12}
    """
    a = resolve_planet(chart, params["a"])
    b = resolve_planet(chart, params["b"])
    include_conj = bool(params.get("include_conjunction", True))
    orb = float(params.get("orb_deg", 12.0))

    a_sign = planet_sign_num(chart, a)
    b_sign = planet_sign_num(chart, b)

    # +0, +3, +6, +9 signs from b_sign
    target = {((b_sign - 1) + k) % 12 + 1 for k in (0, 3, 6, 9)}
    ok_by_sign = a_sign in target

    # degree closeness to 0/90/180/270 from B
    a_lon = planet_lon(chart, a)
    b_lon = planet_lon(chart, b)
    delta = degree_delta(b_lon, a_lon)
    diffs = [abs_min_angle(delta, ang) for ang in (0.0, 90.0, 180.0, 270.0)]
    diff = min(diffs)
    strength = max(0.0, 1.0 - (diff / max(orb, 1e-6)))

    ok = ok_by_sign if include_conj else (ok_by_sign and a_sign != b_sign)
    return {"bool": ok, "strength": round(strength, 3),
            "meta": {"b_sign": b_sign, "target_signs": sorted(target), "angle_diff": round(diff, 2)}}

# ---- Yogakāraka predicates ----
def pred_any_yogakaraka(chart, params):
    yk = yogakaraka_planets(chart)
    return {"bool": bool(yk), "strength": 1.0 if yk else 0.0, "meta": {"yogakarakas": yk}}

def pred_yogakaraka_in_group_from_asc(chart, params):
    # {"group":"kendra"|"trikona"}
    yk = yogakaraka_planets(chart)
    if not yk:
        return {"bool": False, "strength": 0.0, "meta": {"yogakarakas": []}}
    houses = HOUSE_GROUPS[params["group"]]
    targets = set(signs_from_houses_whole(asc_sign_num(chart), houses))
    hits = [p for p in yk if planet_sign_num(chart, p) in targets]
    ok = bool(hits)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta": {"yogakarakas": yk, "hits": hits, "target_signs": sorted(targets)}}

def pred_yogakaraka_strong_place(chart, params):
    # own/exalt/moola for any yogakaraka
    yk = yogakaraka_planets(chart)
    hits = []
    for p in yk:
        s = planet_sign_num(chart, p)
        if s in owns_signs(p) or s == EXALTATION.get(p) or s == MOOLA.get(p):
            hits.append(p)
    ok = bool(hits)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta": {"hits": hits}}

# ---- Benefic/Malefic house predicates ----
def pred_benefics_occupy_house_from_asc(chart, params):
    # {"house": 10}
    house = int(params["house"])
    target_sign = sign_of_house_from_asc(chart, house)
    ben = get_benefics(chart)
    ok = any_planet_in_sign(chart, ben, target_sign)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta": {"benefics": ben, "target_sign": target_sign}}

def pred_benefics_aspect_house_from_asc(chart, params):
    house = int(params["house"])
    target_sign = sign_of_house_from_asc(chart, house)
    ben = get_benefics(chart)
    ok, strength = planets_aspect_sign(chart, ben, target_sign)
    return {"bool": ok, "strength": strength, "meta": {"benefics": ben, "target_sign": target_sign}}

def pred_malefics_occupy_house_from_asc(chart, params):
    house = int(params["house"])
    target_sign = sign_of_house_from_asc(chart, house)
    mal = get_malefics(chart)
    ok = any_planet_in_sign(chart, mal, target_sign)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta": {"malefics": mal, "target_sign": target_sign}}

def pred_malefics_aspect_house_from_asc(chart, params):
    house = int(params["house"])
    target_sign = sign_of_house_from_asc(chart, house)
    mal = get_malefics(chart)
    ok, strength = planets_aspect_sign(chart, mal, target_sign)
    return {"bool": ok, "strength": strength, "meta": {"malefics": mal, "target_sign": target_sign}}

# ---- Ashtakavarga (lite) predicate ----
def pred_sav_lite_threshold(chart, params):
    # {"house":10,"min":0.8}
    # lazy import to avoid circular import (ashtakavarga imports rules_engine helpers)
    from .ashtakavarga import house_score
    house = int(params["house"])
    threshold = float(params.get("min", 0.5))
    val = house_score(chart, house)
    ok = val >= threshold
    # map val (~ -2..+2) to 0..1 for strength: clamp
    strength = max(0.0, min(1.0, (val + 2.0) / 4.0))
    return {"bool": ok, "strength": round(strength, 3), "meta": {"value": round(val, 3), "threshold": threshold}}

# Registry of all predicates
PREDICATES: Dict[str, Any] = {
    "planet_in_karaka_houses_of":     pred_planet_in_karaka_houses_of,
    "planet_in_karaka_places_of":     pred_planet_in_karaka_places_of,
    "planet_in_signs":                pred_planet_in_signs,
    "mutual_aspect_hybrid":           pred_mutual_aspect_hybrid,
    "conjunction":                    pred_conjunction,
    "any_connection":                 pred_any_connection,
    "planet_in_house_group_from_asc": pred_planet_in_house_group_from_asc,
    "planet_in_house_from_asc":       pred_planet_in_house_from_asc,
    "planet_in_own_sign":             pred_planet_in_own_sign,
    "planet_in_exaltation":           pred_planet_in_exaltation,
    "planet_debilitated":             pred_planet_debilitated,
    "exaltation_lord_support":        pred_exaltation_lord_support,
    "debilitation_lord_support":      pred_debilitation_lord_support,
    "lord_exchange":                  pred_lord_exchange,
    "kendra_from":                    pred_kendra_from,

    "any_yogakaraka":                 pred_any_yogakaraka,
    "yogakaraka_in_group_from_asc":   pred_yogakaraka_in_group_from_asc,
    "yogakaraka_strong_place":        pred_yogakaraka_strong_place,

    "benefics_occupy_house_from_asc": pred_benefics_occupy_house_from_asc,
    "benefics_aspect_house_from_asc": pred_benefics_aspect_house_from_asc,
    "malefics_occupy_house_from_asc": pred_malefics_occupy_house_from_asc,
    "malefics_aspect_house_from_asc": pred_malefics_aspect_house_from_asc,

    "sav_lite_threshold":             pred_sav_lite_threshold,
}

# ------------ rules loader / evaluator ------------
RULES_CACHE: Dict[str, Dict[str, Any]] = {}
RULE_ERRORS: List[Dict[str, Any]] = []

def rules_dir() -> str:
    base = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(base, "rulesets")

_ALLOWED_STATUS_TOKENS = {"and", "or", "not", "True", "False", "(", ")"}

def _validate_status_expr(expr: Optional[str], signal_ids: Set[str]) -> Optional[str]:
    """Return None if ok, else an error string describing what’s wrong."""
    if expr is None:
        return None
    raw = expr.replace("(", " ( ").replace(")", " ) ").split()
    for tok in raw:
        if tok in _ALLOWED_STATUS_TOKENS:  # allowed keywords/parens
            continue
        if tok in {"true", "false"}:       # allow lowercase booleans
            continue
        if tok.isidentifier():             # signal ids
            if tok not in signal_ids:
                return f"Unknown identifier '{tok}' in status expression"
            continue
        return f"Illegal token '{tok}' in status expression"
    return None

def load_rules() -> Dict[str, Dict[str, Any]]:
    """Load all rule JSONs from /rulesets, skipping invalid ones and collecting RULE_ERRORS."""
    global RULE_ERRORS
    RULE_ERRORS = []
    out: Dict[str, Dict[str, Any]] = {}

    rd = rules_dir()
    if not os.path.isdir(rd):
        os.makedirs(rd, exist_ok=True)
        return out

    for fname in os.listdir(rd):
        if not fname.lower().endswith(".json"):
            continue

        path = os.path.join(rd, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception as ex:
            RULE_ERRORS.append({"file": fname, "error": f"JSON parse error: {ex}"})
            continue

        if not isinstance(obj, dict):
            RULE_ERRORS.append({"file": fname, "error": "Top-level JSON must be an object"})
            continue
        if obj.get("disabled") is True:
            RULE_ERRORS.append({"file": fname, "error": "Rule disabled via 'disabled': true (skipped)"})
            continue
        if "id" not in obj or "signals" not in obj:
            RULE_ERRORS.append({"file": fname, "error": "Missing 'id' or 'signals' at top level"})
            continue
        if not isinstance(obj["id"], str):
            RULE_ERRORS.append({"file": fname, "error": "'id' must be a string"})
            continue
        if not isinstance(obj["signals"], list) or not obj["signals"]:
            RULE_ERRORS.append({"file": fname, "error": "'signals' must be a non-empty list"})
            continue

        rid = obj["id"]
        if rid in out:
            RULE_ERRORS.append({"file": fname, "error": f"Duplicate rule id '{rid}' (already loaded)"})
            continue

        # validate signals
        seen_sig_ids: Set[str] = set()
        bad = False
        for sig in obj["signals"]:
            if not isinstance(sig, dict):
                RULE_ERRORS.append({"file": fname, "error": f"Signal item must be object: {sig!r}"})
                bad = True
                continue
            sid = sig.get("id"); pred = sig.get("predicate")
            if not sid or not isinstance(sid, str):
                RULE_ERRORS.append({"file": fname, "error": f"Signal missing/invalid 'id': {sig}"})
                bad = True; continue
            if sid in seen_sig_ids:
                RULE_ERRORS.append({"file": fname, "error": f"Duplicate signal id '{sid}'"})
                bad = True; continue
            if not pred or not isinstance(pred, str):
                RULE_ERRORS.append({"file": fname, "error": f"Signal '{sid}' missing/invalid 'predicate'"})
                bad = True; continue
            if pred not in PREDICATES:
                RULE_ERRORS.append({"file": fname, "error": f"Unknown predicate '{pred}' on signal '{sid}'"})
                bad = True; continue
            if "params" in sig and not isinstance(sig["params"], dict):
                RULE_ERRORS.append({"file": fname, "error": f"Signal '{sid}' params must be an object"})
                bad = True; continue
            seen_sig_ids.add(sid)

        # weights: if present, keys must be known signal ids, values numeric
        weights = obj.get("weights", {})
        if weights and not isinstance(weights, dict):
            RULE_ERRORS.append({"file": fname, "error": "'weights' must be an object"})
            bad = True
        else:
            for k in list(weights.keys()):
                if k not in seen_sig_ids:
                    RULE_ERRORS.append({"file": fname, "error": f"'weights' references unknown signal id '{k}'"})
                    bad = True
                else:
                    try:
                        weights[k] = float(weights[k])
                    except Exception:
                        RULE_ERRORS.append({"file": fname, "error": f"'weights.{k}' must be a number"})
                        bad = True

        # strength_weights: booleans for a subset of signal ids
        strength_weights = obj.get("strength_weights", {})
        if strength_weights:
            if not isinstance(strength_weights, dict):
                RULE_ERRORS.append({"file": fname, "error": "'strength_weights' must be an object"})
                bad = True
            else:
                for k, v in strength_weights.items():
                    if k not in seen_sig_ids:
                        RULE_ERRORS.append({"file": fname, "error": f"'strength_weights' references unknown signal id '{k}'"})
                        bad = True
                    if not isinstance(v, bool):
                        RULE_ERRORS.append({"file": fname, "error": f"'strength_weights.{k}' must be true/false"})
                        bad = True

        # status expressions
        for key in ("strong_if", "active_if"):
            if key in obj:
                if not isinstance(obj[key], str):
                    RULE_ERRORS.append({"file": fname, "error": f"'{key}' must be a string boolean expression"})
                    bad = True
                else:
                    err = _validate_status_expr(obj[key], seen_sig_ids)
                    if err:
                        RULE_ERRORS.append({"file": fname, "error": f"{key} invalid: {err}"})
                        bad = True

        if bad:
            continue

        # normalize orb (if provided)
        if "orb_deg" in obj:
            try:
                obj["orb_deg"] = float(obj["orb_deg"])
            except Exception:
                RULE_ERRORS.append({"file": fname, "error": "'orb_deg' must be a number"})
                continue

        out[rid] = obj

    return out

def reload_rules() -> Dict[str, Any]:
    """Reload into RULES_CACHE and return a summary including validation errors (non-fatal)."""
    global RULES_CACHE
    RULES_CACHE = load_rules()
    return {
        "count": len(RULES_CACHE),
        "ids": list(RULES_CACHE.keys()),
        "errors": RULE_ERRORS,
    }

def evaluate_rule(chart: Dict[str, Any], rule: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate a single rule:
    - Each signal yields {"bool": True/False, "strength": 0..1, "meta": {...}}
    - Score is weighted sum; can use strength if listed in strength_weights.
    - Status picked by strong_if / active_if boolean expressions (safe-eval).
    """
    weights: Dict[str, float] = rule.get("weights", {})
    strength_flags: Dict[str, bool] = rule.get("strength_weights", {})
    orb_def: float = float(rule.get("orb_deg", 30.0))

    signals_res: Dict[str, Dict[str, Any]] = {}
    explain: List[str] = []

    # compute signals
    for sig in rule["signals"]:
        sid = sig["id"]
        pred = sig["predicate"]
        params = dict(sig.get("params", {}))
        if "orb_deg" not in params:
            params["orb_deg"] = orb_def
        res = PREDICATES[pred](chart, params)
        signals_res[sid] = res
        explain.append(f"{sid}: {pred} -> {'YES' if res['bool'] else 'NO'} (strength={res['strength']:.3f})")

    # weighted score
    raw = 0.0
    wsum = 0.0
    for sid, w in weights.items():
        val = signals_res.get(sid, {"bool": False, "strength": 0.0})
        use_strength = strength_flags.get(sid, False)
        raw += float(w) * (val["strength"] if use_strength else (1.0 if val["bool"] else 0.0))
        wsum += float(w)
    score = (raw / wsum) if wsum > 0 else 0.0

    # status selection
    ctx = {k: v["bool"] for k, v in signals_res.items()}

    def _safe_eval(expr: str) -> bool:
        # Safe eval using only booleans and our context
        return eval(expr, {"_builtins_": {}}, {**ctx, "True": True, "False": False})

    strong_if = rule.get("strong_if")
    active_if = rule.get("active_if")
    if strong_if:
        status = "strong" if _safe_eval(strong_if) else ("active" if (active_if and _safe_eval(active_if)) or any(ctx.values()) else "inactive")
    else:
        status = "active" if any(ctx.values()) else "inactive"

    return {
        "id": rule["id"],
        "status": status,
        "score": round(score, 3),
        "signals": {k: {"bool": v["bool"], "strength": round(v["strength"], 3), **v.get("meta", {})}
                    for k, v in signals_res.items()},
        "weights": weights,
        "explain": explain,
    }

def evaluate_all(chart: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [evaluate_rule(chart, RULES_CACHE[rid]) for rid in RULES_CACHE]