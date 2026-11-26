# Step 3 monitor and alarm definitions — frozen v1

This protocol is frozen before any Stage 3 fault or sensor run. Thresholds are experiment definitions, not regulatory limits or tuned claims about detector accuracy. Use the verified checkpoint for the matching influent and kinetic condition. Preserve the water volume, total constituent mass, and particulate COD/BOD mass.

## Timing and matched reference

- Use 60-second reporting and match the physical engine integration across all runs. Observe each run for 24 simulated hours. Apply an outage at its scheduled boundary and treat the first complete step with the fault active as minute 1.
- Use a no-fault companion run with the same influent, kinetics, and inventory perturbation. Compare readings at the same simulated time. A fault-specific process alarm is new only if it is absent in the companion reading.
- Use outage starts at 2, 8 and 16 h and durations of 15, 60 and 240 min. Include an unperturbed case and paired single-tank runs with either the wet well or the outlet tank set to 25%, 50% or 75% of capacity at outage onset. Apply the same assignment in the no-fault companion. Keep concentration fixed when scaling tank water, total constituent mass, and particulate mass. For an initially empty outlet, use the most recent positive-discharge sample in the companion before the perturbation, with total and particulate constituent concentrations calculated from exported masses and outlet flow over that same interval. If no such sample exists, mark the perturbation unavailable and record the reason.
- An alarm reported before a fault starts is not a successful detection. Record the time of the first qualifying reported sample. When a rule requires two consecutive samples, use the time of the second sample. Classify detections as during or after the outage. A rule that never fires is right-censored at the end of observation. Report blind time to the outlet-only monitor and distinguish a lower bound when it remains silent. Avoid reporting a finite detection advantage when either time is censored.

## Outlet-only monitor

Use **only treated discharge flow and discharged concentrations**. Each rule must hold on two consecutive samples, using the contemporaneous matched reference.

| Signal | Trigger |
|---|---|
| Treated discharge flow | At least **10% below** a positive matched flow |
| Effluent NH₄-N | At least **max(20% of reference, 0.50 mg/L)** higher |
| Effluent COD | At least **max(20% of reference, 5.0 mg/L)** higher |
| Effluent BOD | At least **max(20% of reference, 2.0 mg/L)** higher |
| Effluent TSS | At least **max(20% of reference, 1.0 mg/L)** higher |

The earliest confirmed rule is the outlet-only time. A zero or missing discharge sample cannot trigger a concentration rule or be treated as a zero concentration. Report trigger signal and its value. The flow rule remains available when the reference has positive flow.

## Equipment status and process alarms

Report the first status flag separately from the first process alarm. A simulator command can flag a requested outage but does not establish detection from a measured response. Use a single reported sample for these existing flags.

| Fault | Command-derived status | Independent process alarms eligible for the comparison |
|---|---|---|
| Lift pump off | Engine lift-pump-stopped flag | Wet-well high level or rejected inlet wastewater |
| Aeration off | Engine aeration-unavailable flag | None in the current engine. Report process detection as unavailable. Do not count the outlet monitor as a process alarm. |
| Permeate pumps off | No existing dedicated shutdown flag | Membrane-tank high level or treated-water holding tank low level at zero discharge |

Only the eligible flags in the table count toward first process detection. Record other alarms in the raw trace but do not substitute them after the run. Apply the frozen physical thresholds in the design basis. Report lift, aeration, and permeate results separately.

## Sensor residual tests

Use the lift wet-well level in percentage points of capacity as the synthetic sensor. Use the engine level as the expected reference. The display value is a separate signal and does not affect plant physics. After two baseline hours, freeze the sensor at the previous good sample for the stuck case or add **+0.20 percentage points per minute** for drift, bounded by 0% and 100%. Run a matched fault-free 24-hour control, and document that no measurement noise is injected in this deterministic test.

Detect when the absolute display/reference residual is **greater than 2.0 percentage points for two consecutive samples**. Count each transition into the alarm as one event and report time from the fault start. Test the stuck case both at the unchanged operating point and with a declared post-fault physical disturbance of **+20% inlet request for 15 minutes beginning one hour after fault onset**, applied identically in its matched control. A sensor stuck near a constant expected value may remain undetected. Report that result. The test uses the model as a reference and does not measure performance with a real or independent sensor.

## Comparisons and reporting rules

Use identical detection rules on the adopted 5.799 h⁻¹ ammonia basis, the named legacy 0.170 h⁻¹ control comparison, and the separately warmed ±20% nominated rate-sensitivity cases. Record individual fault and control configurations and summarize whether conclusions hold, including nondetections. Keep imposed aerobic pH 6.0 and zero-aeration ammonia endpoints as returned by the engine. Compare energy only over equal elapsed windows. Do not change these definitions after examining Step 3 outputs.
