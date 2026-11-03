"""JalRakshak AI - water-balance engine (FAO-56 based).

Pipeline per field:
  weather (Open-Meteo, cached, with offline fallback)
  -> daily ETc = ET0 x Kc
  -> soil-water depletion "bucket" since last irrigation
  -> decision: IRRIGATE_NOW / IRRIGATE_IN_2_DAYS / WAIT (rain) / NO_NEED
  -> amount in mm, litres and pump minutes
Reference: FAO Irrigation and Drainage Paper 56 (Allen et al., 1998).
Advisory tool: values are approximate and must be checked against field conditions.
"""
import json
import os
import random
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import requests

IST = timezone(timedelta(hours=5, minutes=30))
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

# ----------------------------------------------------------------------------
# Crop / soil / irrigation parameters (approximate FAO-56 values)
# kc = (initial, mid, end); stages = days (initial, development, mid, late)
# root = effective root depth (m); p = depletion fraction before stress
# value = relative economic value used only for priority ranking
# ----------------------------------------------------------------------------
CROPS = {
    "sugarcane": dict(kc=(0.40, 1.25, 0.75), stages=(35, 60, 190, 80), root=1.2, p=0.65, value=1.0),
    "onion":     dict(kc=(0.50, 1.05, 0.75), stages=(15, 25, 50, 30),  root=0.4, p=0.30, value=0.9),
    "cotton":    dict(kc=(0.35, 1.15, 0.65), stages=(30, 50, 55, 45),  root=1.0, p=0.65, value=0.8),
    "soybean":   dict(kc=(0.40, 1.15, 0.50), stages=(15, 25, 40, 20),  root=0.6, p=0.50, value=0.6),
    "wheat":     dict(kc=(0.30, 1.15, 0.25), stages=(20, 25, 60, 30),  root=0.9, p=0.55, value=0.6),
    "jowar":     dict(kc=(0.30, 1.05, 0.55), stages=(20, 35, 40, 30),  root=0.9, p=0.55, value=0.5),
}
# Available water (field capacity - wilting point), m3/m3
SOIL = {"black": 0.18, "loam": 0.15, "sandy": 0.08}
# Application efficiency
EFF = {"drip": 0.90, "sprinkler": 0.75, "flood": 0.60}
# Fraction of RAW at which we trigger irrigation (assumption; tunable).
# Drip wets only part of the root zone and is run frequently, so it triggers earlier.
TRIGGER = {"drip": 0.60, "sprinkler": 0.85, "flood": 1.00}

ACRE_M2 = 4047
DEFAULT_LAT, DEFAULT_LON = 17.98, 74.43  # Phaltan, Satara

RAIN_WAIT_MM = 10      # forecast rain in next 48 h that justifies waiting
RAIN_WAIT_PROB = 60    # and its probability (%)
PAST_DAYS = 30
FORECAST_DAYS = 5


def today_ist():
    return datetime.now(IST).date()


# ----------------------------------------------------------------------------
# Crop coefficient curve
# ----------------------------------------------------------------------------
def season_length(crop):
    return sum(CROPS[crop]["stages"])


def kc_for(crop, das):
    """Kc by days after sowing: flat initial, linear rise, flat mid, linear fall."""
    c = CROPS[crop]
    ini, mid, end = c["kc"]
    l1, l2, l3, l4 = c["stages"]
    if das < l1:
        return ini
    if das < l1 + l2:
        return ini + (mid - ini) * (das - l1) / l2
    if das < l1 + l2 + l3:
        return mid
    return mid + (end - mid) * min(1.0, (das - l1 - l2 - l3) / l4)


def stage_of(crop, das):
    l1, l2, l3, _ = CROPS[crop]["stages"]
    if das < l1:
        return "initial"
    if das < l1 + l2:
        return "development"
    if das < l1 + l2 + l3:
        return "mid"
    return "late"


def effective_rain(mm):
    """Ignore light rain (<3 mm), count 80% of the rest."""
    return 0.0 if mm < 3 else mm * 0.8


# ----------------------------------------------------------------------------
# Weather: Open-Meteo -> daily cache -> deterministic offline demo data
# ----------------------------------------------------------------------------
def _synthetic_weather(today):
    """Deterministic demo weather so the app works with no internet."""
    days = [today + timedelta(days=i) for i in range(-PAST_DAYS, FORECAST_DAYS)]
    et0, rain, prob = [], [], []
    for d in days:
        rng = random.Random(d.toordinal())
        et0.append(round(3.5 + rng.random() * 2.0, 2))
        wet = rng.random() < 0.12
        r = round(rng.uniform(5, 25), 1) if wet else 0.0
        rain.append(r)
        prob.append(rng.randint(60, 90) if wet else rng.randint(0, 30))
    return dict(time=[d.isoformat() for d in days], et0=et0, rain=rain, prob=prob,
                today_idx=PAST_DAYS, source="offline-demo")


