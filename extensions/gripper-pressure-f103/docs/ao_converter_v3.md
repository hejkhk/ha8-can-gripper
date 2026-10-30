# AO converter / FSR formula (v3)

Sources supplied by the user:
- AO converter user manual pages 3–5: AO output 0.1–3.3V, 5V module supply, adjustable AO-RES 0–300kΩ, and opamp formula \`Uo=0.1*(1+Rf/Rx)\`.
- IMS003-C10A-1KG datasheet pages 1–2: nominal 1kg rating, force/resistance reference points including a 2kg point beyond the nominal rating.

For resistances in kΩ and measured voltage in V, the sensor conductance in (1/kΩ) is:
\`G=(Uo-0.1)/(0.1*Rf)\`.
If an unloaded baseline \`Uzero\` has been captured, the PC applies:
\`G=(Uo-Uzero)/(0.1*Rf)\`.
Interpolate within the supplied 0–2000gf conductance table. Negative readings are clamped to zero; values beyond the last point are not extrapolated.

For proper use:
1. Remove every power source (also disconnect the USB-TTL adapter).
2. Measure feedback resistance across the unsoldered R2 pads following the module manual, and enter the true reading in kΩ.
3. Reconnect the ADC module and serial interface, capture the no-load zero, and monitor approximate force.
4. Never rely on this estimate as a safety interlock or precise normal-force measurement.

With \`Rf=300kΩ\` and \`Rx=5kΩ\`, formula gives 6.1V and output saturates; approximately 150kΩ corresponds to 3.1V at that datasheet point. This does not validate the sensor outside its nominal 1kg rating.
