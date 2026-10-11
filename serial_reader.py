import serial
import requests
import json
import time
import threading


# =====================================================
# AGROGUARD AI
# ESP32 <-> COM7 <-> FLASK
# =====================================================

COM_PORT = "COM7"
BAUD_RATE = 115200

SERVER_URL = "http://127.0.0.1:5000"

SENSOR_API = f"{SERVER_URL}/api/sensors"
CONTROL_API = f"{SERVER_URL}/api/device/control"


# =====================================================
# IMPORTANT
# =====================================================
# This MUST be the same key configured in app.py
# =====================================================

DEVICE_KEY = "agroguard-esp32-2026"


# =====================================================
# GLOBAL VARIABLES
# =====================================================

ser = None

running = True

last_command = None


# =====================================================
# CONNECT TO ESP32
# =====================================================

def connect_serial():

    global ser

    while running:

        try:

            print(
                f"[SERIAL] Connecting to {COM_PORT}..."
            )

            ser = serial.Serial(
                port=COM_PORT,
                baudrate=BAUD_RATE,
                timeout=1
            )

            time.sleep(2)

            print(
                f"[SERIAL] Connected to {COM_PORT}"
            )

            return True

        except Exception as e:

            print(
                f"[SERIAL] Connection failed: {e}"
            )

            print(
                "[SERIAL] Retrying in 3 seconds..."
            )

            time.sleep(3)

    return False


# =====================================================
# SEND COMMAND TO ESP32
# =====================================================

def send_command(command):

    global ser

    if ser is None or not ser.is_open:

        return False

    try:

        json_command = json.dumps(
            command,
            separators=(",", ":")
        )

        ser.write(
            (
                json_command + "\n"
            ).encode("utf-8")
        )

        ser.flush()

        print(
            f"✓ Pump command -> "
            f"{command['pump_state']} | "
            f"Mode -> {command['irrigation_mode']}"
        )

        return True

    except Exception as e:

        print(
            f"✗ Failed to send command to ESP32: {e}"
        )

        return False


# =====================================================
# GET CONTROL COMMAND FROM FLASK
# =====================================================

def get_control_command():

    try:

        response = requests.get(
            CONTROL_API,
            headers={
                "X-Device-Key": DEVICE_KEY
            },
            timeout=3
        )

        if response.status_code == 401:

            print(
                "✗ Flask rejected device key (401)."
            )

            print(
                "✗ Check DEVICE_KEY in app.py "
                "and serial_reader.py."
            )

            return None

        if response.status_code != 200:

            print(
                f"✗ Flask control response: "
                f"{response.status_code}"
            )

            return None

        data = response.json()

        pump_state = str(
            data.get(
                "pump_state",
                "OFF"
            )
        ).upper()

        irrigation_mode = str(
            data.get(
                "irrigation_mode",
                "AUTO"
            )
        ).upper()

        soil_dry_pct = int(
            data.get(
                "soil_dry_pct",
                data.get("soil_dry_threshold", 30)
            )
        )

        soil_wet_pct = int(
            data.get(
                "soil_wet_pct",
                data.get("soil_wet_threshold", 60)
            )
        )

        rain_threshold_raw = int(
            data.get(
                "rain_threshold_raw",
                data.get("rain_raw_threshold", 2000)
            )
        )

        if pump_state not in [
            "ON",
            "OFF"
        ]:

            pump_state = "OFF"

        if irrigation_mode not in [
            "AUTO",
            "MANUAL"
        ]:

            irrigation_mode = "AUTO"

        return {

            "pump_state":
                pump_state,

            "irrigation_mode":
                irrigation_mode,

            "soil_dry_pct":
                soil_dry_pct,

            "soil_wet_pct":
                soil_wet_pct,

            "rain_threshold_raw":
                rain_threshold_raw
        }

    except requests.exceptions.ConnectionError:

        print(
            "✗ Cannot connect to Flask."
        )

        return None

    except requests.exceptions.Timeout:

        print(
            "✗ Flask request timed out."
        )

        return None

    except Exception as e:

        print(
            f"✗ Control error: {e}"
        )

        return None


# =====================================================
# CONTROL LOOP
# =====================================================

def control_loop():

    global last_command

    print(
        "[CONTROL] Pump control loop started."
    )

    while running:

        try:

            command = get_control_command()

            if command is not None:

                if command != last_command:

                    print()
                    print(
                        "-----------------------------------"
                    )

                    print(
                        "Dashboard control:"
                    )

                    print(
                        f"Pump: "
                        f"{command['pump_state']}"
                    )

                    print(
                        f"Mode: "
                        f"{command['irrigation_mode']}"
                    )

                    print(
                        "-----------------------------------"
                    )

                    if send_command(command):

                        last_command = (
                            command.copy()
                        )

            time.sleep(0.5)

        except Exception as e:

            print(
                f"[CONTROL] Loop error: {e}"
            )

            time.sleep(1)


# =====================================================
# SEND SENSOR DATA TO FLASK
# =====================================================

