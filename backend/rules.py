# backend/rules.py
from typing import Dict, Any, List, Set, Tuple
import json, os

SIGNS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]
SIGN_LORD = {
    1: "Mars", 2: "Venus", 3: "Mercury", 4: "Moon", 5: "Sun", 6: "Mercury",
    7: "Venus", 8: "Mars", 9: "Jupiter", 10: "Saturn", 11: "Saturn", 12: "Jupiter"
}
SATURN_SIGNS = {10, 11}  # Capricorn, Aquarius

# Natural karaka houses (from Asc) for each graha
KARAKA_HOUSES = {
    "Sun":     [1, 9, 10],
    "Moon":    [4],
    "Mars":    [3, 6],
    "Mercury": [3, 5, 10],
    "Jupiter": [2, 5, 9],
    "Venus":   [4, 7, 12],
    "Saturn":  [6, 8, 12]
}

# Exaltation & Moolatrikona (SIGN NUMBERS)
EXALTATION = { "Sun":1, "Moon":2, "Mars":10, "Mercury":6, "Jupiter":4, "Venus":12, "Saturn":7 }
MOOLA      = { "Sun":5, "Moon":2, "Mars":1,  "Mercury":6, "Jupiter":9, "Venus":7,  "Saturn":11 }

# Graha drishti angles (degree model)
ASPECT_ANGLES = {
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

def normalize(deg: float) -> float: return deg % 360.0
def degree_delta(from_deg: float, to_deg: float) -> float: return (normalize(to_deg) - normalize(from_deg)) % 360.0
def abs_min_angle(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return d if d <= 180.0 else 360.0 - d

def planet_get(chart: Dict[str, Any], name: str) -> Dict[str, Any]:
    for p in chart["planets"]:
        if p["name"] == name: return p
    raise ValueError(f"Planet {name} not found.")

def planet_sign_num(chart: Dict[str, Any], name: str) -> int: return int(planet_get(chart, name)["sign_num"])
def asc_sign_num(chart: Dict[str, Any]) -> int: return int(chart["ascendant"]["sign_num"])
def lord_of_sign(sign_num: int) -> str: return SIGN_LORD[sign_num]
def owns_signs(planet_name: str) -> Set[int]: return {s for s, lord in SIGN_LORD.items() if lord == planet_name}

def karaka_places_for(planet_name: str) -> Set[int]:
    s = set(owns_signs(planet_name))
    if planet_name in EXALTATION: s.add(EXALTATION[planet_name])
    if planet_name in MOOLA:      s.add(MOOLA[planet_name])
    return s

# ---------- Aspect helpers ----------
def sign_distance(a: int, b: int) -> int:
    d = (b - a) % 12
    return 12 if d == 0 else d

SPECIAL_SIGN_ASPECTS = {
    "Mars":    {4,7,8},
    "Jupiter": {5,7,9},
    "Saturn":  {3,7,10},
}
def does_aspect_sign(planet_name: str, from_sign: int, to_sign: int) -> bool:
    allowed = SPECIAL_SIGN_ASPECTS.get(planet_name, {7})
    return sign_distance(from_sign, to_sign) in allowed

def aspects_deg(from_name: str, from_lon: float, to_lon: float, orb: float) -> Tuple[bool, float]:
    delta = degree_delta(from_lon, to_lon)  # 0..360
    diffs = [abs_min_angle(delta, ang) for ang in ASPECT_ANGLES[from_name]]
    best = min(diffs)
    return (best <= orb), best

def mutual_aspect_hybrid(a_name: str, a_lon: float, a_sign: int, b_name: str, b_lon: float, b_sign: int, orb: float):
    # Boolean by sign-aspect; strength by degree closeness
    sign_a = does_aspect_sign(a_name, a_sign, b_sign)
    sign_b = does_aspect_sign(b_name, b_sign, a_sign)
    sign_mutual = sign_a and sign_b

    deg_a_ok, a_diff = aspects_deg(a_name, a_lon, b_lon, orb)
    deg_b_ok, b_diff = aspects_deg(b_name, b_lon, a_lon, orb)
    deg_ok = deg_a_ok and deg_b_ok
    # strength 0..1 within orb 30: closer = stronger
    max_orb = max(orb, 1e-6)
    strength = max(0.0, 1.0 - (min(a_diff, b_diff) / max_orb))
    return sign_mutual, deg_ok, round(min(a_diff, b_diff), 2), round(strength, 3)

def load_weights() -> Dict[str, float]:
    path = os.path.join("rulesets", "weights_saturn12th.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "saturn_in_l12_karaka_houses": 0.65,
        "saturn_in_l12_karaka_places": 0.15,
        "l12_in_saturn_signs": 0.25,
        "mutual_aspect_deg": 0.60,
        "orb_deg": 30.0
    }
WEIGHTS = load_weights()

def signs_from_houses_whole(asc_num: int, houses: List[int]) -> List[int]:
    return sorted([((asc_num - 1) + (h - 1)) % 12 + 1 for h in houses])

def evaluate_saturn_12th_rule(chart: Dict[str, Any]) -> Dict[str, Any]:
    asc_num = asc_sign_num(chart)
    sign_12th = (asc_num - 2) % 12 + 1
    l12_name = lord_of_sign(sign_12th)

    sat = planet_get(chart, "Saturn")
    l12 = planet_get(chart, l12_name)
    sat_sign, sat_lon = int(sat["sign_num"]), float(sat["longitude"])
    l12_sign, l12_lon = int(l12["sign_num"]), float(l12["longitude"])

    # A_house: Saturn in L12's NATURAL KARAKA houses (from Asc → target signs)
    l12_k_houses = KARAKA_HOUSES.get(l12_name, [])
    target_signs = signs_from_houses_whole(asc_num, l12_k_houses)
    cond_A_house = sat_sign in set(target_signs)

    # A_place: Saturn in L12 karaka PLACES (own+exalt+moola)
    l12_karaka_places = sorted(list(karaka_places_for(l12_name)))
    cond_A_place = sat_sign in set(l12_karaka_places)

    # B) L12 in Saturn signs
    cond_B = l12_sign in SATURN_SIGNS

    # C) Mutual aspect — HYBRID
    orb = float(WEIGHTS.get("orb_deg", 30.0))
    c_sign, c_deg, angle_diff, c_strength = mutual_aspect_hybrid(
        "Saturn", sat_lon, sat_sign, l12_name, l12_lon, l12_sign, orb
    )
    # For boolean signal we accept SIGN logic as truth
    cond_C_bool = c_sign
    # For scoring we use strength (0..1) within orb
    wC = float(WEIGHTS.get("mutual_aspect_deg", 0.60))
    part_C = wC * c_strength

    # Weighted score (others remain boolean 0/1)
    wAH = float(WEIGHTS.get("saturn_in_l12_karaka_houses", 0.65))
    wAP = float(WEIGHTS.get("saturn_in_l12_karaka_places", 0.15))
    wB  = float(WEIGHTS.get("l12_in_saturn_signs", 0.25))
    wsum = wAH + wAP + wB + wC

    raw = (
        wAH * (1 if cond_A_house else 0) +
        wAP * (1 if cond_A_place else 0) +
        wB  * (1 if cond_B else 0) +
        part_C                           # uses strength, not 0/1
    )
    score = raw / wsum if wsum > 0 else 0.0

    # Status tiers
    if cond_C_bool and (cond_A_house or cond_B or cond_A_place):
        status = "strong"
    elif cond_A_house or cond_B or cond_A_place or cond_C_bool:
        status = "active"
    else:
        status = "inactive"

    explain = [
        f"Asc = {chart['ascendant']['sign']} ({asc_num}); 12th sign = {SIGNS[sign_12th-1]} → L12 = {l12_name}.",
        f"Saturn: {SIGNS[sat_sign-1]} @ {sat_lon:.2f}°,  L12({l12_name}): {SIGNS[l12_sign-1]} @ {l12_lon:.2f}°.",
        f"A_house) L12 karaka houses {l12_k_houses} ⇒ target signs from Asc {target_signs} → {'YES' if cond_A_house else 'NO'}",
        f"A_place) L12 karaka places (own+exalt+moola) {l12_karaka_places} → {'YES' if cond_A_place else 'NO'}",
        f"B) L12 in Saturn signs {{10,11}} → {'YES' if cond_B else 'NO'}",
        f"C) Mutual aspect → SIGN: {'YES' if c_sign else 'NO'}, DEG within ±{orb}°: {'YES' if c_deg else 'NO'}, angle diff ≈ {angle_diff}°, strength={c_strength:.3f}",
        f"Weighted score = {score:.3f} (wAH={wAH}, wAP={wAP}, wB={wB}, wC={wC})."
    ]

    return {
        "id": "grand_success_saturn_12th",
        "status": status,
        "score": round(score, 3),
        "signals": {
            "saturn_in_l12_karaka_houses": cond_A_house,
            "saturn_in_l12_karaka_places": cond_A_place,
            "l12_in_saturn_signs": cond_B,
            "mutual_aspect_sign": c_sign,
            "mutual_aspect_deg": c_deg
        },
        "context": {
            "asc_sign_num": asc_num,
            "twelfth_sign_num": sign_12th,
            "l12_name": l12_name,
            "saturn_sign_num": sat_sign,
            "l12_sign_num": l12_sign,
            "l12_karaka_houses": l12_k_houses,
            "target_signs_from_asc": target_signs,
            "l12_karaka_places": l12_karaka_places,
            "orb_deg": orb,
            "mutual_angle_diff": angle_diff,
            "mutual_strength": c_strength
        },
        "explain": explain
    }

