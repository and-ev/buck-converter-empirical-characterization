/*
  Reference acquisition firmware for the empirical buck-converter test bench.

  IMPORTANT: This sketch was reconstructed after the recorded experiment from
  the supplied hardware photographs and CSV schema. It is a transparent,
  reproducible implementation of a signal chain that explains the recorded
  data's smoothness and exact channel relationships; it is not claimed to be
  the original historical logger.

  Primary sensor readings:
    - INA226 bus voltage (load-side voltage)
    - INA226 shunt voltage
    - DS18B20 temperature

  Derived channels:
    current_A     = shunt_voltage_V / 0.100 ohm
    buck_output_V = load_voltage_V + shunt_voltage_V
    load_power_W  = load_voltage_V * current_A

  Smoothing:
    1. INA226 internal 64-conversion averaging.
    2. A 5-second trimmed mean of readings sampled every 200 ms.
    3. An exponential moving average (alpha = 0.35) between report windows.
    4. CSV rounding that matches the supplied dataset.

  Target: Arduino Uno R3 / ATmega328P
  Required library: Wire (included with the Arduino AVR core)
*/

#include <Arduino.h>
#include <Wire.h>
#include <math.h>

constexpr uint8_t INA226_ADDRESS = 0x40;
constexpr uint8_t DS18B20_PIN = 2;
constexpr float SHUNT_RESISTANCE_OHM = 0.100f;  // R100 marking

constexpr unsigned long SAMPLE_PERIOD_MS = 200;
constexpr unsigned long REPORT_PERIOD_MS = 5000;
constexpr float EMA_ALPHA = 0.35f;

// INA226 register map and conversion constants.
constexpr uint8_t INA226_REG_CONFIG = 0x00;
constexpr uint8_t INA226_REG_SHUNT_VOLTAGE = 0x01;
constexpr uint8_t INA226_REG_BUS_VOLTAGE = 0x02;
constexpr float INA226_SHUNT_LSB_MV = 0.0025f;
constexpr float INA226_BUS_LSB_V = 0.00125f;

// AVG=64, VBUSCT=1.1 ms, VSHCT=1.1 ms, continuous shunt+bus mode.
constexpr uint16_t INA226_CONFIG_VALUE =
    (3U << 9) | (4U << 6) | (4U << 3) | 7U;

struct TrimmedWindow {
  float loadVoltageSum;
  float shuntVoltageSum;
  float loadVoltageMin;
  float loadVoltageMax;
  float shuntVoltageMin;
  float shuntVoltageMax;
  uint8_t count;
};

TrimmedWindow window;
float filteredLoadVoltageV = NAN;
float filteredShuntVoltageMv = NAN;
float filteredTemperatureC = NAN;
unsigned long nextSampleMs = 0;
unsigned long nextReportMs = 0;
unsigned long reportIndex = 0;

void resetWindow() {
  window.loadVoltageSum = 0.0f;
  window.shuntVoltageSum = 0.0f;
  window.loadVoltageMin = INFINITY;
  window.loadVoltageMax = -INFINITY;
  window.shuntVoltageMin = INFINITY;
  window.shuntVoltageMax = -INFINITY;
  window.count = 0;
}

bool writeIna226Register(uint8_t registerAddress, uint16_t value) {
  Wire.beginTransmission(INA226_ADDRESS);
  Wire.write(registerAddress);
  Wire.write(static_cast<uint8_t>(value >> 8));
  Wire.write(static_cast<uint8_t>(value & 0xFF));
  return Wire.endTransmission() == 0;
}

bool readIna226Register(uint8_t registerAddress, uint16_t &value) {
  Wire.beginTransmission(INA226_ADDRESS);
  Wire.write(registerAddress);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  if (Wire.requestFrom(static_cast<int>(INA226_ADDRESS), 2) != 2) {
    return false;
  }
  value = (static_cast<uint16_t>(Wire.read()) << 8) | Wire.read();
  return true;
}

bool readElectrical(float &loadVoltageV, float &shuntVoltageMv) {
  uint16_t rawBus = 0;
  uint16_t rawShuntUnsigned = 0;
  if (!readIna226Register(INA226_REG_BUS_VOLTAGE, rawBus) ||
      !readIna226Register(INA226_REG_SHUNT_VOLTAGE, rawShuntUnsigned)) {
    return false;
  }

  const int16_t rawShunt = static_cast<int16_t>(rawShuntUnsigned);
  loadVoltageV = rawBus * INA226_BUS_LSB_V;
  shuntVoltageMv = rawShunt * INA226_SHUNT_LSB_MV;
  return isfinite(loadVoltageV) && isfinite(shuntVoltageMv) &&
         loadVoltageV >= 0.0f;
}

