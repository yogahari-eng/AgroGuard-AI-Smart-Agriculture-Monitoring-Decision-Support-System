# AgroGuard AI — Real ESP32 Hardware + Flask Web System

AgroGuard AI is an agriculture monitoring and irrigation project that connects a physical **ESP32 Dev Module / ESP32-D0WD-V3** to a Flask web dashboard. The sensor dashboard is now **hardware-only**: there is no simulated sensor generator and no automatic fallback to fake values.

## Hardware used

- ESP32 Dev Module / ESP32-D0WD-V3 — controller + Wi-Fi
- DHT22 — temperature and humidity
- Capacitive Soil Moisture Sensor — analog soil moisture
- Rain Sensor (4-pin module, analog output) — rain detection
- Relay Module — ESP32-controlled pump switch
- Mini Water Pump (3–9V)
- Breadboard and jumper wires
- External/appropriate power source for pump

See **HARDWARE_WIRING.md** for the exact wiring table and power notes.

## Architecture

```text
DHT22 ─┐
Soil ──┤
Rain ──┼──> ESP32 ──Wi-Fi/HTTP──> Flask API ──> SQLite ──> Web Dashboard
(no slope sensor)                         │
                                      └── Irrigation decision
                                               │
ESP32 <──── pump state/mode/thresholds ────────┘
  │
Relay ──> Mini Pump
```

The ESP32 POSTs one real sensor packet about every 4 seconds. Flask stores it, evaluates irrigation rules, and sends the requested relay state back in the API response. If Wi-Fi or the server temporarily fails, the ESP32 keeps a local safety-first irrigation fallback.

## 1. Run the web application on Windows

Open Command Prompt or the VS Code terminal inside the extracted `agroguard-ai` folder:

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

For ESP32 access, Windows Firewall must allow Python/Flask on your **Private network**.

## 2. Find the PC IPv4 address

On the Flask computer:

```bat
ipconfig
```

Find the active Wi-Fi adapter's **IPv4 Address**, for example:

```text
192.168.1.100
```

The PC and ESP32 must be on the same Wi-Fi network or phone hotspot.

## 3. Configure the ESP32 firmware

Open:

```text
esp32/agroguard_esp32.ino
```

Edit these values:

```cpp
const char* WIFI_SSID      = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD  = "YOUR_WIFI_PASSWORD";
const char* SENSOR_API_URL = "http://192.168.1.100:5000/api/sensors";
const char* DEVICE_API_KEY = "agroguard-esp32-2026";
```

Replace `192.168.1.100` with your PC's real IPv4 address.

### Arduino IDE libraries

Install through **Library Manager**:

- DHT sensor library by Adafruit
- Adafruit Unified Sensor
- - ArduinoJson

Install/select the ESP32 board package, choose **ESP32 Dev Module**, select the correct COM port, then upload the sketch.

Open Serial Monitor at **115200 baud**. You should see real temperature, humidity, soil raw/percentage, rain raw/status, slope, pump state, and HTTP status.

## 4. Device API security

The firmware sends:

```text
X-Device-Key: agroguard-esp32-2026
```

Flask expects the same key. For a stronger key on Windows, run Flask like this:

```bat
set AGROGUARD_DEVICE_KEY=my-long-private-device-key
python app.py
```

Then put the exact same value in `DEVICE_API_KEY` inside the `.ino` file and upload again.

## 5. Live sensor packet

ESP32 sends JSON to:

```text
POST /api/sensors
```

Example:

```json
{
  "temperature": 30.4,
  "humidity": 65.2,
  "soil_moisture_raw": 2210,
  "soil_moisture_pct": 43.9,
  "rain_raw": 3740,
  }
```

Flask validates numeric ranges, stores the packet in SQLite, and responds with the current irrigation command and thresholds.

## 6. Automatic irrigation logic

Safety-first rule order:

```text
IF rain detected              -> Pump OFF (hard safety interlock)
ELSE IF MANUAL mode           -> Use requested web pump state
ELSE IF soil < dry threshold  -> Pump ON
ELSE IF soil > wet threshold  -> Pump OFF
ELSE                           -> Hold previous state (hysteresis)
```

The default thresholds are:

- Dry: 30%
- Wet: 60%
- Rain raw threshold: 2000 (lower = rain)

Change them from **Settings** in the web interface. The ESP32 receives updated thresholds from the server automatically.

## 7. Manual pump control from the web

Go to:

```text
/irrigation
```

Choose **Manual**, then Turn Pump ON/OFF. The database state changes immediately and the next ESP32 sensor sync applies that command to GPIO 26. Rain remains a safety override and forces the pump OFF.

## 8. Soil moisture calibration

The conversion to percentage happens on the ESP32. In `agroguard_esp32.ino`:

```cpp
int SOIL_DRY_RAW = 3000;
int SOIL_WET_RAW = 1200;
```

These are example calibration values only. Use Serial Monitor to measure your own dry and wet raw readings, then replace them.

## 9. Real AI disease/pest detection

Random/mock disease and pest predictions have been removed. For real image inference, add:

```text
ai/models/crop_disease_model.keras
ai/models/pest_model.keras
ai/models/disease_class_names.txt
ai/models/pest_class_names.txt
```

Then install the optional AI dependency:

```bat
pip install -r requirements-ai.txt
```

If a model is missing, Crop Health tells you that the real model is unavailable instead of generating a fake prediction.

## 10. Pages

| Page | Function |
|---|---|
| Dashboard | Latest physical sensor data + hardware connection status |
| Land & Terrain | Land suitability + sensor-based terrain-risk screening |
| Irrigation | Automatic/manual physical pump control |
| Crop Health | Real Keras disease/pest inference when model files are installed |
| Advisory | Farmer guidance based on live readings |
| Analytics | Historical ESP32 sensor charts |
| Settings | Irrigation/rain/AI thresholds |

## 11. Important power safety

- Never power the pump directly from an ESP32 GPIO.
- Use the relay to switch the pump's own suitable power source.
- A rectangular 9V 6F22 battery normally has poor motor-current capability.
- Do not apply raw 9V to the ESP32 3.3V pin.
- For the prototype, USB/regulated 5V for the ESP32 and a suitable separate pump supply is safer.
- Verify your relay module voltage and active-LOW/active-HIGH behavior before connecting the pump.

## 12. Terrain interpretation

The current hardware setup has **no slope/tilt sensor**. AgroGuard AI does not fabricate slope values or claim professional landslide prediction.

## Project structure

```text
agroguard-ai/
├── app.py
├── database.py
├── agri_logic.py
├── ai_inference.py
├── auth.py
├── requirements.txt
├── requirements-ai.txt
├── HARDWARE_WIRING.md
├── esp32/
│   └── agroguard_esp32.ino
├── ai/models/
├── templates/
├── static/
└── uploads/
```

## USB / COM7 hardware mode

The current final prototype uses a simple USB serial bridge instead of Wi-Fi:

```text
ESP32 sensors
    ↓ USB
COM7
    ↓
serial_reader.py
    ↓ HTTP POST
Flask /api/sensors
    ↓
SQLite + Dashboard
```

Run Flask first, then `python serial_reader.py`. Close Arduino Serial Monitor before starting the bridge.
The ESP32 sends `temperature`, `humidity`, `soil_moisture_raw`, `soil_moisture_pct`, `rain_raw`, and `rain_detected`. No slope/tilt sensor is used in the current hardware path.