def send_sensor_data(sensor_data):

    try:

        payload = {

            "temperature":
                sensor_data[
                    "temperature"
                ],

            "humidity":
                sensor_data[
                    "humidity"
                ],

            "soil_moisture_raw":
                sensor_data[
                    "soil_moisture_raw"
                ],

            "soil_moisture_pct":
                sensor_data[
                    "soil_moisture_pct"
                ],

            "rain_raw":
                sensor_data[
                    "rain_raw"
                ],

            "rain_detected":
                sensor_data.get(
                    "rain_detected",
                    False
                )
        }

        print(
            "Sending data to AgroGuard..."
        )

        response = requests.post(
            SENSOR_API,
            json=payload,
            headers={
                "X-Device-Key": DEVICE_KEY
            },
            timeout=3
        )

        print(
            f"Flask response: "
            f"{response.status_code}"
        )

        if response.status_code == 401:

            print(
                "✗ Unauthorized ESP32 device."
            )

            print(
                "✗ DEVICE_KEY mismatch."
            )

            return

        if response.status_code == 200:

            print(
                "✓ Data sent successfully!"
            )

        else:

            print(
                "✗ Flask rejected sensor data"
            )

            print(
                response.text
            )

    except KeyError as e:

        print(
            f"✗ Missing sensor field: {e}"
        )

    except requests.exceptions.ConnectionError:

        print(
            "✗ Cannot connect to Flask."
        )

    except requests.exceptions.Timeout:

        print(
            "✗ Flask request timed out."
        )

    except Exception as e:

        print(
            f"✗ Sensor send error: {e}"
        )


# =====================================================
# VALIDATE SENSOR PACKET
# =====================================================

def validate_sensor_packet(data):

    required_fields = [

        "temperature",

        "humidity",

        "soil_moisture_raw",

        "soil_moisture_pct",

        "rain_raw",

        "rain_detected",

        "pump_state",

        "irrigation_mode"
    ]

    for field in required_fields:

        if field not in data:

            print(
                f"✗ Missing field from ESP32: "
                f"{field}"
            )

            return False

    return True


# =====================================================
# PROCESS ESP32 JSON
# =====================================================

def process_json_line(line):

    line = line.strip()

    if not line:

        return

    try:

        data = json.loads(line)

    except json.JSONDecodeError:

        print()
        print(
            "✗ Invalid JSON received from ESP32:"
        )

        print(
            line
        )

        return

    packet_type = data.get(
        "type",
        ""
    )


    # =================================================
    # SENSOR DATA
    # =================================================

    if packet_type == "sensor":

        print()
        print(
            "------------------------------------------------------------"
        )

        print(
            "Received from ESP32:"
        )

        print(
            json.dumps(
                data,
                indent=2
            )
        )

        if not validate_sensor_packet(data):

            print(
                "✗ Invalid sensor packet."
            )

            print(
                "------------------------------------------------------------"
            )

            return

        print(
            "✓ JSON received successfully!"
        )

        send_sensor_data(
            data
        )

        print(
            "------------------------------------------------------------"
        )


    # =================================================
    # COMMAND ACK
    # =================================================

    elif packet_type == "command_ack":

        print()
        print(
            "✓ Pump command acknowledged by ESP32:"
        )

        print(
            json.dumps(
                data,
                indent=2
            )
        )

        # IMPORTANT:
        # DO NOT send command_ack to /api/sensors


    # =================================================
    # STARTUP
    # =================================================

    elif packet_type == "startup":

        print()
        print(
            "✓ ESP32 startup:"
        )

        print(
            json.dumps(
                data,
                indent=2
            )
        )


    # =================================================
    # STATUS
    # =================================================

    elif packet_type == "status":

        print()
        print(
            "✓ ESP32 status:"
        )

        print(
            json.dumps(
                data,
                indent=2
            )
        )


    # =================================================
    # UNKNOWN
    # =================================================

    else:

        print(
            "⚠ Unknown JSON packet:"
        )

        print(
            json.dumps(
                data,
                indent=2
            )
        )


# =====================================================
# SERIAL LOOP
# =====================================================

def serial_loop():

    global ser

    if not connect_serial():

        return

    print()
    print(
        "============================================================"
    )

    print(
        "             AGROGUARD AI SERIAL READER"
    )

    print(
        "============================================================"
    )

    print(
        f"COM PORT : {COM_PORT}"
    )

    print(
        f"BAUD     : {BAUD_RATE}"
    )

    print(
        f"SERVER   : {SERVER_URL}"
    )

    print(
        f"DEVICE   : {DEVICE_KEY}"
    )

    print(
        "============================================================"
    )

    print()

    while running:

        try:

            if (
                ser is None or
                not ser.is_open
            ):

                print(
                    "[SERIAL] Connection lost."
                )

                if not connect_serial():

                    time.sleep(2)

                    continue

            if ser.in_waiting > 0:

                line = (
                    ser.readline()
                    .decode(
                        "utf-8",
                        errors="ignore"
                    )
                    .strip()
                )

                if line:

                    process_json_line(
                        line
                    )

            else:

                time.sleep(0.05)

        except serial.SerialException as e:

            print(
                f"✗ Serial error: {e}"
            )

            try:

                if ser:

                    ser.close()

            except Exception:
                pass

            ser = None

            time.sleep(2)

        except KeyboardInterrupt:

            break

        except Exception as e:

            print(
                f"✗ Serial loop error: {e}"
            )

            time.sleep(1)


# =====================================================
# MAIN
# =====================================================

def main():

    global running

    control_thread = threading.Thread(
        target=control_loop,
        daemon=True
    )

    control_thread.start()

    try:

        serial_loop()

    except KeyboardInterrupt:

        print(
            "\nStopping AgroGuard..."
        )

    finally:

        running = False

        try:

            if ser and ser.is_open:

                ser.close()

        except Exception:
            pass

        print(
            "Serial reader stopped."
        )


# =====================================================
# START
# =====================================================

if __name__ == "__main__":

    main()