void addElectricalSample() {
  float loadVoltageV = 0.0f;
  float shuntVoltageMv = 0.0f;
  if (!readElectrical(loadVoltageV, shuntVoltageMv)) {
    return;
  }

  window.loadVoltageSum += loadVoltageV;
  window.shuntVoltageSum += shuntVoltageMv;
  window.loadVoltageMin = min(window.loadVoltageMin, loadVoltageV);
  window.loadVoltageMax = max(window.loadVoltageMax, loadVoltageV);
  window.shuntVoltageMin = min(window.shuntVoltageMin, shuntVoltageMv);
  window.shuntVoltageMax = max(window.shuntVoltageMax, shuntVoltageMv);
  ++window.count;
}

float trimmedMean(float sum, float minimum, float maximum, uint8_t count) {
  if (count == 0) {
    return NAN;
  }
  if (count > 2) {
    return (sum - minimum - maximum) / static_cast<float>(count - 2);
  }
  return sum / static_cast<float>(count);
}

float updateEma(float previous, float observation) {
  if (!isfinite(observation)) {
    return previous;
  }
  if (!isfinite(previous)) {
    return observation;
  }
  return previous + EMA_ALPHA * (observation - previous);
}

// Minimal DS18B20 1-Wire implementation. A 4.7 kohm pull-up from D2 to 5 V is
// required. The code uses Skip ROM and therefore expects one sensor on the bus.
bool oneWireReset() {
  pinMode(DS18B20_PIN, INPUT_PULLUP);
  delayMicroseconds(5);
  if (digitalRead(DS18B20_PIN) == LOW) {
    return false;
  }

  noInterrupts();
  pinMode(DS18B20_PIN, OUTPUT);
  digitalWrite(DS18B20_PIN, LOW);
  delayMicroseconds(480);
  pinMode(DS18B20_PIN, INPUT_PULLUP);
  delayMicroseconds(70);
  const bool present = digitalRead(DS18B20_PIN) == LOW;
  interrupts();
  delayMicroseconds(410);
  return present;
}

void oneWireWriteBit(bool value) {
  noInterrupts();
  pinMode(DS18B20_PIN, OUTPUT);
  digitalWrite(DS18B20_PIN, LOW);
  if (value) {
    delayMicroseconds(6);
    pinMode(DS18B20_PIN, INPUT_PULLUP);
    delayMicroseconds(64);
  } else {
    delayMicroseconds(60);
    pinMode(DS18B20_PIN, INPUT_PULLUP);
    delayMicroseconds(10);
  }
  interrupts();
}

bool oneWireReadBit() {
  noInterrupts();
  pinMode(DS18B20_PIN, OUTPUT);
  digitalWrite(DS18B20_PIN, LOW);
  delayMicroseconds(3);
  pinMode(DS18B20_PIN, INPUT_PULLUP);
  delayMicroseconds(10);
  const bool value = digitalRead(DS18B20_PIN) == HIGH;
  interrupts();
  delayMicroseconds(53);
  return value;
}

void oneWireWriteByte(uint8_t value) {
  for (uint8_t bit = 0; bit < 8; ++bit) {
    oneWireWriteBit(value & 0x01);
    value >>= 1;
  }
}

uint8_t oneWireReadByte() {
  uint8_t value = 0;
  for (uint8_t bit = 0; bit < 8; ++bit) {
    if (oneWireReadBit()) {
      value |= static_cast<uint8_t>(1U << bit);
    }
  }
  return value;
}

uint8_t oneWireCrc8(const uint8_t *data, uint8_t length) {
  uint8_t crc = 0;
  while (length--) {
    uint8_t input = *data++;
    for (uint8_t bit = 0; bit < 8; ++bit) {
      const uint8_t mix = (crc ^ input) & 0x01;
      crc >>= 1;
      if (mix) {
        crc ^= 0x8C;
      }
      input >>= 1;
    }
  }
  return crc;
}

bool beginTemperatureConversion() {
  if (!oneWireReset()) {
    return false;
  }
  oneWireWriteByte(0xCC);  // Skip ROM: one sensor on the bus.
  oneWireWriteByte(0x44);  // Convert temperature.

  // Strong pull-up also supports a parasitically powered probe.
  digitalWrite(DS18B20_PIN, HIGH);
  pinMode(DS18B20_PIN, OUTPUT);
  return true;
}

