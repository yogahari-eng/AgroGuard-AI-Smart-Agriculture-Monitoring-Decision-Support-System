"""
app.py — AgroGuard AI
Pure Python web app: Flask + Jinja2 server-rendered templates, SQLite,
matplotlib for charts. No JavaScript framework is used anywhere; live
updates use a plain HTML meta-refresh, and charts are rendered server-side
as PNG images.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:5000
"""
import os
import io
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, session, flash,
    send_file, jsonify
)
from werkzeug.utils import secure_filename

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from database import init_db, get_db, get_settings, update_settings, now
import auth
import agri_logic
import ai_inference

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("AGROGUARD_SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB upload cap

REFRESH_SECONDS = 4  # dashboard auto-refresh interval
DEVICE_API_KEY = "agroguard-esp32-2026"

# Default assumed rainfall (mm/year) used by land-suitability/crop modules
# until the user overrides it on the Land Suitability page.
DEFAULT_RAINFALL_MM = 1100


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_globals():
    return {"refresh_seconds": REFRESH_SECONDS, "sms_enabled": auth.SMS_ENABLED}


# ---------------------------------------------------------------------------
# Sensor helpers
# ---------------------------------------------------------------------------

def _age_seconds(timestamp_str):
    try:
        ts = datetime.fromisoformat(timestamp_str)
        return max(0, int((datetime.utcnow() - ts).total_seconds()))
    except (ValueError, TypeError):
        return None


def record_reading():
    """Return the latest REAL ESP32 reading. Never fabricate simulation data."""
    settings = get_settings()
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sensor_readings WHERE source='esp32' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    if row:
        reading = dict(row)
        age = _age_seconds(reading.get("timestamp"))
        connected = age is not None and age <= 20
        reading["has_reading"] = True
        reading["connected"] = connected
        reading["esp32_disconnected"] = not connected
        reading["last_seen_seconds"] = age
    else:
        # Neutral placeholders only until the first physical sensor packet arrives.
        # They are explicitly marked unavailable and are never stored as readings.
        reading = {
            "source": "esp32", "temperature": 0.0, "humidity": 0.0,
            "soil_moisture_raw": 0.0, "soil_moisture_pct": 0.0,
            "rain_raw": 4095.0, "slope_deg": None, "timestamp": None,
            "has_reading": False, "connected": False,
            "esp32_disconnected": True, "last_seen_seconds": None,
        }

    reading["rain_status"] = "RAIN" if reading["rain_raw"] < settings["rain_raw_threshold"] else "NO_RAIN"
    reading["terrain_status"] = "UNAVAILABLE" if reading["slope_deg"] is None else ("MOVEMENT_DETECTED" if reading["slope_deg"] > 25 else "STABLE")
    return reading, settings


def _recent(timestamp_str, max_age_seconds=20):
    age = _age_seconds(timestamp_str)
    return age is not None and age <= max_age_seconds


def _store_reading(conn, reading):
    settings = get_settings()
    conn.execute(
        "INSERT INTO sensor_readings "
        "(source, temperature, humidity, soil_moisture_raw, soil_moisture_pct, "
        " rain_raw, rain_status, slope_deg, terrain_status, timestamp) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "esp32",
            reading["temperature"], reading["humidity"],
            reading["soil_moisture_raw"], reading["soil_moisture_pct"],
            reading["rain_raw"],
            "RAIN" if reading["rain_raw"] < settings["rain_raw_threshold"] else "NO_RAIN",
            reading.get("slope_deg"),
            "UNAVAILABLE",
            reading["timestamp"],
        ),
    )
    conn.commit()


def apply_irrigation(reading, settings):
    if not reading.get("has_reading"):
        return {
            "state": settings["pump_state"], "mode": settings["irrigation_mode"],
            "reason": "Waiting for the first ESP32 sensor packet before automatic irrigation can evaluate the field.",
            "rain_status": "NO_RAIN",
        }

    decision = agri_logic.irrigation_decision(
        reading["soil_moisture_pct"], reading["rain_raw"],
        settings["irrigation_mode"], settings["pump_state"], settings,
    )
    if decision["state"] != settings["pump_state"]:
        conn = get_db()
        conn.execute(
            "INSERT INTO pump_events (state, mode, reason, timestamp) VALUES (?,?,?,?)",
            (decision["state"], decision["mode"], decision["reason"], now()),
        )
        conn.commit()
        conn.close()
        update_settings(pump_state=decision["state"])
    return decision


