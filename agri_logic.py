"""
agri_logic.py
Rule-based agricultural decision logic for AgroGuard AI.
Slope/tilt sensing is intentionally not used in the current hardware setup.
"""

def irrigation_decision(soil_pct, rain_raw, mode, manual_state, settings):
    rain_status = "RAIN" if rain_raw < settings["rain_raw_threshold"] else "NO_RAIN"

    # Rain is always a hard safety interlock.
    if rain_status == "RAIN":
        return {
            "state": "OFF",
            "mode": mode,
            "reason": "Pump OFF — rain detected, safety interlock active.",
            "rain_status": rain_status,
        }

    if mode == "MANUAL":
        state = "ON" if manual_state == "ON" else "OFF"
        return {
            "state": state,
            "mode": mode,
            "reason": f"Manual mode — pump set {state} by user.",
            "rain_status": rain_status,
        }

    if soil_pct < settings["soil_dry_threshold"]:
        state = "ON"
        reason = f"Pump ON — soil moisture {soil_pct:.1f}% below dry threshold ({settings['soil_dry_threshold']:.1f}%)."
    elif soil_pct > settings["soil_wet_threshold"]:
        state = "OFF"
        reason = f"Pump OFF — soil moisture {soil_pct:.1f}% above wet threshold ({settings['soil_wet_threshold']:.1f}%)."
    else:
        state = manual_state if manual_state in ("ON", "OFF") else "OFF"
        reason = f"Pump {state} — soil moisture {soil_pct:.1f}% in stable band, holding last state."

    return {"state": state, "mode": mode, "reason": reason, "rain_status": rain_status}


def _score_band(value, good_range, ok_range, label):
    lo_g, hi_g = good_range
    lo_o, hi_o = ok_range
    if lo_g <= value <= hi_g:
        return 100, f"{label}: Good"
    if lo_o <= value <= hi_o:
        return 65, f"{label}: Acceptable"
    return 30, f"{label}: Poor"


def land_suitability(temperature, humidity, soil_pct, rainfall_mm, slope_deg=None, terrain_stable=None):
    scores = []

    s, r = _score_band(temperature, (18, 32), (12, 38), "Temperature")
    scores.append((s, r))
    s, r = _score_band(soil_pct, (35, 70), (20, 85), "Soil moisture")
    scores.append((s, r))
    s, r = _score_band(rainfall_mm, (600, 2000), (300, 3000), "Rainfall")
    scores.append((s, r))

    if slope_deg is None:
        scores.append((None, "Slope: Not available (no slope sensor installed)"))
    else:
        s, r = _score_band(slope_deg, (0, 10), (10, 20), "Slope")
        scores.append((s, r))

    if terrain_stable is None:
        scores.append((None, "Terrain stability: Not available (no motion/tilt sensor installed)"))
    else:
        scores.append((100 if terrain_stable else 40, f"Terrain stability: {'Good' if terrain_stable else 'Concerning'}"))

    available = [s for s, _ in scores if s is not None]
    overall = round(sum(available) / len(available)) if available else 0

    if overall >= 75:
        verdict = "Suitable for cultivation"
    elif overall >= 50:
        verdict = "Moderately suitable — some conditions need attention"
    else:
        verdict = "Currently not well suited — review flagged factors"

    return {"score": overall, "verdict": verdict, "reasons": [r for _, r in scores]}


def terrain_risk(slope_deg=None, terrain_movement=None, rain_status="NO_RAIN"):
    # No slope sensor in current hardware: do not fabricate slope or movement values.
    if slope_deg is None and terrain_movement is None:
        factors = ["Slope / ground-movement data is unavailable because no tilt sensor is installed."]
        if rain_status == "RAIN":
            factors.append("Rain is active — inspect drainage and terrain conditions manually.")
        return {
            "level": "Unavailable",
            "factors": factors,
            "disclaimer": "Terrain Risk Screening is unavailable without a slope/tilt sensor. This system does not provide professional geological or landslide prediction.",
        }

    points = 0
    factors = []
    if slope_deg is not None:
        if slope_deg < 10:
            factors.append("Slope is gentle")
        elif slope_deg < 20:
            points += 1
            factors.append("Slope is moderate")
        else:
            points += 2
            factors.append("Slope is steep")
    if terrain_movement:
        points += 2
        factors.append("Tilt sensor indicates possible ground movement")
    if rain_status == "RAIN":
        points += 1
        factors.append("Active rainfall increases surface risk")

    level = "Low Risk" if points <= 1 else "Moderate Risk" if points <= 3 else "High Risk"
    return {
        "level": level,
        "factors": factors,
        "disclaimer": "Terrain Risk Screening only — this is a basic indication, not a certified geological landslide prediction.",
    }


