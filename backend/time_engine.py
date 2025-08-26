# backend/time_engine.py
import datetime as dt
from typing import List, Dict, Any, Tuple
import swisseph as swe

# ---- Vimshottari Dasha ----
DASHA_ORDER = ["Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury"]
DASHA_YEARS = {"Ketu":7,"Venus":20,"Sun":6,"Moon":10,"Mars":7,"Rahu":18,"Jupiter":16,"Saturn":19,"Mercury":17}
NAK_LORDS = [
    "Ketu","Venus","Sun", "Moon","Mars","Rahu","Jupiter","Saturn","Mercury",  # 0..8
    "Ketu","Venus","Sun", "Moon","Mars","Rahu","Jupiter","Saturn","Mercury",  # 9..17
    "Ketu","Venus","Sun", "Moon","Mars","Rahu","Jupiter","Saturn","Mercury"   # 18..26
]
NAK_SIZE = 13.3333333333  # degrees

def jd_from_local(d: dt.datetime, tz_hours: float) -> float:
    # interpret d as local; convert to UTC JD
    offset = int(round(tz_hours * 60))
    from pytz import FixedOffset, utc
    d_local = FixedOffset(offset).localize(d)
    d_utc = d_local.astimezone(utc)
    return swe.julday(d_utc.year, d_utc.month, d_utc.day, d_utc.hour + d_utc.minute/60 + d_utc.second/3600)

def moon_sidereal_lon(jd_ut: float) -> float:
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
    pos, _ = swe.calc_ut(jd_ut, swe.MOON, flags)
    return pos[0] % 360.0

def moon_nakshatra(moon_lon: float) -> Tuple[int, float]:
    """Return (nak_index 0..26, frac_remaining 0..1)."""
    idx = int(moon_lon // NAK_SIZE)
    start = idx * NAK_SIZE
    end = start + NAK_SIZE
    remaining = (end - moon_lon) / NAK_SIZE
    if remaining < 0: remaining = 0.0
    return idx, remaining

def next_in_cycle(name: str) -> str:
    i = DASHA_ORDER.index(name)
    return DASHA_ORDER[(i + 1) % len(DASHA_ORDER)]

def add_years(d: dt.datetime, years: float) -> dt.datetime:
    days = years * 365.2425
    return d + dt.timedelta(days=days)

def vimshottari_schedule(dob: str, tob: str, tz: float, years_ahead: int = 60) -> Dict[str, Any]:
    # build MD + AD from birth to birth+years_ahead
    dob_dt = dt.datetime.strptime(f"{dob} {tob}", "%Y-%m-%d %H:%M")
    jd = jd_from_local(dob_dt, tz)
    moon_lon = moon_sidereal_lon(jd)
    nak_idx, rem_frac = moon_nakshatra(moon_lon)
    md_lord = NAK_LORDS[nak_idx]
    # remaining of current MD at birth:
    md_years_total = DASHA_YEARS[md_lord]
    md_rem_years = md_years_total * rem_frac

    md_list = []
    cur_start = dob_dt
    cur_lord = md_lord
    cur_len = md_rem_years
    horizon = add_years(dob_dt, years_ahead)

    # first (partial) MD
    cur_end = add_years(cur_start, cur_len)
    md_list.append({"lord": cur_lord, "start": cur_start, "end": cur_end})
    # subsequent full MDs
    while cur_end < horizon:
        cur_start = cur_end
        cur_lord = next_in_cycle(cur_lord)
        cur_len = DASHA_YEARS[cur_lord]
        cur_end = add_years(cur_start, cur_len)
        md_list.append({"lord": cur_lord, "start": cur_start, "end": cur_end})

    # Build Antardashas (AD) inside each MD
    ad_list = []
    for md in md_list:
        md_len_years = (md["end"] - md["start"]).days / 365.2425
        # sequence starts from MD lord itself
        seq = DASHA_ORDER[DASHA_ORDER.index(md["lord"]):] + DASHA_ORDER[:DASHA_ORDER.index(md["lord"])]
        cursor = md["start"]
        for lord in seq:
            portion = DASHA_YEARS[lord] / 120.0
            span_years = md_len_years * portion
            ad_start = cursor
            ad_end = add_years(ad_start, span_years)
            if ad_start >= md["end"]: break
            ad_list.append({"md": md["lord"], "lord": lord, "start": ad_start, "end": min(ad_end, md["end"])})
            cursor = ad_end
            if cursor >= md["end"]: break

    return {"md": md_list, "ad": ad_list}

# ---- Saturn Transit hits to natal L12 (degree-based Vedic drishti) ----
ASPECT_ANGLES = {"Saturn":[60,180,300]}  # same definition
def abs_min_angle(a: float, b: float) -> float:
    d = abs((a-b) % 360.0)
    return min(d, 360.0 - d)

def saturn_transit_hits_to(chart: Dict[str, Any], to_lon: float, tz: float, date_from: str, date_to: str, orb: float = 6.0, step_days: int = 30):
    """Group monthly windows where transit Saturn aspects natal 'to_lon' by Vedic angles within orb."""
    start = dt.datetime.strptime(date_from, "%Y-%m-%d")
    end   = dt.datetime.strptime(date_to, "%Y-%m-%d")
    hits = []
    cur_on = None
    cur_start = None

    swe.set_sid_mode(swe.SIDM_LAHIRI)  # assume Lahiri for transit too
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL

    d = start
    while d <= end:
        jd = jd_from_local(dt.datetime(d.year, d.month, d.day, 12, 0), tz)
        pos, _ = swe.calc_ut(jd, swe.SATURN, flags)
        sat_lon = pos[0] % 360.0
        ok = any(abs_min_angle(((to_lon - sat_lon) % 360.0), ang) <= orb for ang in ASPECT_ANGLES["Saturn"])
        if ok and not cur_on:
            cur_on = True
            cur_start = d
        if (not ok) and cur_on:
            hits.append({"start": cur_start, "end": d})
            cur_on = False
        d += dt.timedelta(days=step_days)

    if cur_on:
        hits.append({"start": cur_start, "end": end})
    return hits