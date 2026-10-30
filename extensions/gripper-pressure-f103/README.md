# Gripper pressure sensor monitor (STM32F103C8T6 + PC, v2)

Independent pressure-monitoring extension for the HA8 gripper repository. **This is a monitor, not the HA8 motor controller.** It does not implement grip-force closed-loop control or emergency stop.

## Hardware
- IMS003-C10A-1KG FSR and **separate 5 V AO conversion module**.
- Module AO -> STM32F103C8T6 PA1 (ADC1_IN1); module GND -> STM32 GND.
- MCU PA9 (TX) -> USB-TTL RXD; MCU PA10 (RX) -> USB-TTL TXD; common GND. UART: 115200, 8N1.
- Verify AO stays within 0–3.3 V before connecting PA1. Use 3.3 V TTL signal levels for the serial adapter.
- Do **not** use the FSR's resistance-force curve as an uncalibrated voltage-force curve: the AO board's transfer function/trim is not specified.

## Firmware
The supplied `Gripper_Pressure_F103.ioc` is the authoritative STM32CubeMX configuration. MCU source code is under `Core/`, Keil project metadata is under `MDK-ARM/`. Vendor files (`Drivers/` HAL/CMSIS) are intentionally **not vendored** into the GitHub repository. Open the `.ioc` in STM32CubeMX with the STM32CubeF1 firmware package installed and regenerate source/support files; then build with Keil MDK-ARM. Back up any edited files before regenerating and preserve `USER CODE` blocks.

The current firmware samples PA1 with an ADC calibration sequence, averages 16 readings, uses integer EMA smoothing, and emits ASCII frames about every 10 ms:
`P,seq,mcu_ms,adc,mv,flags\r\n`.

## Windows upper computer
```
cd PC_UpperComputer
py -3 -m pip install -r requirements.txt
py -3 gripper_monitor.py
```
Connect the serial device, confirm raw ADC and voltage change with a load, then choose:
- **Factory curve (quick estimate):** 0g zero and one known-force reference. Uses the manufacturer's *conductance-versus-force* table by interpolation, assuming the AO module maps conductance approximately linearly over the used span. This needs verification.
- **Measured multi-point:** collect several real loads for a higher-confidence calibration under the actual grip geometry.

Never infer known force merely from an object's weight clamped between two fingers. The current sensor datasheet states **1 kg nominal range** but contains a **2 kg reference data point**; 1–2 kg accuracy, durability, and safe use require independent validation. Pressure/force values are estimates and should not be used as the sole safety interlock.

Run `py -3 -m unittest discover -s tests -v` from this directory for algorithm and protocol tests.

## Relationship with existing HA8
This folder is standalone and **does not modify** `HA8_UpperComputer.py`, `ha8_protocol.py` or `ha8_serial.py`. The sensor uses its own STM32 / USB-TTL serial link; the existing HA8 actuator uses its official USB-to-UART adapter. Integrating readings into the HA8 controller is a separate step.

## Status (2026-10-30)
User-confirmed: COM4 receiving ~100 frames/s and observed voltage rises on pressure. Factory-mode force precision not yet bench-characterized.


## V3: no-weight circuit estimate (2026-10-30)

The PC monitor adds **免砝码 · 电路** mode based on the AO converter manual:
\`Uo = 0.1 * (1 + Rf/Rx)\`, using the measured AO-RES feedback resistance \`Rf\` and the IMS003-C10A manufacturer's conductance/force table. A no-load offset capture is recommended. No reference mass is required **for theoretical estimation**; precision is not guaranteed.

**Power off all modules before measuring the empty R2 solder pads with an ohmmeter.** The module manual says this gives the current AO-RES feedback resistance; enter the measured value in kΩ. 300kΩ is a supplier *recommendation* for IMS-C10A small-range sensors, not necessarily the installed trim setting. Adjusting AO-RES changes the hardware and requires a new measurement.

At 300kΩ the 2kg datasheet resistance (5kΩ) would require 6.1V, which the module cannot output. Around 150kΩ gives approximately 3.1V at 2kg on paper, but **the sensor is nominally rated 1kg** and the upper range is unverified.

Run the updated PC program using \`py -3 gripper_monitor.py\`. Firmware and UART remain unchanged. See the separate note at \`docs/ao_converter_v3.md\`.
