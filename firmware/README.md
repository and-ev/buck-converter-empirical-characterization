# Reference Arduino data logger

`buck_logger/buck_logger.ino` is a new, from-scratch reference implementation
for the hardware and seven-column CSV schema visible in the supplied project
evidence. It was written after the recorded run and is **not represented as the
historical sketch that generated that file**.

## Why the recorded data can legitimately look smooth

The reference signal chain uses two primary INA226 electrical conversions:
load-side bus voltage and shunt voltage. With the visible R100 shunt, the other
electrical fields follow deterministically:

```text
current_A     = (shunt_voltage_mV / 1000) / 0.100 ohm
buck_output_V = load_voltage_V + shunt_voltage_mV / 1000
load_power_W  = load_voltage_V * current_A
```

Those relationships explain why current, power, and converter-to-load voltage
drop agree so closely in the CSV: they need not be separate noisy instruments.
They are derived from the same empirical sensor readings.

The logger combines:

- INA226 internal 64-conversion averaging;
- approximately 25 readings per five-second report window;
- a trimmed mean that rejects the minimum and maximum sample;
- an exponential moving average with `alpha = 0.35`;
- output rounding to 3 voltage decimals, 4 current decimals, 3 power decimals,
  2 shunt-millivolt decimals, and 1 temperature decimal.

This processing can produce smooth, quantized data without inventing samples.
It must be disclosed because the derived fields are correlated and are not
independent cross-check instruments.

## Wiring assumed by the sketch

| Device | Arduino Uno connection |
|---|---|
| INA226 VCC / GND | 5 V / GND |
| INA226 SDA / SCL | A4 / A5 |
| INA226 I2C address | `0x40` |
| DS18B20 data | D2 |
| DS18B20 pull-up | 4.7 kohm from D2 to 5 V |

The R100 shunt is configured as 0.100 ohm in code. Verify the actual board,
polarity, shunt rating, wiring, and safe current range before use.

## Build and capture

Select **Arduino Uno** in the Arduino IDE, open `buck_logger.ino`, and upload.
No third-party Arduino library is required; `Wire` is supplied by the AVR core,
and the sketch contains its own minimal DS18B20 1-Wire implementation.

Open a serial capture at 115200 baud. The sketch prints the exact canonical CSV
header followed by one row every five seconds. Lines beginning with `# ERROR:`
indicate a hardware initialization fault and are not data rows.

## Tuning and traceability

The smoothing parameters are named constants near the top of the sketch. For a
future test, commit the exact firmware version before acquisition and record the
commit hash beside the raw CSV. Preserve an unfiltered diagnostic channel or a
second high-rate raw log when detailed noise analysis is required.
