# backend/rules_engine.py
import json, os
from typing import Dict, Any, List, Tuple

# ------------ Core tables ------------
SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]
SIGN_LORD = {1:"Mars",2:"Venus",3:"Mercury",4:"Moon",5:"Sun",6:"Mercury",7:"Venus",8:"Mars",9:"Jupiter",10:"Saturn",11:"Saturn",12:"Jupiter"}
EXALTATION = {"Sun":1,"Moon":2,"Mars":10,"Mercury":6,"Jupiter":4,"Venus":12,"Saturn":7}
MOOLA      = {"Sun":5,"Moon":2,"Mars":1, "Mercury":6,"Jupiter":9,"Venus":7, "Saturn":11}
DEBILITATION = {"Sun":7,"Moon":8,"Mars":4,"Mercury":12,"Jupiter":10,"Venus":6,"Saturn":1}
KARAKA_HOUSES = {"Sun":[1,9,10],"Moon":[4],"Mars":[3,6],"Mercury":[3,5,10],"Jupiter":[2,5,9],"Venus":[4,7,12],"Saturn":[6,8,12]}
HOUSE_GROUPS = {"kendra":[1,4,7,10],"trikona":[1,5,9],"dusthana":[6,8,12],"upachaya":[3,6,10,11]}
SPECIAL_SIGN_ASPECTS = {"Mars":{4,7,8},"Jupiter":{5,7,9},"Saturn":{3,7,10}}  # others = 7th only
ASPECT_ANGLES = {
    "Sun":[180],"Moon":[180],"Mercury":[180],"Venus":[180],
    "Mars":[90,180,240],"Jupiter":[120,180,240],"Saturn":[60,180,300],
    "Rahu":[180],"Ketu":[180],
}

# ------------ tiny math/helpers ------------
def normalize(d: float) -> float: return d % 360.0
def degree_delta(a: float, b: float) -> float: return (normalize(b) - normalize(a)) % 360.0
def abs_min_angle(a: float, b: float) -> float:
    d = abs(a-b) % 360.0
    return d if d <= 180 else 360-d

def asc_sign_num(chart: Dict[str,Any]) -> int: return int(chart["ascendant"]["sign_num"])
def planet_get(chart: Dict[str,Any], name: str) -> Dict[str,Any]:
    for p in chart["planets"]:
        if p["name"] == name: return p
    raise ValueError(f"Planet {name} not found")
def planet_sign_num(chart: Dict[str,Any], name: str) -> int: return int(planet_get(chart,name)["sign_num"])
def planet_lon(chart: Dict[str,Any], name: str) -> float: return float(planet_get(chart,name)["longitude"])
def lord_of_sign(sign_num: int) -> str: return SIGN_LORD[sign_num]
def owns_signs(planet_name: str) -> set: return {s for s,l in SIGN_LORD.items() if l == planet_name}
def karaka_places_for(planet_name: str) -> set:
    s = set(owns_signs(planet_name))
    if planet_name in EXALTATION: s.add(EXALTATION[planet_name])
    if planet_name in MOOLA: s.add(MOOLA[planet_name])
    return s

def sign_distance(a: int, b: int) -> int:
    d = (b - a) % 12
    return 12 if d == 0 else d
def does_aspect_sign(planet_name: str, from_sign: int, to_sign: int) -> bool:
    return sign_distance(from_sign, to_sign) in SPECIAL_SIGN_ASPECTS.get(planet_name, {7})
def aspects_deg(from_name: str, from_lon: float, to_lon: float, orb: float) -> Tuple[bool,float]:
    delta = degree_delta(from_lon, to_lon)
    diffs = [abs_min_angle(delta,a) for a in ASPECT_ANGLES[from_name]]
    best = min(diffs)
    return (best <= orb), best
def signs_from_houses_whole(asc_num: int, houses: List[int]) -> List[int]:
    return sorted([((asc_num-1)+(h-1))%12 + 1 for h in houses])
def sign_of_house_from_asc(chart: Dict[str,Any], house_num: int) -> int:
    asc = asc_sign_num(chart)
    return ((asc - 1) + (house_num - 1)) % 12 + 1

# ------------ token resolver ------------
def resolve_planet(chart: Dict[str,Any], token: str) -> str:
    """Supports 'Saturn' or 'lord(12th)' etc."""
    token = token.strip()
    if token.startswith("lord(") and token.endswith(")"):
        inside = token[5:-1].strip()  # e.g., '12th'
        house_num = int(''.join(ch for ch in inside if ch.isdigit()))
        sign_num = sign_of_house_from_asc(chart, house_num)
        return lord_of_sign(sign_num)
    return token

