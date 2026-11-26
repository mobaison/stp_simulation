# Recycle and organic-decay diagnostics

## Recycle selection, fixed before execution

Run the default and raw municipal influents separately at each nitrate recycle setpoint of 0.30, 0.60, 1.00, 1.50, 2.00, and 3.00. Keep the adopted aerobic ammonia rate at 5.799 h⁻¹ and retain all other coefficients and balanced control setpoints. Start each case from the same standard half-full initial state. Report every 300 s using the production engine's unchanged internal five-second increments. The production control bounds remain in place for interactive and API use. Only the diagnostic probe can use requests above 1.00.

Require a verified warm-up within 168 simulated hours. The normal 60-minute window and 24-hour verification require less than 0.5% variation in effluent ammonia and COD, less than 1 m³ net volume drift, no alarms, no influent rejection, and valid effluent samples. Also require nitrate stability using the same relative tolerance. Show the last observed interval for any failed case and identify it as unverified.

To recommend a setpoint, choose the lowest tested value that gives modeled total inorganic nitrogen (TIN = NH₄-N + NO₃-N) at or below 10 mg/L as N with verified warm-up, no alarms, and no rejection in **both** influent cases. Record any alarms and rejection from the entire trace, including startup. If none meets this rule, retain 0.30. Values exceeding the listed setpoints would be considered only if results and hydraulic capacity support a useful extension. No recycle change will be adopted in this diagnostic.

Report measured recycled flow divided by admitted flow separately from the model's request knob, and report the model's nominal recycle-power component separately from total energy. The power term depends on requested ratios.

## COD and BOD proposal, fixed before execution

At the existing 0.30 recycle setting on raw municipal influent, test a target of approximately 30 mg/L effluent COD and 5 mg/L effluent BOD. These are illustrative targets for the prototype. The U.S. EPA's Cauley Creek MBR example reported average effluent COD of 12 mg/L and BOD of 2 mg/L. The diagnostic targets are deliberately less stringent than that published plant example, without implying that its performance applies to this plant. [EPA MBR Fact Sheet, Table 2](https://www.epa.gov/sites/default/files/2019-08/documents/membrane_bioreactor_fact_sheet_p100il7g.pdf)

Use the warmed municipal baseline's transfer flows and tank volumes in a steady, well-mixed stage mass balance. Compute a common multiplier across the existing COD coefficients and a separate multiplier across the existing BOD coefficients to target those values. Preserve the relative stage kinetics, membrane fractions, recycle settings, nitrogen rates, and hydraulic controls. Run the calculated coefficients in an isolated probe from a separate cold start. Use the same warm-up and 24-hour checks and require BOD stability too. Report the actual trial outcomes without retuning them to hit the targets. None of the organic-decay trial coefficients is adopted.
