# backend/predictor.py
from typing import List, Dict, Any, Set, Tuple
from datetime import date as _date



# reuse static summaries
def pick_top_rules(evals: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
    status_rank = {"strong": 2, "active": 1, "inactive": 0}
    ranked = sorted(
        evals,
        key=lambda r: (r.get("score", 0.0), status_rank.get(r.get("status","inactive"),0)),
        reverse=True
    )
    return ranked[:top_n]

def summarize(evals: List[Dict[str, Any]], top_n: int = 5) -> Dict[str, Any]:
    top = pick_top_rules(evals, top_n=top_n)
    lines = [f"{r['id'].replace('_',' ')}: {r['status']} (score {r['score']:.2f})" for r in top]
    strengths = [r["id"] for r in top if r["status"] == "strong"]
    actives   = [r["id"] for r in top if r["status"] == "active"]
    cautions  = [r["id"] for r in top if "debil" in r["id"] and r["status"] != "strong"]
    return {"top_rules": top, "summary_lines": lines,
            "highlights": {"strong": strengths, "active": actives, "cautions": cautions}}

# -------------------- TIME-AWARE --------------------
from .rules_engine import (
    asc_sign_num, SIGN_LORD, SIGNS,
    does_aspect_sign, aspects_deg, planet_lon, planet_sign_num,
    sign_of_house_from_asc
)
from .transits import aspects_to_natal, calc_transit_positions

def _infer_categories(rule_id: str) -> Set[str]:
    rid = rule_id.lower()
    cats: Set[str] = set()
    if any(k in rid for k in ["career_", "rajayoga", "yogakaraka"]):
        cats.add("career")
    if any(k in rid for k in ["dhana", "fortune", "l9"]):
        cats.add("wealth")
    if not cats:
        cats.add("general")
    return cats

def _aspect_strength_to_sign(planet_name: str, p_lon: float, p_sign: int, target_sign: int) -> float:
    """0..1 strength if planet aspects the target SIGN (sign-aspect + degree closeness to sign midpoint)."""
    if not does_aspect_sign(planet_name, p_sign, target_sign):
        return 0.0
    target_mid = (target_sign - 1) * 30 + 15.0
    _ok, diff = aspects_deg(planet_name, p_lon, target_mid, 30.0)
    return max(0.0, 1.0 - diff/30.0)

def _time_boosts(natal: Dict[str, Any], when_date: str, when_time: str, when_tz: float,
                 ayanamsha: str, orb_deg: float) -> Dict[str, Any]:
    """Compute small global/category boosts based on a few practical transit heuristics."""
    asc = asc_sign_num(natal)
    asc_lord = SIGN_LORD[asc]
    # key house signs
    h9  = sign_of_house_from_asc(natal, 9)
    h10 = sign_of_house_from_asc(natal, 10)
    h11 = sign_of_house_from_asc(natal, 11)

    # transit positions
    trans = calc_transit_positions(when_date, when_time, when_tz, ayanamsha)
    tmap = {t["name"]: t for t in trans}

    # helpers
    def get(name: str) -> Tuple[float,int]:
        t = tmap.get(name)
        return (float(t["longitude"]), int(t["sign_num"])) if t else (0.0, 0)

    j_lon, j_sign = get("Jupiter")
    v_lon, v_sign = get("Venus")
    s_lon, s_sign = get("Saturn")
    m_lon, m_sign = get("Mars")
    r_lon, r_sign = get("Rahu")
    k_lon, k_sign = get("Ketu")

    # positives: Jupiter to 9/10/11; Venus to 10th
    j_to_10 = max(
        1.0 if j_sign == h10 else 0.0,
        _aspect_strength_to_sign("Jupiter", j_lon, j_sign, h10)
    )
    j_to_9  = max(1.0 if j_sign == h9  else 0.0, _aspect_strength_to_sign("Jupiter", j_lon, j_sign, h9))
    j_to_11 = max(1.0 if j_sign == h11 else 0.0, _aspect_strength_to_sign("Jupiter", j_lon, j_sign, h11))
    v_to_10 = max(
        1.0 if v_sign == h10 else 0.0,
        _aspect_strength_to_sign("Venus", v_lon, v_sign, h10)
    )

    # negatives from transit→natal hits (Saturn/Mars/Nodes to Moon or Asc lord)
    hits = aspects_to_natal(natal, when_date, when_time, when_tz, ayanamsha, orb_deg)["hits"]

    def _max_strength(transit_name: str, natal_targets: Set[str]) -> float:
        cand = [h["strength"] for h in hits if h["transit"]["name"] == transit_name and h["natal"]["name"] in natal_targets]
        return max(cand) if cand else 0.0

    saturn_hard = _max_strength("Saturn", { "Moon", asc_lord })
    mars_hard   = _max_strength("Mars",   { "Moon", asc_lord, SIGN_LORD[h10] })
    nodes_hard  = max(
        _max_strength("Rahu", {"Sun","Moon"}),
        _max_strength("Ketu", {"Sun","Moon"})
    )

    # convert to small boosts/penalties
    # tuneable; values are conservative so scores stay 0..1 after clamping
    boost_career  = +0.10*j_to_10 + 0.05*v_to_10 - 0.10*saturn_hard - 0.08*mars_hard
    boost_wealth  = +0.06*j_to_9 + 0.06*j_to_11 - 0.06*nodes_hard
    boost_general = +0.04*j_to_10 + 0.03*j_to_9 + 0.03*j_to_11 - 0.03*saturn_hard

    # global (soft) hint if needed elsewhere
    global_hint  = 0.5*boost_career + 0.5*boost_wealth

    notes = []
    if j_to_10 > 0.4: notes.append("Transit Jupiter favorably influences career (10th).")
    if j_to_9  > 0.4: notes.append("Transit Jupiter supports dharma/fortune (9th).")
    if j_to_11 > 0.4: notes.append("Transit Jupiter supports gains/network (11th).")
    if v_to_10 > 0.4: notes.append("Transit Venus adds polish to career (10th).")
    if saturn_hard > 0.4: notes.append("Transit Saturn is pressing Moon/Asc-lord — pace yourself.")
    if mars_hard   > 0.4: notes.append("Transit Mars is edgy to Moon/Asc/10L — avoid impulsive moves.")
    if nodes_hard  > 0.4: notes.append("Nodes are tight to luminaries — keep clarity.")

    return {
        "boosts": {
            "career":  round(max(-0.25, min(0.25, boost_career)), 3),
            "wealth":  round(max(-0.25, min(0.25, boost_wealth)), 3),
            "general": round(max(-0.25, min(0.25, boost_general)), 3),
            "global":  round(max(-0.25, min(0.25, global_hint)), 3),
        },
        "notes": notes,
        "context": {
            "asc_sign": SIGNS[asc-1],
            "asc_lord": asc_lord,
            "houses": {"9": h9, "10": h10, "11": h11}
        }
    }

def summarize_timeaware(evals: List[Dict[str, Any]],
                        natal: Dict[str, Any],
                        when_date: str, when_time: str, when_tz: float,
                        ayanamsha: str, orb_deg: float = 6.0,
                        top_n: int = 5) -> Dict[str, Any]:
    """
    Adjust each rule's score with small transit-based boosts/penalties.
    """
    tb = _time_boosts(natal, when_date, when_time, when_tz, ayanamsha, orb_deg)
    b = tb["boosts"]
    adjusted = []
    for r in evals:
        cats = _infer_categories(r["id"])
        delta = b["general"]
        if "career" in cats: delta += b["career"]
        if "wealth" in cats: delta += b["wealth"]
        new_score = max(0.0, min(1.0, r.get("score", 0.0) + delta))
        adjusted.append({
            "id": r["id"], "base_score": r.get("score", 0.0),
            "adjusted_score": round(new_score, 3),
            "status": r.get("status","inactive"),
            "categories": sorted(list(cats))
        })

    # rank by adjusted score
    top = sorted(adjusted, key=lambda x: x["adjusted_score"], reverse=True)[:top_n]
    lines = [f"{t['id'].replace('_',' ')}: adj {t['adjusted_score']:.2f} (base {t['base_score']:.2f})" for t in top]

    return {
        "time_boosts": tb,
        "ranked": adjusted,
        "top_rules": top,
        "summary_lines": lines
    }

