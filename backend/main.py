# backend/main.py
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from .ephemeris import compute_chart
from .rules_engine import reload_rules, RULES_CACHE, evaluate_rule, evaluate_all, rules_dir, RULE_ERRORS

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

@app.get("/rules/debug")
def rules_debug():
    rd = rules_dir()
    files = os.listdir(rd) if os.path.isdir(rd) else []
    return {"rules_dir": rd, "files": files, "loaded": list(RULES_CACHE.keys()), "errors": RULE_ERRORS}
