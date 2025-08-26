import swisseph as swe
import datetime, pytz
from typing import List, Tuple, Dict, Any

# ---------------- core tables ----------------
SIGNS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

# simple classical combust limits (degrees from Sun)
COMBUST_LIMITS = {
    "Mercury": 12.0,
    "Venus": 10.0,
    "Mars": 17.0,
    "Jupiter": 11.0,
    "Saturn": 15.0,
}

AYAN_MAP = {
    "Lahiri": swe.SIDM_LAHIRI,
    "Raman": swe.SIDM_RAMAN,
    "Krishnamurti": swe.SIDM_KRISHNAMURTI,
}

PLANETS = [
    (swe.SUN, "Sun"),
    (swe.MOON, "Moon"),
    (swe.MERCURY, "Mercury"),
    (swe.VENUS, "Venus"),
    (swe.MARS, "Mars"),
    (swe.JUPITER, "Jupiter"),
    (swe.SATURN, "Saturn"),
    (swe.MEAN_NODE, "Rahu"),
    ("KETU", "Ketu"),
]

# ---------------- math helpers ----------------
def normalize(deg: float) -> float:
    return deg % 360.0

def ang_dist(a: float, b: float) -> float:
    d = abs(normalize(a - b))
    return d if d <= 180 else 360 - d

