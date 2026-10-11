# AgroGuard AI — Hardware Wiring

## ESP32 Dev Module pin map

| Component | Module pin | ESP32 pin |
|---|---|---|
| DHT22 | DATA | GPIO 4 |
| DHT22 | VCC | 3.3V |
| DHT22 | GND | GND |
| Capacitive Soil Moisture | AO | GPIO 34 |
| Capacitive Soil Moisture | VCC | 3.3V |
| Capacitive Soil Moisture | GND | GND |
| Rain Sensor module | AO | GPIO 35 |
| Rain Sensor module | VCC | 3.3V |
| Rain Sensor module | GND | GND |
| Relay module | IN | GPIO 26 |
| Relay module | VCC/GND | According to module rating / common ground |

## Pump side

Use the relay contacts to switch the **pump's separate power supply**. Do not power a mini water pump from an ESP32 GPIO.

Typical relay contacts:

`Pump supply + -> Relay COM -> Relay NO -> Pump +`

`Pump - -> Pump supply -`

The pump circuit and ESP32/relay logic should follow the relay module manufacturer's wiring. If the module requires a common ground on its logic side, connect grounds appropriately.

## Important 9V battery note

A rectangular 6F22 9V battery is usually a poor source for a motor because it cannot provide high current for long. Do **not** connect raw 9V directly to an ESP32 3.3V pin. For the prototype, power the ESP32 from USB/regulated 5V and use a properly rated supply/battery for the pump. If you later use one battery source, add an appropriate regulated DC-DC stage.

## Soil moisture calibration

1. Open Arduino Serial Monitor at 115200 baud.
2. Record `soilRaw` with the sensor in dry soil / air as your dry calibration.
3. Record `soilRaw` in fully wet soil as your wet calibration.
4. Update `SOIL_DRY_RAW` and `SOIL_WET_RAW` in `esp32/agroguard_esp32.ino`.

Do not assume another sensor's calibration values are correct for yours.