# ------------ predicates ------------
def pred_planet_in_karaka_houses_of(chart, params):
    planet = resolve_planet(chart, params["planet"])
    of     = resolve_planet(chart, params["of"])
    target_houses = KARAKA_HOUSES.get(of, [])
    target_signs  = signs_from_houses_whole(asc_sign_num(chart), target_houses)
    ok = planet_sign_num(chart, planet) in set(target_signs)
    return {"bool": ok, "strength": 1.0 if ok else 0.0,
            "meta":{"target_houses":target_houses,"target_signs":target_signs}}

def pred_planet_in_karaka_places_of(chart, params):
    planet = resolve_planet(chart, params["planet"])
    of     = resolve_planet(chart, params["of"])
    target_signs = sorted(list(karaka_places_for(of)))
    ok = planet_sign_num(chart, planet) in set(target_signs)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta":{"target_signs":target_signs}}

def pred_planet_in_signs(chart, params):
    planet = resolve_planet(chart, params["planet"])
    signs  = set(params["signs"])
    ok = planet_sign_num(chart, planet) in signs
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta":{}}

def pred_mutual_aspect_hybrid(chart, params):
    a = resolve_planet(chart, params["a"]); b = resolve_planet(chart, params["b"])
    orb = float(params.get("orb_deg", 30.0))
    a_sign, b_sign = planet_sign_num(chart,a), planet_sign_num(chart,b)
    a_lon,  b_lon  = planet_lon(chart,a),  planet_lon(chart,b)
    sign_mut = does_aspect_sign(a, a_sign, b_sign) and does_aspect_sign(b, b_sign, a_sign)
    a_ok, a_diff = aspects_deg(a, a_lon, b_lon, orb)
    b_ok, b_diff = aspects_deg(b, b_lon, a_lon, orb)
    closeness = min(a_diff, b_diff)
    strength = max(0.0, 1.0 - (closeness / max(orb, 30.0)))
    return {"bool": sign_mut, "strength": round(strength,3), "meta":{"deg_ok": a_ok and b_ok, "angle_diff": round(closeness,2)}}

def pred_conjunction(chart, params):
    a = resolve_planet(chart, params["a"]); b = resolve_planet(chart, params["b"])
    orb = float(params.get("orb_deg", 8.0))
    a_lon, b_lon = planet_lon(chart,a), planet_lon(chart,b)
    delta = abs_min_angle(a_lon, b_lon)
    ok = delta <= orb
    strength = max(0.0, 1.0 - (delta / max(orb, 1e-6)))
    return {"bool": ok, "strength": round(strength,3), "meta":{"sep_deg": round(delta,2)}}

def pred_any_connection(chart, params):
    a = params["a"]; b = params["b"]; orb = float(params.get("orb_deg", 8.0))
    # conjunction or mutual aspect (hybrid)
    cj = pred_conjunction(chart, {"a":a,"b":b,"orb_deg":orb})
    ma = pred_mutual_aspect_hybrid(chart, {"a":a,"b":b,"orb_deg":max(orb,15.0)})
    ok = cj["bool"] or ma["bool"]
    closeness = min(cj["meta"]["sep_deg"], ma["meta"]["angle_diff"])
    strength = max(cj["strength"], ma["strength"])
    return {"bool": ok, "strength": round(strength,3), "meta":{"closest_deg": round(closeness,2)}}

def pred_planet_in_house_group_from_asc(chart, params):
    planet = resolve_planet(chart, params["planet"])
    houses = HOUSE_GROUPS[params["group"]]
    target_signs = signs_from_houses_whole(asc_sign_num(chart), houses)
    ok = planet_sign_num(chart, planet) in set(target_signs)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta":{"houses":houses,"target_signs":target_signs}}

def pred_planet_in_house_from_asc(chart, params):
    planet = resolve_planet(chart, params["planet"])
    house = int(params["house"])
    target_sign = sign_of_house_from_asc(chart, house)
    ok = planet_sign_num(chart, planet) == target_sign
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta":{"target_sign":target_sign}}

def pred_planet_in_own_sign(chart, params):
    planet = resolve_planet(chart, params["planet"])
    p_sign = planet_sign_num(chart, planet)
    ok = p_sign in owns_signs(planet)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta":{}}

def pred_planet_in_exaltation(chart, params):
    planet = resolve_planet(chart, params["planet"])
    ok = planet_sign_num(chart, planet) == EXALTATION.get(planet)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta":{}}

def pred_planet_debilitated(chart, params):
    planet = resolve_planet(chart, params["planet"])
    ok = planet_sign_num(chart, planet) == DEBILITATION.get(planet)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta":{}}

def pred_exaltation_lord_support(chart, params):
    planet = resolve_planet(chart, params["planet"])
    ex_sign = EXALTATION[planet]
    ex_lord = SIGN_LORD[ex_sign]
    return pred_any_connection(chart, {"a": ex_lord, "b": planet, "orb_deg": params.get("orb_deg", 30)})

