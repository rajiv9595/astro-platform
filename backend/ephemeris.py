# backend/ephemeris.py
import swisseph as swe
import datetime, pytz
from typing import List, Tuple

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

def normalize(deg: float) -> float:
    return deg % 360.0

def ang_dist(a: float, b: float) -> float:
    d = abs(normalize(a - b))
    return d if d <= 180 else 360 - d

def sign_of(longitude: float) -> Tuple[str, int]:
    idx = int(normalize(longitude) // 30)
    return SIGNS[idx], idx + 1  # 1..12

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

def compute_chart(dob: str, tob: str, lat: float, lon: float, tz: float, ayanamsha: str = "Lahiri"):
    # 1) sidereal mode
    swe.set_sid_mode(pick_ayan(ayanamsha))
    jd_ut = to_utc_jd(dob, tob, tz)
    ayan = swe.get_ayanamsa(jd_ut)
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED

    # 2) houses + asc
    sid_cusps, asc = compute_houses_sidereal(jd_ut, lat, lon, ayan)
    asc_sign, asc_sign_num = sign_of(asc)

    # 3) Sun first (for combustion checks)
    sun_pos, _ = swe.calc_ut(jd_ut, swe.SUN, flags)
    sun_lon = normalize(sun_pos[0])    # longitude
    sun_lon_spd = sun_pos[3]           # speed in longitude (deg/day)

    # 4) planets
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

    return {
        "ayanamsha": ayanamsha,
        "julian_day_ut": jd_ut,
        "ascendant": ascendant,
        "houses": houses,
        "planets": out_planets
    }