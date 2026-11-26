# Step 3 results — STP simulation-based digital twin prototype

The primary case uses raw municipal influent and the adopted ammonia and organic decay coefficients. The results cover synthetic faults in this model. The design basis and v1.1 protocol were hashed before simulation.

## Verified starting states

| Influent | NH₄-N | NO₃-N | Modeled TIN | COD | BOD | TSS |
| --- | --- | --- | --- | --- | --- | --- |
| Municipal | 1.046 | 17.008 | 18.054 | 30.008 | 5.004 | 2.000 |
| Default | 1.004 | 16.924 | 17.928 | 11.163 | 2.082 | 0.050 |

All concentrations are in mg/L. Each of the eight influent/rate cases was independently warmed and verified for a further 24 hours.

| Influent | Joint particulate-fraction change | COD (mg/L) | BOD (mg/L) | TSS (mg/L) |
| --- | --- | --- | --- | --- |
| Municipal | -25% | 41.783 | 7.014 | 2.000 |
| Municipal | +25% | 18.232 | 2.995 | 2.000 |
| Default | -25% | 11.457 | 2.132 | 0.050 |
| Default | +25% | 10.869 | 2.032 | 0.050 |

The particulate-fraction sensitivity uses the adopted organic multipliers. The municipal COD/BOD design values depend strongly on the influent split. The modeled TIN values exceed the design-basis screen.

## Equipment faults — full primary grid

See the [duration and perturbation tables](DURATION_AND_PERTURBATION.md) for the collapsed-onset presentation.

| Fault | Command status | Process alarm | Aerobic NH₄-N monitor | Outlet-only monitor | Outlet silent at end |
| --- | --- | --- | --- | --- | --- |
| Lift pump | 63/63, 1 min | 63/63, 14 min | 0/63 | 21/63, 322 min | 42/63 |
| Aeration | 63/63, 1 min | Unavailable | 63/63, 7 min | 42/63, 57 min | 21/63 |
| Permeate pumps | Unavailable | 57/63, 1 min | 0/63 | 63/63, 2 min | 0/63 |

Cells show confirmed runs over all runs and the median among confirmed runs. A silent comparator remains right-censored at the end of its 24-hour trajectory. The residual observation windows after the outages begin are 480, 960 or 1,320 minutes. The outlet and aerobic monitors both get the matched no-fault reference.

| Fault | Process alarm before / tied / after outlet | Aerobic monitor before / tied / after outlet |
| --- | --- | --- |
| Lift pump | 21 / 0 / 0 | No jointly confirmed runs |
| Aeration | No jointly confirmed runs | 42 / 0 / 0 |
| Permeate pumps | 42 / 15 / 0 | No jointly confirmed runs |

Timing order uses jointly confirmed runs. The CSV also gives counts for one-sided confirmations, after-outage detections and censored runs.

The outlet-only monitor confirmed 0/63 lift outages before restoration. It confirmed 21/63 after restoration. A command flag indicates the requested outage from the software state. The hydraulic alarm comes from the modeled wet well.

- Lift pump [confirmation curve](figures/lift_detection.png) and [run-grid heatmap](figures/lift_heatmap.png)
- Aeration [confirmation curve](figures/aeration_detection.png) and [run-grid heatmap](figures/aeration_heatmap.png)
- Permeate pumps [confirmation curve](figures/permeate_detection.png) and [run-grid heatmap](figures/permeate_heatmap.png)

## Pump recovery example

The unperturbed primary lift run in the central onset and duration settings restored the pump at minute 540. The first alarm-free sample was minute 545, 5 minutes later. Rejected inflow reached 326.35 m³ by the end of the run. The outlet monitor's final state was right censored. [Complete recovery trace](equipment/municipal_adopted_t480_none/lift_60m.csv.gz)

## Kinetic sensitivity — matched municipal reduced grids

