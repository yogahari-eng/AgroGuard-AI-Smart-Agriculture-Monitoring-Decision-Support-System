const int IR_SENSOR_PIN = 27;

void setup() {
  Serial.begin(115200);
  pinMode(IR_SENSOR_PIN, INPUT);
}

void loop() {
  int value = digitalRead(IR_SENSOR_PIN);

  Serial.print("IR OUT = ");
  Serial.println(value);

  delay(300);
}