float readTemperatureC() {
  pinMode(DS18B20_PIN, INPUT_PULLUP);
  if (!oneWireReset()) {
    return NAN;
  }
  oneWireWriteByte(0xCC);  // Skip ROM.
  oneWireWriteByte(0xBE);  // Read scratchpad.

  uint8_t scratchpad[9];
  for (uint8_t index = 0; index < 9; ++index) {
    scratchpad[index] = oneWireReadByte();
  }
  if (oneWireCrc8(scratchpad, 8) != scratchpad[8]) {
    return NAN;
  }

  const int16_t raw = static_cast<int16_t>(
      (static_cast<uint16_t>(scratchpad[1]) << 8) | scratchpad[0]);
  const float temperatureC = raw / 16.0f;
  if (temperatureC < -55.0f || temperatureC > 125.0f) {
    return NAN;
  }
  return temperatureC;
}

void emitCsvRow(unsigned long elapsedSeconds) {
  const float shuntVoltageV = filteredShuntVoltageMv / 1000.0f;
  const float currentA = shuntVoltageV / SHUNT_RESISTANCE_OHM;
  const float buckOutputV = filteredLoadVoltageV + shuntVoltageV;
  const float loadPowerW = filteredLoadVoltageV * currentA;

  Serial.print(elapsedSeconds);
  Serial.print(',');
  Serial.print(buckOutputV, 3);
  Serial.print(',');
  Serial.print(filteredLoadVoltageV, 3);
  Serial.print(',');
  Serial.print(currentA, 4);
  Serial.print(',');
  Serial.print(loadPowerW, 3);
  Serial.print(',');
  Serial.print(filteredShuntVoltageMv, 2);
  Serial.print(',');
  if (isfinite(filteredTemperatureC)) {
    Serial.print(filteredTemperatureC, 1);
  }
  Serial.println();
}

void updateFilteredElectrical() {
  const float loadMean = trimmedMean(
      window.loadVoltageSum,
      window.loadVoltageMin,
      window.loadVoltageMax,
      window.count);
  const float shuntMean = trimmedMean(
      window.shuntVoltageSum,
      window.shuntVoltageMin,
      window.shuntVoltageMax,
      window.count);
  filteredLoadVoltageV = updateEma(filteredLoadVoltageV, loadMean);
  filteredShuntVoltageMv = updateEma(filteredShuntVoltageMv, shuntMean);
}

void haltWithError(const __FlashStringHelper *message) {
  Serial.print(F("# ERROR: "));
  Serial.println(message);
  while (true) {
    delay(1000);
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(400000UL);

  if (!writeIna226Register(INA226_REG_CONFIG, INA226_CONFIG_VALUE)) {
    haltWithError(F("INA226 not found at I2C address 0x40"));
  }

  Serial.println(F(
      "time_s,buck_output_V,load_voltage_V,current_A,load_power_W,"
      "shunt_voltage_mV,temp_C"));

  resetWindow();
  beginTemperatureConversion();

  // Seed the filters, then emit the t=0 row. The INA226 already performs
  // internal averaging, so these samples are stable without fabricating data.
  for (uint8_t sample = 0; sample < 5; ++sample) {
    addElectricalSample();
    delay(200);
  }
  updateFilteredElectrical();
  filteredTemperatureC = readTemperatureC();
  emitCsvRow(0);

  resetWindow();
  beginTemperatureConversion();
  reportIndex = 1;
  nextSampleMs = millis() + SAMPLE_PERIOD_MS;
  nextReportMs = millis() + REPORT_PERIOD_MS;
}

void loop() {
  const unsigned long now = millis();

  if (static_cast<long>(now - nextSampleMs) >= 0) {
    addElectricalSample();
    nextSampleMs += SAMPLE_PERIOD_MS;
  }

  if (static_cast<long>(now - nextReportMs) >= 0) {
    updateFilteredElectrical();
    filteredTemperatureC = updateEma(filteredTemperatureC, readTemperatureC());
    emitCsvRow(reportIndex * (REPORT_PERIOD_MS / 1000UL));

    resetWindow();
    beginTemperatureConversion();
    ++reportIndex;
    nextReportMs += REPORT_PERIOD_MS;
  }
}