| Ammonia rate (h⁻¹) | Fault | Process alarm | Aerobic NH₄-N monitor | Outlet-only monitor | Outlet silent at end | Inside before / tied / after outlet |
| --- | --- | --- | --- | --- | --- | --- |
| Adopted (5.799) | Lift pump | 27/27, 14 min | 0/27 | 9/27, 322 min | 18/27 | 9 / 0 / 0 |
| Adopted (5.799) | Aeration | Unavailable | 27/27, 7 min | 18/27, 57 min | 9/27 | 18 / 0 / 0 |
| Adopted (5.799) | Permeate pumps | 24/27, 1 min | 0/27 | 27/27, 2 min | 0/27 | 18 / 6 / 0 |
| Legacy (0.17) | Lift pump | 27/27, 14 min | 0/27 | 9/27, 322 min | 18/27 | 9 / 0 / 0 |
| Legacy (0.17) | Aeration | Unavailable | 9/27, 112 min | 18/27, 121 min | 9/27 | 0 / 0 / 9 |
| Legacy (0.17) | Permeate pumps | 24/27, 1 min | 0/27 | 27/27, 2 min | 0/27 | 18 / 6 / 0 |
| −20% (4.6392) | Lift pump | 27/27, 14 min | 0/27 | 9/27, 322 min | 18/27 | 9 / 0 / 0 |
| −20% (4.6392) | Aeration | Unavailable | 27/27, 7 min | 18/27, 57 min | 9/27 | 18 / 0 / 0 |
| −20% (4.6392) | Permeate pumps | 24/27, 1 min | 0/27 | 27/27, 2 min | 0/27 | 18 / 6 / 0 |
| +20% (6.9588) | Lift pump | 27/27, 14 min | 0/27 | 9/27, 322 min | 18/27 | 9 / 0 / 0 |
| +20% (6.9588) | Aeration | Unavailable | 27/27, 7 min | 18/27, 57 min | 9/27 | 18 / 0 / 0 |
| +20% (6.9588) | Permeate pumps | 24/27, 1 min | 0/27 | 27/27, 2 min | 0/27 | 18 / 6 / 0 |

All four rates use the same reduced grid. “Inside” refers to the aerobic monitor for aeration and to process alarms for lift and permeate. Confirmed-only medians can summarize different sets of trials, so ordering uses the paired counts in the last column. The secondary low-strength default cases appear in the full aggregate CSV.

The hydraulic alarm timing findings held at every tested ammonia rate. The aeration-monitor lead held at ±20% on the municipal grid and reversed in jointly confirmed trials at the legacy rate. Rate-dependent aeration timing reflects both the ammonia response and the threshold relative to baseline.

## Sensor faults — primary municipal case

| Command schedule | Indicated inlet bias | Fault | Healthy runs with false alarm | Confirmed out of 20 | Censored out of 20 | Median confirmation | Fault runs active at injection |
| --- | --- | --- | --- | --- | --- | --- | --- |
| constant | -5% | stuck | 20/20 | 1 | 19 | 1 min | 2 |
| constant | -5% | drift | 20/20 | 18 | 2 | 3 min | 2 |
| constant | +0% | stuck | 0/20 | 0 | 20 | — | 0 |
| constant | +0% | drift | 0/20 | 20 | 0 | 11.5 min | 0 |
| constant | +5% | stuck | 20/20 | 3 | 17 | 1 min | 1 |
| constant | +5% | drift | 20/20 | 20 | 0 | 19 min | 1 |
| surge | -5% | stuck | 20/20 | 20 | 0 | 67 min | 2 |
| surge | -5% | drift | 20/20 | 18 | 2 | 3 min | 2 |
| surge | +0% | stuck | 0/20 | 20 | 0 | 64 min | 0 |
| surge | +0% | drift | 0/20 | 20 | 0 | 11.5 min | 0 |
| surge | +5% | stuck | 20/20 | 19 | 1 | 62 min | 1 |
| surge | +5% | drift | 20/20 | 20 | 0 | 19 min | 1 |

The independent prediction twin uses commanded flow. The physical twin receives biased flow. The seed noise is shared across paired healthy, stuck and drift runs. A detection after injection requires a new alarm transition. The full sensor aggregate includes every influent, rate, schedule and bias, as well as counts of alarms before injection. [Sensor detection and false-alarm figure](figures/sensor_detection.png)

Across both influents and all rates, healthy false alarms occurred in 0/320 zero-bias replicates and 640/640 biased replicates. These replicate counts reuse matched seeds and deterministic hydraulic trajectories. The monitor missed stuck readings under constant unbiased commands and detected them after the surge. The biased healthy controls show that this residual can respond to inlet-flow error as well as level-sensor faults.

## Continuous pH and aeration-off checks

| Influent and rate | pH 6.0 effluent NH₄-N | Aeration off effluent NH₄-N |
| --- | --- | --- |
| municipal adopted | 2.543 | 23.835 |
| municipal legacy | 19.730 | 24.510 |
| municipal minus20 | 3.099 | 23.847 |
| municipal plus20 | 2.156 | 23.827 |
| default adopted | 2.441 | 22.882 |
| default legacy | 18.941 | 23.530 |
| default minus20 | 2.975 | 22.893 |
| default plus20 | 2.070 | 22.874 |

Concentrations are in mg/L as N in the final one-minute interval. These separate 24-hour runs are excluded from fault-detection counts.

## Data and reproducibility

- [Equipment run records](equipment_detection.csv) and [equipment aggregates](equipment_summary.csv)
- [Sensor run records](sensor_detection.csv) and [sensor aggregates](sensor_summary.csv)
- [pH and aeration-off run records](ammonia_comparisons.csv)
- [Frozen protocol](../../DETECTION_PROTOCOL.md) and [input hashes](../model_v2/freeze_manifest.sha256)