def sign_index_from_long(longitude: float) -> int:
    return int(normalize(longitude) // 30) + 1  # 1..12

def sign_of(longitude: float) -> Tuple[str, int]:
    idx = sign_index_from_long(longitude) - 1
    return SIGNS[idx], idx + 1

def pick_ayan(ayanamsha: str) -> int:
    return AYAN_MAP.get(ayanamsha, swe.SIDM_LAHIRI)

def to_utc_jd(dob: str, tob: str, tz_hours: float) -> float:
    # dob: 'YYYY-MM-DD', tob: 'HH:MM' in local time; tz_hours like +5.5
    dt = datetime.datetime.strptime(f"{dob} {tob}", "%Y-%m-%d %H:%M")
    offset_min = int(round(tz_hours * 60))
    dt_local = pytz.FixedOffset(offset_min).localize(dt)
    dt_utc = dt_local.astimezone(pytz.utc)
    return swe.julday(
        dt_utc.year, dt_utc.month, dt_utc.day,
        dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    )

def sidereal(longitude: float, ayan: float) -> float:
    return normalize(longitude - ayan)

def is_between_arc(a: float, b: float, x: float) -> bool:
    # arc-interval membership on a 0..360 circle: [a, b)
    a, b, x = normalize(a), normalize(b), normalize(x)
    if a <= b:
        return a <= x < b
    return x >= a or x < b

# ---------------- D1 (Rāśi) houses ----------------
def house_index_for(longitude: float, sid_cusps: List[float]) -> int:
    for i in range(12):
        a = sid_cusps[i]
        b = sid_cusps[(i + 1) % 12]
        if is_between_arc(a, b, longitude):
            return i + 1
    return 12

def compute_houses_sidereal(jd_ut: float, lat: float, lon: float, ayan: float):
    # houses() is tropical; convert cusps to sidereal by subtracting ayanamsha
    cusps, ascmc = swe.houses(jd_ut, lat, lon, b'P')  # Placidus
    sid_cusps = [sidereal(c, ayan) for c in cusps[:12]]
    asc_tropical = ascmc[0]
    asc = sidereal(asc_tropical, ayan)
    return sid_cusps, asc

# ---------------- generic varga helpers ----------------
def deg_in_sign(longitude: float) -> float:
    return normalize(longitude) % 30.0

def navamsa_sign_num(d1_sign: int, deg_in_that_sign: float) -> int:
    # D9: 30°/9 = 3°20' per pada
    pada = int((deg_in_that_sign * 9.0) // 30.0)  # 0..8
    # Movable: start from same sign; Fixed: start from 9th; Dual: start from 5th
    if d1_sign in (1,4,7,10):       # movable
        start = d1_sign
    elif d1_sign in (2,5,8,11):     # fixed
        start = ((d1_sign + 8 - 1) % 12) + 1  # 9th from
    else:                           # dual
        start = ((d1_sign + 4 - 1) % 12) + 1  # 5th from
    return ((start - 1 + pada) % 12) + 1

def dasamsa_sign_num(d1_sign: int, deg_in_that_sign: float) -> int:
    # D10: 30°/10 = 3° segments
    part = int(deg_in_that_sign // 3.0)  # 0..9
    # Odd sign: start from same; Even sign: start from 9th
    if d1_sign % 2 == 1:  # odd
        start = d1_sign
    else:                 # even
        start = ((d1_sign + 8 - 1) % 12) + 1
    return ((start - 1 + part) % 12) + 1

def whole_sign_houses_from(lagna_sign: int) -> List[Dict[str, Any]]:
    houses = []
    for i in range(12):
        sign_num = ((lagna_sign - 1 + i) % 12) + 1
        houses.append({
            "house": i + 1,
            "cusp_degree": None,  # varga uses whole-sign houses (no real cusps)
            "sign": SIGNS[sign_num - 1],
            "sign_num": sign_num
        })
    return houses

# ---------------- Varga builder (keeps your placement logic intact) ----------------
def build_chart_varga(varga: str, asc_sidereal_deg: float, d1_planets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    - Uses D1 longitudes to derive varga signs (unchanged from your current placement logic).
    - Ascendant sign for varga is computed from D1 Asc *via* varga mapping.
    - Returns whole-sign houses with cusp_degree=None AND houses_signs (pretty list).
    """
    # 1) varga asc sign
    asc_sign_d1 = sign_index_from_long(asc_sidereal_deg)
    asc_deg_in_sign = deg_in_sign(asc_sidereal_deg)

    if varga.upper() == "D9":
        lagna_sign = navamsa_sign_num(asc_sign_d1, asc_deg_in_sign)
    elif varga.upper() == "D10":
        lagna_sign = dasamsa_sign_num(asc_sign_d1, asc_deg_in_sign)
    else:
        raise ValueError(f"Unsupported varga: {varga}")

    ascendant = {
        "degree": round(asc_sidereal_deg, 4),     # keep same degree as D1 (you liked this earlier)
        "sign": SIGNS[lagna_sign - 1],
        "sign_num": lagna_sign
    }

    # 2) planets: keep original longitudes/retro/combust; only map to varga sign
    out_planets = []
    for p in d1_planets:
        lon = float(p["longitude"])
        d1_sign = int(p["sign_num"])
        dins = deg_in_sign(lon)

        if varga.upper() == "D9":
            v_sign = navamsa_sign_num(d1_sign, dins)
        else:  # D10
            v_sign = dasamsa_sign_num(d1_sign, dins)

        out_planets.append({
            "name": p["name"],
            "longitude": lon,                    # unchanged
            "sign": SIGNS[v_sign - 1],          # varga sign
            "sign_num": v_sign,                 # varga sign num
            "retro": bool(p.get("retro", False)),
            "combust": bool(p.get("combust", False))
            # (no 'house' in varga planets by design)
        })

    # 3) whole-sign houses + pretty "houses_signs"
    houses = whole_sign_houses_from(lagna_sign)
    houses_signs = [{"house": h["house"], "sign": h["sign"], "sign_num": h["sign_num"]} for h in houses]

    return {
        "ascendant": ascendant,
        "houses": houses,              # whole-sign, cusp_degree=None
        "houses_signs": houses_signs,  # NEW pretty field
        "planets": out_planets
    }

# ---------------- main chart compute ----------------
def compute_chart(dob: str, tob: str, lat: float, lon: float, tz: float, ayanamsha: str = "Lahiri"):
    # 1) sidereal mode
    swe.set_sid_mode(pick_ayan(ayanamsha))
    jd_ut = to_utc_jd(dob, tob, tz)
    ayan = swe.get_ayanamsa(jd_ut)
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED

    # 2) houses + asc (D1)
    sid_cusps, asc = compute_houses_sidereal(jd_ut, lat, lon, ayan)
    asc_sign, asc_sign_num = sign_of(asc)

    # 3) Sun first (for combustion checks)
    sun_pos, _ = swe.calc_ut(jd_ut, swe.SUN, flags)
    sun_lon = normalize(sun_pos[0])    # longitude
    sun_lon_spd = sun_pos[3]           # speed in longitude (deg/day) — kept for parity

    # 4) planets D1
    out_planets = []
    for pid, pname in PLANETS:
        if pid == "KETU":
            rahu_pos, _ = swe.calc_ut(jd_ut, swe.MEAN_NODE, flags)
            rahu_lon = normalize(rahu_pos[0])
            rahu_spd = rahu_pos[3]
            lon_sid = normalize(rahu_lon + 180.0)
            spd = -abs(rahu_spd)  # show retrograde nature
        else:
            pos, _ = swe.calc_ut(jd_ut, pid, flags)
            lon_sid = normalize(pos[0])  # longitude
            spd = pos[3]                 # longitude speed

        sgn_name, sgn_num = sign_of(lon_sid)
        house = house_index_for(lon_sid, sid_cusps)
        retro = spd < 0
        combust = False
        if pname in COMBUST_LIMITS and pname != "Sun":
            combust = ang_dist(lon_sid, sun_lon) <= COMBUST_LIMITS[pname]

        out_planets.append({
            "name": pname,
            "longitude": round(lon_sid, 4),
            "sign": sgn_name,
            "sign_num": sgn_num,
            "house": house,
            "retro": retro,
            "combust": combust
        })

    ascendant = {"degree": round(asc, 4), "sign": asc_sign, "sign_num": asc_sign_num}
    houses = [{"house": i + 1, "cusp_degree": round(sid_cusps[i], 4)} for i in range(12)]

    chart_d1 = {
        "ayanamsha": ayanamsha,
        "julian_day_ut": jd_ut,
        "ascendant": ascendant,
        "houses": houses,
        "planets": out_planets
    }

    # 5) Vargas (no placement logic change; just add houses_signs)
    d9 = build_chart_varga("D9", asc, out_planets)
    d10 = build_chart_varga("D10", asc, out_planets)

    # merge
    chart_d1["D9"]  = d9
    chart_d1["D10"] = d10
    return chart_d1