def _clean(daily, source):
    n = len(daily["time"])
    et0 = [4.0 if v is None else float(v) for v in daily["et0_fao_evapotranspiration"]]
    rain = [0.0 if v is None else float(v) for v in daily["precipitation_sum"]]
    prob = [0 if v is None else float(v) for v in daily["precipitation_probability_max"]]
    t = today_ist().isoformat()
    idx = daily["time"].index(t) if t in daily["time"] else min(PAST_DAYS, n - 1)
    return dict(time=list(daily["time"]), et0=et0, rain=rain, prob=prob,
                today_idx=idx, source=source)


def get_weather(lat, lon, offline=False):
    """Return dict(time, et0, rain, prob, today_idx, source)."""
    today = today_ist()
    if offline:
        return _synthetic_weather(today)
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"wx_{lat:.2f}_{lon:.2f}_{today.isoformat()}.json")
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "daily": "et0_fao_evapotranspiration,precipitation_sum,precipitation_probability_max",
                "past_days": PAST_DAYS, "forecast_days": FORECAST_DAYS,
                "timezone": "Asia/Kolkata",
            },
            timeout=10,
        )
        r.raise_for_status()
        daily = r.json()["daily"]
        with open(cache, "w") as fh:
            json.dump(daily, fh)
        return _clean(daily, "open-meteo-live")
    except Exception:
        if os.path.exists(cache):
            with open(cache) as fh:
                return _clean(json.load(fh), "cached")
        return _synthetic_weather(today)


def with_simulated_rain(w, mm=25, prob=90):
    """Demo helper: pretend heavy rain is forecast for tomorrow and the day after."""
    w = deepcopy(w)
    t = w["today_idx"]
    for i in (t + 1, t + 2):
        if i < len(w["rain"]):
            w["rain"][i], w["prob"][i] = mm, prob
    w["source"] += "+simulated-rain"
    return w


# ----------------------------------------------------------------------------
# Soil-water bucket
# ----------------------------------------------------------------------------
def soil_params(f):
    c = CROPS[f["crop"]]
    taw = 1000 * SOIL[f["soil"]] * c["root"]       # total available water, mm
    raw = c["p"] * taw                              # readily available water, mm
    trigger = raw * TRIGGER[f["irrigation"]]        # irrigate when depletion reaches this
    return taw, raw, trigger


def _depletion(f, w, taw):
    """Depletion (mm) at the start of today, plus a daily trace for charts."""
    sow = date.fromisoformat(f["sowing_date"])
    crop = f["crop"]
    t = w["today_idx"]
    start = 0
    li = f.get("last_irrigation")
    if li:
        ld = li if isinstance(li, str) else li.isoformat()
        if ld in w["time"]:
            start = w["time"].index(ld) + 1       # soil refilled to field capacity that day
        elif ld > w["time"][-1]:
            start = t
    dr, trace = 0.0, []
    for i in range(start, t):
        d = date.fromisoformat(w["time"][i])
        das = (d - sow).days
        if 0 <= das <= season_length(crop):
            etc = w["et0"][i] * kc_for(crop, das)
            dr = min(taw, max(0.0, dr + etc - effective_rain(w["rain"][i])))
        trace.append((w["time"][i], round(dr, 1)))
    return dr, trace


