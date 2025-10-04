# backend/ashtakavarga.py
from typing import Dict, Any, List
from .rules_engine import asc_sign_num, sign_of_house_from_asc, get_benefics, get_malefics, planets_aspect_sign, any_planet_in_sign, SIGNS

def sav_lite(chart: Dict[str, Any]) -> Dict[str, Any]:
    """Return simple SAV-like points (0..8-ish) per house from Asc:
    +1 if a benefic occupies the house
    +best_strength (0..1) if benefics aspect it
    -1 if a malefic occupies the house
    -best_strength if malefics aspect it
    """
    out = []
    for h in range(1, 13):
        s = sign_of_house_from_asc(chart, h)
        ben = get_benefics(chart); mal = get_malefics(chart)
        p = 0.0
        if any_planet_in_sign(chart, ben, s): p += 1.0
        ok_b, str_b = planets_aspect_sign(chart, ben, s)
        if ok_b: p += str_b
        if any_planet_in_sign(chart, mal, s): p -= 1.0
        ok_m, str_m = planets_aspect_sign(chart, mal, s)
        if ok_m: p -= str_m
        out.append({"house": h, "sign_num": s, "sign": SIGNS[s-1], "score": round(p, 3)})
    return {"asc_sign_num": asc_sign_num(chart), "houses": out}

def house_score(chart: Dict[str, Any], house: int) -> float:
    data = sav_lite(chart)
    for row in data["houses"]:
        if row["house"] == house:
            return float(row["score"])
    return 0.0