# ---------------------------------------------------------------------------
# Auth routes: signup -> login -> OTP
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return redirect(url_for("dashboard") if "user_id" in session else url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not name or not contact or not password:
            flash("Please fill in all fields.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
        else:
            conn = get_db()
            existing = conn.execute("SELECT id FROM users WHERE contact=?", (contact,)).fetchone()
            if existing:
                flash("An account with this email/phone already exists.", "error")
                conn.close()
            else:
                conn.execute(
                    "INSERT INTO users (name, contact, password_hash, created_at) VALUES (?,?,?,?)",
                    (name, contact, auth.hash_password(password), now()),
                )
                conn.commit()
                conn.close()
                flash("Account created. Please log in.", "success")
                return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        contact = request.form.get("contact", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE contact=?", (contact,)).fetchone()
        conn.close()

        if user is None or not auth.verify_password(password, user["password_hash"]):
            flash("Invalid email/phone or password.", "error")
            return render_template("login.html")

        code = auth.create_otp(contact, purpose="login")
        sms_result = auth.send_otp_sms(contact, code)

        session["pending_contact"] = contact
        session["pending_user_id"] = user["id"]

        if sms_result["sent"]:
            flash(f"A verification code was sent to {contact}.", "success")
        else:
            flash("Demo mode: no SMS gateway configured, so your code is shown below.", "info")
            session["demo_otp"] = sms_result["demo_code"]

        return redirect(url_for("otp_verify"))

    return render_template("login.html")


@app.route("/otp", methods=["GET", "POST"])
def otp_verify():
    contact = session.get("pending_contact")
    if not contact:
        return redirect(url_for("login"))

    if request.method == "POST":
        code = request.form.get("otp", "")
        ok, message = auth.verify_otp(contact, code, purpose="login")
        if ok:
            session["user_id"] = session.pop("pending_user_id")
            session.pop("pending_contact", None)
            session.pop("demo_otp", None)
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))
        flash(message, "error")

    return render_template("otp.html", contact=contact, demo_otp=session.get("demo_otp"))


@app.route("/otp/resend")
def otp_resend():
    contact = session.get("pending_contact")
    if not contact:
        return redirect(url_for("login"))
    code = auth.create_otp(contact, purpose="login")
    result = auth.send_otp_sms(contact, code)
    if result["sent"]:
        flash("A new code was sent.", "success")
        session.pop("demo_otp", None)
    else:
        session["demo_otp"] = result["demo_code"]
        flash("Demo mode: new code shown below.", "info")
    return redirect(url_for("otp_verify"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Landing page — suitability / terrain / crop recommendation overview
# ---------------------------------------------------------------------------

@app.route("/landing")
@login_required
def landing():
    reading, settings = record_reading()
    rainfall = float(request.args.get("rainfall", DEFAULT_RAINFALL_MM))

    suitability = agri_logic.land_suitability(
        reading["temperature"], reading["humidity"], reading["soil_moisture_pct"],
        rainfall, None, None,
    )
    risk = agri_logic.terrain_risk(
        None, None, reading["rain_status"],
    )
    crops = agri_logic.recommend_crops(
        reading["temperature"], reading["soil_moisture_pct"], rainfall, None,
    )

    return render_template(
        "landing.html", reading=reading, suitability=suitability, risk=risk,
        crops=crops, rainfall=rainfall,
    )


# ---------------------------------------------------------------------------
# Dashboard — live monitoring
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    reading, settings = record_reading()
    irrigation = apply_irrigation(reading, settings)
    settings = get_settings()  # re-fetch after possible pump_state update

    conn = get_db()
    alerts = build_alerts(reading, irrigation)
    conn.close()

    return render_template(
        "dashboard.html", reading=reading, irrigation=irrigation,
        settings=settings, alerts=alerts,
    )


def build_alerts(reading, irrigation):
    alerts = []
    if reading["soil_moisture_pct"] < 25:
        alerts.append({"level": "warning", "text": "Low soil moisture detected — irrigation may be required."})
    if irrigation["rain_status"] == "RAIN":
        alerts.append({"level": "info", "text": "Rain detected — irrigation suspended."})
    if reading.get("slope_deg") is not None and reading["slope_deg"] > 25:
        alerts.append({"level": "critical", "text": "Terrain-risk indication is high — inspect terrain conditions."})
    if not reading.get("has_reading"):
        alerts.append({"level": "critical", "text": "Waiting for ESP32 — no hardware sensor packet has been received yet."})
    elif reading.get("esp32_disconnected"):
        alerts.append({"level": "warning", "text": "ESP32 is offline — the dashboard is showing the last REAL hardware reading, not simulated data."})
    return alerts


# ---------------------------------------------------------------------------
# Irrigation control (auto / manual)
# ---------------------------------------------------------------------------

@app.route("/irrigation", methods=["GET", "POST"])
@login_required
def irrigation_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "set_mode":
            update_settings(irrigation_mode=request.form.get("mode", "AUTO"))
        elif action == "pump_on":
            update_settings(irrigation_mode="MANUAL", pump_state="ON")
            conn = get_db()
            conn.execute("INSERT INTO pump_events (state, mode, reason, timestamp) VALUES (?,?,?,?)",
                         ("ON", "MANUAL", "Manual mode — pump turned ON by user.", now()))
            conn.commit(); conn.close()
        elif action == "pump_off":
            update_settings(irrigation_mode="MANUAL", pump_state="OFF")
            conn = get_db()
            conn.execute("INSERT INTO pump_events (state, mode, reason, timestamp) VALUES (?,?,?,?)",
                         ("OFF", "MANUAL", "Manual mode — pump turned OFF by user.", now()))
            conn.commit(); conn.close()
        return redirect(url_for("irrigation_page"))

    reading, settings = record_reading()
    irrigation = apply_irrigation(reading, settings)
    settings = get_settings()

    conn = get_db()
    history = conn.execute("SELECT * FROM pump_events ORDER BY id DESC LIMIT 15").fetchall()
    conn.close()

    return render_template("irrigation.html", reading=reading, irrigation=irrigation,
                            settings=settings, history=history)


# ---------------------------------------------------------------------------
# Crop health — disease & pest detection
# ---------------------------------------------------------------------------

@app.route("/crop-health", methods=["GET", "POST"])
@login_required
def crop_health():
    result = None
    if request.method == "POST":
        analysis_type = request.form.get("analysis_type", "disease")
        file = request.files.get("image")

        if not file or file.filename == "":
            flash("Please choose an image to upload.", "error")
        else:
            filename = secure_filename(file.filename)
            save_path = os.path.join(UPLOAD_DIR, f"{int(datetime.utcnow().timestamp())}_{filename}")
            file.save(save_path)

            settings = get_settings()
            classification = ai_inference.classify(save_path, analysis_type)

            if classification.get("error"):
                if classification.get("error_type") == "model_unavailable":
                    flash(classification.get("message", "Real AI model is not installed."), "error")
                elif classification.get("error_type") == "inference_failed":
                    flash(classification.get("message", "AI inference failed."), "error")
                else:
                    flash("That file doesn't look like a valid image. Please try again.", "error")
            else:
                confidence = classification["confidence"]
                label = ai_inference.confidence_label(confidence, settings)
                recommendation = ai_inference.recommendation_for(
                    analysis_type, classification["prediction"], confidence, settings)

                conn = get_db()
                conn.execute(
                    "INSERT INTO crop_analysis (image_path, analysis_type, prediction, confidence, recommendation, timestamp) "
                    "VALUES (?,?,?,?,?,?)",
                    (save_path, analysis_type, classification["prediction"], confidence, recommendation, now()),
                )
                conn.commit()
                conn.close()

                result = {
                    "prediction": classification["prediction"],
                    "confidence": confidence,
                    "label": label,
                    "recommendation": recommendation,
                    "is_mock": classification["is_mock"],
                    "analysis_type": analysis_type,
                    "image_url": url_for("uploaded_file", filename=os.path.basename(save_path)),
                }

    conn = get_db()
    history = conn.execute("SELECT * FROM crop_analysis ORDER BY id DESC LIMIT 10").fetchall()
    conn.close()

    return render_template("crop_health.html", result=result, history=history)


@app.route("/uploads/<filename>")
@login_required
def uploaded_file(filename):
    return send_file(os.path.join(UPLOAD_DIR, filename))


# ---------------------------------------------------------------------------
# Farmer advisory
# ---------------------------------------------------------------------------

@app.route("/advisory")
@login_required
def advisory():
    reading, settings = record_reading()
    irrigation = apply_irrigation(reading, settings)
    rainfall = DEFAULT_RAINFALL_MM

    suitability = agri_logic.land_suitability(
        reading["temperature"], reading["humidity"], reading["soil_moisture_pct"],
        rainfall, None, None,
    )
    risk = agri_logic.terrain_risk(
        None, None, reading["rain_status"],
    )
    crops = agri_logic.recommend_crops(
        reading["temperature"], reading["soil_moisture_pct"], rainfall, None,
    )
    top_crop = crops[0] if crops else None
    tips = agri_logic.build_advisory(reading, suitability, risk, irrigation, top_crop)

    return render_template("advisory.html", reading=reading, suitability=suitability,
                            risk=risk, tips=tips, top_crop=top_crop)


# ---------------------------------------------------------------------------
# Analytics — server-rendered charts (no JS charting library)
# ---------------------------------------------------------------------------

@app.route("/analytics")
@login_required
def analytics():
    return render_template("analytics.html")


@app.route("/chart/<metric>.png")
@login_required
def chart(metric):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sensor_readings ORDER BY id DESC LIMIT 60"
    ).fetchall()
    conn.close()
    rows = list(reversed(rows))

    times = [r["timestamp"][11:19] for r in rows]  # HH:MM:SS
    metric_map = {
        "temperature": ("Temperature (°C)", [r["temperature"] for r in rows], "#d97757"),
        "humidity": ("Humidity (%)", [r["humidity"] for r in rows], "#3b82c4"),
        "soil": ("Soil Moisture (%)", [r["soil_moisture_pct"] for r in rows], "#4a7c59"),
        "rain": ("Rain Sensor Raw Value", [r["rain_raw"] for r in rows], "#a0522d"),
    }
    title, values, color = metric_map.get(metric, metric_map["temperature"])

    fig, ax = plt.subplots(figsize=(7, 3), dpi=110)
    if values:
        ax.plot(times, values, color=color, linewidth=2)
        ax.fill_between(times, values, color=color, alpha=0.12)
    ax.set_title(title, fontsize=11, loc="left", color="#2b2b26")
    ax.tick_params(axis="x", rotation=60, labelsize=6)
    ax.tick_params(axis="y", labelsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    if request.method == "POST":
        update_settings(
            soil_dry_threshold=float(request.form.get("soil_dry_threshold", 30)),
            soil_wet_threshold=float(request.form.get("soil_wet_threshold", 60)),
            rain_raw_threshold=float(request.form.get("rain_raw_threshold", 2000)),
            disease_conf_high=float(request.form.get("disease_conf_high", 80)),
            disease_conf_mid=float(request.form.get("disease_conf_mid", 50)),
        )
        flash("Settings updated.", "success")
        return redirect(url_for("settings_page"))

    return render_template("settings.html", settings=get_settings())


# ---------------------------------------------------------------------------
# ESP32 hardware API — point your real board's HTTP client at this route
# ---------------------------------------------------------------------------

@app.route("/api/sensors", methods=["POST"])
def api_sensors_ingest():
    """Receive a real sensor packet and return the relay command to the ESP32."""
    data = request.get_json(silent=True) or {}
    device_key = (
        request.headers.get("X-Device-Key")
        or request.args.get("device_key")
        or data.get("device_key")
    )

    if device_key != DEVICE_API_KEY:
        return jsonify({"error": "Unauthorized ESP32 device"}), 401
    required = ["temperature", "humidity", "soil_moisture_raw", "soil_moisture_pct", "rain_raw"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Missing fields, expected {required} and optional rain_detected"}), 400

    try:
        clean = {k: float(data[k]) for k in required}
    except (TypeError, ValueError):
        return jsonify({"error": "Required sensor fields must be numeric"}), 400

    if not (-20 <= clean["temperature"] <= 80 and 0 <= clean["humidity"] <= 100 and
            0 <= clean["soil_moisture_raw"] <= 4095 and 0 <= clean["soil_moisture_pct"] <= 100 and
            0 <= clean["rain_raw"] <= 4095):
        return jsonify({"error": "Sensor packet contains out-of-range values"}), 422

    # Slope is intentionally unavailable in the current hardware setup.
    # Keep the database column nullable for backward compatibility.
    clean["slope_deg"] = None

    clean["source"] = "esp32"
    clean["timestamp"] = now()
    conn = get_db()
    _store_reading(conn, clean)
    conn.close()

    settings = get_settings()
    live = dict(clean)
    live["has_reading"] = True
    decision = apply_irrigation(live, settings)
    settings = get_settings()

    return jsonify({
        "status": "ok",
        "server_time": clean["timestamp"],
        "pump": {"state": settings["pump_state"], "mode": settings["irrigation_mode"], "reason": decision["reason"]},
        "thresholds": {
            "soil_dry_pct": settings["soil_dry_threshold"],
            "soil_wet_pct": settings["soil_wet_threshold"],
            "rain_raw": settings["rain_raw_threshold"],
        },
    })


@app.route("/api/device/control")
def api_device_control():
    device_key = (
        request.headers.get("X-Device-Key")
        or request.args.get("device_key")
    )

    if device_key != DEVICE_API_KEY:
        return jsonify({"error": "Unauthorized ESP32 device"}), 401

    settings = get_settings()
    return jsonify({
        "pump_state": settings["pump_state"],
        "irrigation_mode": settings["irrigation_mode"],
        "soil_dry_threshold": settings["soil_dry_threshold"],
        "soil_wet_threshold": settings["soil_wet_threshold"],
        "rain_raw_threshold": settings["rain_raw_threshold"],
    })


@app.route("/api/live")
@login_required
def api_live():
    reading, settings = record_reading()
    irrigation = apply_irrigation(reading, settings)
    return jsonify({"reading": reading, "irrigation": irrigation})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
