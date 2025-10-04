# backend/main.py
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from .ephemeris import compute_chart
from .rules_engine import reload_rules, RULES_CACHE, evaluate_rule, evaluate_all, rules_dir
from .predictor import summarize
from .rules_engine import evaluate_all, RULES_CACHE
from .ashtakavarga import sav_lite
from .transits import aspects_to_natal
from .predictor import summarize_timeaware
from .transits import aspects_to_natal,scan_transit_windows



app = FastAPI(title="Next-Gen Astro Platform")

# If you already put this model in schemas.py, you can instead:
# from .schemas import ChartIn
class ChartIn(BaseModel):
    dob: str      # "YYYY-MM-DD"
    tob: str      # "HH:MM" 24h
    lat: float
    lon: float
    tz: float     # e.g. 5.5
    ayanamsha: str = "Lahiri"

class TransitIn(ChartIn):
    when_date: str   # "YYYY-MM-DD"
    when_time: str   # "HH:MM"
    when_tz: float   # e.g. 5.5 (local tz for when)

class WindowIn(ChartIn):
    start_date: str  # "YYYY-MM-DD"
    days: int        # e.g., 60
    when_tz: float   # local tz to evaluate each day (usually same as tz)

@app.get("/")
def root():
    return {"message": "Astro API running!"}

# ----- Chart endpoints (keep if you use them) -----
@app.post("/chart/v1")
def chart_v1(body: ChartIn):
    return compute_chart(body.dob, body.tob, body.lat, body.lon, body.tz, body.ayanamsha)

# ----- JSON rules engine endpoints -----
@app.post("/rules/reload")
def rules_reload():
    return reload_rules()

@app.get("/rules/list")
def rules_list():
    return {"count": len(RULES_CACHE), "ids": list(RULES_CACHE.keys())}

@app.post("/rules/evaluate/all")
def rules_eval_all(body: ChartIn):
    chart = compute_chart(body.dob, body.tob, body.lat, body.lon, body.tz, body.ayanamsha)
    return evaluate_all(chart)

@app.post("/rules/evaluate/{rule_id}")
def rules_eval_one(rule_id: str, body: ChartIn):
    chart = compute_chart(body.dob, body.tob, body.lat, body.lon, body.tz, body.ayanamsha)
    rule = RULES_CACHE.get(rule_id)
    if not rule:
        return {"error": f"Rule '{rule_id}' not loaded. Call /rules/reload or check /rules/list."}
    return evaluate_rule(chart, rule)

@app.post("/predict/v1")
def predict_v1(body: ChartIn, top_n: int = 5):
    chart = compute_chart(body.dob, body.tob, body.lat, body.lon, body.tz, body.ayanamsha)
    evals = evaluate_all(chart)
    report = summarize(evals, top_n=top_n)
    return {
        "chart_meta": {"ayanamsha": body.ayanamsha},
        "loaded_rules": list(RULES_CACHE.keys()),
        **report
        }

@app.post("/ashtakavarga/lite")
def ashtakavarga_lite(body: ChartIn):
    chart = compute_chart(body.dob, body.tob, body.lat, body.lon, body.tz, body.ayanamsha)
    return sav_lite(chart)

@app.post("/transits/aspects/v1")
def transits_aspects_v1(body: TransitIn, orb_deg: float = 6.0):
    """
    Transiting→Natal aspects (mutual by sign; degree closeness within orb_deg).
    Sorted by strength.
    """
    natal = compute_chart(body.dob, body.tob, body.lat, body.lon, body.tz, body.ayanamsha)
    res = aspects_to_natal(
        natal,
        when_date=body.when_date,
        when_time=body.when_time,
        when_tz=body.when_tz,
        ayanamsha=body.ayanamsha,
        orb_deg=orb_deg
    )
    return res
@app.post("/predict/timeaware/v1")
def predict_timeaware_v1(body: TransitIn, top_n: int = 5, orb_deg: float = 6.0):
    """
    Combine static rule scores with small transit-based boosts.
    """
    natal = compute_chart(body.dob, body.tob, body.lat, body.lon, body.tz, body.ayanamsha)
    evals = evaluate_all(natal)
    report = summarize_timeaware(
        evals, natal,
        when_date=body.when_date, when_time=body.when_time, when_tz=body.when_tz,
        ayanamsha=body.ayanamsha, orb_deg=orb_deg, top_n=top_n
    )
    return {
        "chart_meta": {"ayanamsha": body.ayanamsha},
        "when": {"date": body.when_date, "time": body.when_time, "tz": body.when_tz},
        **report
    }

@app.post("/transits/windows/v1")
def transits_windows_v1(body: WindowIn, top_n: int = 7):
    natal = compute_chart(body.dob, body.tob, body.lat, body.lon, body.tz, body.ayanamsha)
    res = scan_transit_windows(
        natal,
        start_date=body.start_date,
        days=body.days,
        local_tz=body.when_tz,
        ayanamsha=body.ayanamsha,
        top_n=top_n
    )
    return res