# ----------------------------------------------------------------------------
# Recommendation
# ----------------------------------------------------------------------------
def recommend(field, weather=None, simulate_rain=False, offline=False):
    w = weather or get_weather(field["lat"], field["lon"], offline=offline)
    if simulate_rain:
        w = with_simulated_rain(w)
    crop = field["crop"]
    t = w["today_idx"]
    today = date.fromisoformat(w["time"][t])
    das = (today - date.fromisoformat(field["sowing_date"])).days
    taw, raw, trigger = soil_params(field)
    forecast = [dict(date=w["time"][i], et0=w["et0"][i], rain=w["rain"][i], prob=w["prob"][i])
                for i in range(t, len(w["time"]))]
    base = dict(das=das, taw_mm=round(taw, 1), raw_mm=round(raw, 1), trigger_mm=round(trigger, 1),
                forecast=forecast, source=w["source"], litres=0, litres_if_irrigated=0,
                minutes=0, water_mm=0.0, depletion_mm=0.0, stress_ratio=0.0,
                etc_today=0.0, kc=0.0, rain48=0.0, prob48=0, trace=[], need="NO_NEED")

    if das < 0:
        return {**base, "action": "NOT_SOWN", "stage": "initial", "reason_code": "not_sown"}
    if das > season_length(crop):
        return {**base, "action": "SEASON_OVER", "stage": "late", "reason_code": "season_over"}

    dr, trace = _depletion(field, w, taw)
    if field.get("sensor_depletion_mm") is not None:   # manual / sensor reading overrides model
        dr = min(taw, max(0.0, float(field["sensor_depletion_mm"])))

    kc = kc_for(crop, das)
    etc_today = w["et0"][t] * kc
    rain48 = sum(w["rain"][t:t + 2])
    prob48 = max(w["prob"][t:t + 2]) if w["prob"][t:t + 2] else 0

    eff = EFF[field["irrigation"]]
    area_m2 = field["area_acre"] * ACRE_M2

    if dr >= trigger:
        need, need_mm, code = "IRRIGATE_NOW", dr, "below_safe"
    elif dr + 2 * etc_today >= trigger:
        need, need_mm, code = "IRRIGATE_IN_2_DAYS", dr + 2 * etc_today, "crossing_soon"
    else:
        need, need_mm, code = "NO_NEED", 0.0, "enough"

    action = need
    if need != "NO_NEED" and rain48 >= RAIN_WAIT_MM and prob48 >= RAIN_WAIT_PROB:
        action, code = "WAIT", "rain_expected"

    gross = need_mm / eff
    litres_full = int(gross * area_m2)
    litres = litres_full if action in ("IRRIGATE_NOW", "IRRIGATE_IN_2_DAYS") else 0
    pump_lpm = max(1, float(field.get("pump_lpm", 400)))
    minutes = int(-(-litres // pump_lpm)) if action == "IRRIGATE_NOW" else 0

    return {**base, "action": action, "need": need, "reason_code": code,
            "stage": stage_of(crop, das), "depletion_mm": round(dr, 1),
            "stress_ratio": round(dr / trigger, 2) if trigger else 0.0,
            "etc_today": round(etc_today, 2), "kc": round(kc, 2),
            "rain48": round(rain48, 1), "prob48": int(prob48),
            "water_mm": round(gross, 1), "litres": litres,
            "litres_if_irrigated": litres_full, "minutes": minutes, "trace": trace}


# ----------------------------------------------------------------------------
# Priority ranking (which field first)
# ----------------------------------------------------------------------------
STAGE_WEIGHT = {"initial": 0.5, "development": 0.8, "mid": 1.0, "late": 0.3}


def priority(fields):
    """Score = 55% stress + 25% growth-stage sensitivity + 20% crop value."""
    for f in fields:
        r = f["reco"]
        if r["action"] in ("NOT_SOWN", "SEASON_OVER"):
            f["score"] = -1.0
            continue
        f["score"] = round(0.55 * min(r["stress_ratio"], 1.5) / 1.5
                           + 0.25 * STAGE_WEIGHT[r["stage"]]
                           + 0.20 * CROPS[f["crop"]]["value"], 3)
    return sorted(fields, key=lambda x: -x["score"])


# ----------------------------------------------------------------------------
# Water saved vs. habit (estimate)
# ----------------------------------------------------------------------------
def water_savings(field, weather, habit_days=7, habit_mm=40, days=30):
    """Replay the last `days` days: smart schedule vs. fixed 'every N days' habit.
    habit_mm is the gross depth the farmer applies each time (editable assumption)."""
    w = weather
    t = w["today_idx"]
    crop = field["crop"]
    taw, _, trigger = soil_params(field)
    eff = EFF[field["irrigation"]]
    area_m2 = field["area_acre"] * ACRE_M2
    sow = date.fromisoformat(field["sowing_date"])
    dr, smart_l, events, active_days = 0.0, 0.0, 0, 0
    for i in range(max(0, t - days), t):
        das = (date.fromisoformat(w["time"][i]) - sow).days
        if not 0 <= das <= season_length(crop):
            continue
        active_days += 1
        dr = min(taw, max(0.0, dr + w["et0"][i] * kc_for(crop, das) - effective_rain(w["rain"][i])))
        if dr >= trigger:
            smart_l += dr / eff * area_m2
            events += 1
            dr = 0.0
    habit_events = active_days // habit_days
    habit_l = habit_events * habit_mm * area_m2
    saved = habit_l - smart_l
    return dict(days=active_days, smart_litres=int(smart_l), smart_events=events,
                habit_litres=int(habit_l), habit_events=habit_events, saved_litres=int(saved),
                saved_pct=round(100 * saved / habit_l, 1) if habit_l else 0.0)