CROP_DB = [
    {"name": "Rice", "temp": (20, 35), "moisture": (60, 90), "rainfall": (1000, 2500), "max_slope": 8, "notes": "Needs high moisture; terrain fit should be checked separately."},
    {"name": "Maize (Corn)", "temp": (18, 32), "moisture": (40, 70), "rainfall": (500, 1200), "max_slope": 15, "notes": "Good general-purpose crop; drainage and terrain should be checked."},
    {"name": "Finger Millet (Ragi)", "temp": (15, 30), "moisture": (25, 55), "rainfall": (400, 1000), "max_slope": 30, "notes": "Hardy crop with relatively lower water requirement."},
    {"name": "Tea", "temp": (13, 28), "moisture": (50, 80), "rainfall": (1500, 3000), "max_slope": 35, "notes": "Climate and rainfall are important; terrain must be assessed separately."},
    {"name": "Potato", "temp": (10, 25), "moisture": (40, 70), "rainfall": (500, 1200), "max_slope": 20, "notes": "Prefers cooler conditions and well-drained soil."},
    {"name": "Ginger", "temp": (19, 30), "moisture": (55, 80), "rainfall": (1500, 2500), "max_slope": 25, "notes": "Needs adequate moisture and suitable climate."},
    {"name": "Groundnut", "temp": (20, 35), "moisture": (25, 55), "rainfall": (500, 1000), "max_slope": 10, "notes": "Prefers well-drained conditions."},
    {"name": "Chili Pepper", "temp": (20, 35), "moisture": (30, 60), "rainfall": (600, 1500), "max_slope": 15, "notes": "Moderate water needs; local agronomic conditions should be checked."},
]

def _range_score(value, lo, hi):
    if lo <= value <= hi:
        return 1.0
    span = max(hi - lo, 1)
    dist = min(abs(value - lo), abs(value - hi))
    return max(0.0, 1 - dist / span)


def recommend_crops(temperature, soil_pct, rainfall_mm, slope_deg=None, top_n=4):
    results = []
    for crop in CROP_DB:
        t_score = _range_score(temperature, *crop["temp"])
        m_score = _range_score(soil_pct, *crop["moisture"])
        r_score = _range_score(rainfall_mm, *crop["rainfall"])
        if slope_deg is None:
            slope_score = 0.5
            slope_reason = "Terrain fit not evaluated (no slope sensor)"
        else:
            if slope_deg > crop["max_slope"] + 10:
                continue
            slope_score = 1.0 if slope_deg <= crop["max_slope"] else max(0.0, 1 - (slope_deg - crop["max_slope"]) / 20)
            slope_reason = "Good terrain compatibility" if slope_score > 0.7 else "Slope is challenging for this crop"

        overall = round((t_score * 0.35 + m_score * 0.35 + r_score * 0.30) * 100) if slope_deg is None else round((t_score * 0.3 + m_score * 0.3 + r_score * 0.25 + slope_score * 0.15) * 100)
        why = [
            "Suitable temperature range" if t_score > 0.7 else "Temperature slightly outside ideal range",
            "Good soil moisture match" if m_score > 0.7 else "Soil moisture not ideal",
            "Good rainfall compatibility" if r_score > 0.7 else "Rainfall not ideal",
            slope_reason,
        ]
        results.append({"name": crop["name"], "score": overall, "why": why, "notes": crop["notes"]})
    results.sort(key=lambda c: c["score"], reverse=True)
    return results[:top_n]


def build_advisory(reading, suitability, risk, irrigation, top_crop):
    tips = []
    if irrigation["rain_status"] == "RAIN":
        tips.append("Rain is active — hold off on watering and check drainage.")
    elif reading.get("has_reading") and reading["soil_moisture_pct"] < 30:
        tips.append("Soil is on the dry side — irrigation is recommended soon.")
    elif reading.get("has_reading") and reading["soil_moisture_pct"] > 75:
        tips.append("Soil is quite wet — avoid additional watering to prevent waterlogging.")
    else:
        tips.append("Soil moisture is in a healthy range — no action needed right now.")

    if risk["level"] == "High Risk":
        tips.append("Terrain risk is high — inspect slopes after rain and avoid heavy machinery on wet ground.")
    elif risk["level"] == "Moderate Risk":
        tips.append("Terrain risk is moderate — monitor the area, especially after heavy rain.")
    elif risk["level"] == "Unavailable":
        tips.append("Slope-based terrain screening is unavailable because no tilt/slope sensor is installed.")

    if suitability["score"] < 50:
        tips.append("Land suitability is currently low — review the flagged factors before planting.")
    if top_crop:
        tips.append(f"Based on current climate and soil conditions, {top_crop['name']} is the strongest crop match right now.")
    return tips