def pred_debilitation_lord_support(chart, params):
    planet = resolve_planet(chart, params["planet"])
    d_sign = DEBILITATION[planet]
    d_lord = SIGN_LORD[d_sign]
    return pred_any_connection(chart, {"a": d_lord, "b": planet, "orb_deg": params.get("orb_deg", 30)})

def pred_lord_exchange(chart, params):
    a = resolve_planet(chart, params["a"]); b = resolve_planet(chart, params["b"])
    a_sign = planet_sign_num(chart, a); b_sign = planet_sign_num(chart, b)
    ok = (SIGN_LORD[a_sign] == b) and (SIGN_LORD[b_sign] == a)
    return {"bool": ok, "strength": 1.0 if ok else 0.0, "meta":{"a_sign":a_sign,"b_sign":b_sign}}

PREDICATES = {
    "planet_in_karaka_houses_of": pred_planet_in_karaka_houses_of,
    "planet_in_karaka_places_of": pred_planet_in_karaka_places_of,
    "planet_in_signs":            pred_planet_in_signs,
    "mutual_aspect_hybrid":       pred_mutual_aspect_hybrid,
    "conjunction":                pred_conjunction,
    "any_connection":             pred_any_connection,
    "planet_in_house_group_from_asc": pred_planet_in_house_group_from_asc,
    "planet_in_house_from_asc":   pred_planet_in_house_from_asc,
    "planet_in_own_sign":         pred_planet_in_own_sign,
    "planet_in_exaltation":       pred_planet_in_exaltation,
    "planet_debilitated":         pred_planet_debilitated,
    "exaltation_lord_support":    pred_exaltation_lord_support,
    "debilitation_lord_support":  pred_debilitation_lord_support,
    "lord_exchange":              pred_lord_exchange,
}

# ------------ rules loader / evaluator ------------
RULES_CACHE: Dict[str, Dict[str,Any]] = {}

def rules_dir() -> str:
    base = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(base, "rulesets")

def load_rules() -> Dict[str, Dict[str,Any]]:
    out = {}
    rd = rules_dir()
    if not os.path.isdir(rd): os.makedirs(rd, exist_ok=True)
    for fname in os.listdir(rd):
        if fname.endswith(".json"):
            path = os.path.join(rd, fname)
            with open(path, "r", encoding="utf-8") as f:
                rule = json.load(f)
                out[rule["id"]] = rule
    return out

def reload_rules() -> Dict[str,Any]:
    global RULES_CACHE
    RULES_CACHE = load_rules()
    return {"count": len(RULES_CACHE), "ids": list(RULES_CACHE.keys())}

def evaluate_rule(chart: Dict[str,Any], rule: Dict[str,Any]) -> Dict[str,Any]:
    weights = rule.get("weights", {})
    orb_def = float(rule.get("orb_deg", 30.0))
    signals_res = {}
    explain = []

    for sig in rule["signals"]:
        pid = sig["id"]
        pred = sig["predicate"]
        params = dict(sig.get("params", {}))
        if "orb_deg" not in params: params["orb_deg"] = orb_def
        res = PREDICATES[pred](chart, params)
        signals_res[pid] = res
        explain.append(f"{pid}: {pred} -> {'YES' if res['bool'] else 'NO'} (strength={res['strength']:.3f})")

    raw = 0.0; wsum = 0.0
    strength_flags = rule.get("strength_weights", {})
    for pid, w in weights.items():
        val = signals_res.get(pid, {"bool":False,"strength":0.0})
        use_strength = strength_flags.get(pid, False)
        raw += float(w) * (val["strength"] if use_strength else (1.0 if val["bool"] else 0.0))
        wsum += float(w)
    score = (raw/wsum) if wsum>0 else 0.0

    ctx = {k:v["bool"] for k,v in signals_res.items()}
    def eval_expr(expr: str) -> bool:
        allowed = {"and","or","not","True","False"}
        tokens = expr.replace("(", " ( ").replace(")", " ) ").split()
        for t in tokens:
            if t.isidentifier() and t not in allowed and t not in ctx:
                raise ValueError(f"Unknown token in rule status expr: {t}")
        return eval(expr, {"_builtins_": {}}, {**ctx, **{"True": True, "False": False}})

    strong_if = rule.get("strong_if")
    active_if = rule.get("active_if")
    if strong_if:
        status = "strong" if eval_expr(strong_if) else ("active" if (active_if and eval_expr(active_if)) or any(ctx.values()) else "inactive")
    else:
        status = "active" if any(ctx.values()) else "inactive"

    return {
        "id": rule["id"],
        "status": status,
        "score": round(score,3),
        "signals": {k: {"bool": v["bool"], "strength": round(v["strength"],3), **v.get("meta",{})} for k,v in signals_res.items()},
        "weights": weights,
        "explain": explain
    }

def evaluate_all(chart: Dict[str,Any]) -> List[Dict[str,Any]]:
    return [evaluate_rule(chart, RULES_CACHE[rid]) for rid in RULES_CACHE]