# backend/transits.py
from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta
import math
import swisseph as swe
from datetime import date as _date

from .rules_engine import (
    SIGNS, ASPECT_ANGLES, does_aspect_sign, aspects_deg,
    planet_sign_num, planet_lon, asc_sign_num, SIGN_LORD   # <-- add this
)



PLANETS = ["Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn","Rahu","Ketu"]

def _jd_ut_from_local(date_str: str, time_str: str, tz_hours: float) -> float:
    # "YYYY-MM-DD", "HH:MM", tz like 5.5
    dt_local = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    dt_utc = dt_local - timedelta(hours=tz_hours)
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day,
                      dt_utc.hour + dt_utc.minute/60.0)

def _sign_num_from_lon(lon: float) -> int:
    # 0..360 → 1..12
    return int(math.floor(lon % 360.0) // 30) + 1

def _calc6(jd_ut: float, body_id: int, flags: int) -> Tuple[float,float,float,float,float,float]:
    """Robust calc: always return 6 floats (lon, lat, dist, lon_spd, lat_spd, dist_spd)."""
    res = swe.calc_ut(jd_ut, body_id, flags | swe.FLG_SPEED)
    # pyswisseph usually returns (xx, retflag)
    if isinstance(res, tuple) and len(res) == 2:
        xx, _retflag = res
    else:
        xx = res
    # xx is list-like of 3 or 6 floats
    lon = float(xx[0]); lat = float(xx[1]); dist = float(xx[2])
    lon_spd = float(xx[3]) if len(xx) > 3 else 0.0
    lat_spd = float(xx[4]) if len(xx) > 4 else 0.0
    dist_spd = float(xx[5]) if len(xx) > 5 else 0.0
    return lon, lat, dist, lon_spd, lat_spd, dist_spd

def calc_transit_positions(date_str: str, time_str: str, tz_hours: float, ayanamsha: str) -> List[Dict[str, Any]]:
    jd_ut = _jd_ut_from_local(date_str, time_str, tz_hours)
    ayan_id = getattr(swe, f"SIDM_{ayanamsha.upper()}", swe.SIDM_LAHIRI)
    swe.set_sid_mode(ayan_id, 0, 0)
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED

    out = []
    # Rahu = mean node; Ketu = opposite
    for name in PLANETS:
        if name == "Rahu":
            lon, lat, dist, lon_spd, lat_spd, dist_spd = _calc6(jd_ut, swe.MEAN_NODE, flags)
        elif name == "Ketu":
            r_lon, r_lat, r_dist, r_lon_spd, r_lat_spd, r_dist_spd = _calc6(jd_ut, swe.MEAN_NODE, flags)
            lon = (r_lon + 180.0) % 360.0
            lat = -r_lat
            dist = r_dist
            # speed: same magnitude as Rahu, direction mirrored in longitude is fine
            lon_spd = r_lon_spd
            lat_spd = -r_lat_spd
            dist_spd = r_dist_spd
        else:
            body_id = getattr(swe, name.upper())
            lon, lat, dist, lon_spd, lat_spd, dist_spd = _calc6(jd_ut, body_id, flags)

        out.append({
            "name": name,
            "longitude": lon,
            "sign_num": _sign_num_from_lon(lon),
            "speed": lon_spd
        })
    return out

def aspects_to_natal(natal: Dict[str, Any],
                     when_date: str, when_time: str, when_tz: float,
                     ayanamsha: str = "Lahiri",
                     orb_deg: float = 6.0) -> Dict[str, Any]:
    """
    Compute transiting→natal aspects (mutual by sign; degree closeness).
    """
    transits = calc_transit_positions(when_date, when_time, when_tz, ayanamsha)
    asc_num = asc_sign_num(natal)

    natal_planets = [p for p in natal["planets"]]  # include nodes; degree model still fine

    hits: List[Dict[str, Any]] = []
    for t in transits:
        t_name, t_lon, t_sign = t["name"], float(t["longitude"]), int(t["sign_num"])
        for n in natal_planets:
            n_name, n_lon, n_sign = n["name"], float(n["longitude"]), int(n["sign_num"])

            sign_ok = does_aspect_sign(t_name, t_sign, n_sign) and does_aspect_sign(n_name, n_sign, t_sign)

            t_ok, t_diff = aspects_deg(t_name, t_lon, n_lon, orb_deg)
            n_ok, n_diff = aspects_deg(n_name, n_lon, t_lon, orb_deg)
            diff = min(t_diff, n_diff)
            strength = max(0.0, 1.0 - (diff / max(orb_deg, 1e-6)))

            if sign_ok:
                hits.append({
                    "transit": {"name": t_name, "sign_num": t_sign, "sign": SIGNS[t_sign-1], "lon": round(t_lon, 2)},
                    "natal":   {"name": n_name, "sign_num": n_sign, "sign": SIGNS[n_sign-1], "lon": round(n_lon, 2)},
                    "deg_ok": bool(t_ok and n_ok),
                    "angle_diff": round(diff, 2),
                    "strength": round(strength, 3)
                })

    hits.sort(key=lambda x: x["strength"], reverse=True)
    return {
        "when": {"date": when_date, "time": when_time, "tz": when_tz, "ayanamsha": ayanamsha},
        "asc_sign_num": asc_num,
        "transits": transits,
        "hits": hits
    }



def _date_iter(start_ymd: str, days: int) -> List[str]:
    y, m, d = map(int, start_ymd.split("-"))
    start = _date(y, m, d)
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

def _score_day(natal: Dict[str, Any], ymd: str, local_tz: float, ayanamsha: str) -> Dict[str, Any]:
    """Small heuristic: +Jupiter/Venus to 9/10/11, −Saturn/Mars to Moon/Asc-lord/10L."""
    asc = asc_sign_num(natal)
    asc_lord = SIGN_LORD[asc]
    h9  = ((asc - 1) + 8) % 12 + 1
    h10 = ((asc - 1) + 9) % 12 + 1
    h11 = ((asc - 1) + 10) % 12 + 1

    trans = calc_transit_positions(ymd, "12:00", local_tz, ayanamsha)
    tmap = {t["name"]: t for t in trans}

    def _aspect_strength_to_sign(name: str, p) -> float:
        s = p["sign_num"]; lon = p["longitude"]
        def one(ts):
            ok, diff = aspects_deg(name, lon, (ts - 1) * 30 + 15.0, 30.0)
            return (1.0 - diff/30.0) if does_aspect_sign(name, s, ts) else 0.0
        return max(one(h9), one(h10), one(h11))

    j = tmap.get("Jupiter"); v = tmap.get("Venus"); s = tmap.get("Saturn"); m = tmap.get("Mars")
    base_plus  = 0.0
    if j: base_plus += 0.12 * _aspect_strength_to_sign("Jupiter", j)
    if v: base_plus += 0.08 * _aspect_strength_to_sign("Venus", v)

    # degree-based transit→natal pressure
    hits = aspects_to_natal(natal, ymd, "12:00", local_tz, ayanamsha, 6.0)["hits"]
    def max_hit(tname, targets):
        xs = [h["strength"] for h in hits if h["transit"]["name"] == tname and h["natal"]["name"] in targets]
        return max(xs) if xs else 0.0
    minus = 0.0
    ten_lord = SIGN_LORD[h10]
    minus -= 0.12 * max_hit("Saturn", { "Moon", asc_lord })
    minus -= 0.10 * max_hit("Mars",   { "Moon", asc_lord, ten_lord })

    score = max(-0.3, min(0.3, base_plus + minus))
    return {"date": ymd, "score": round(score, 3), "notes": []}

def scan_transit_windows(natal: Dict[str, Any], start_date: str, days: int, local_tz: float, ayanamsha: str = "Lahiri", top_n: int = 7) -> Dict[str, Any]:
    days = max(1, min(365, int(days)))
    dates = _date_iter(start_date, days)
    rows = [_score_day(natal, ymd, local_tz, ayanamsha) for ymd in dates]
    best = sorted(rows, key=lambda r: r["score"], reverse=True)[:top_n]
    worst = sorted(rows, key=lambda r: r["score"])[:min(top_n, len(rows))]
    return {"start": start_date, "days": days, "top": best, "bottom": worst, "all": rows}