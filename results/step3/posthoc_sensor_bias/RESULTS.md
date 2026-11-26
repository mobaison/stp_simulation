# POST-HOC inlet-flow bias analysis

Exploratory municipal adopted-rate runs reuse the frozen sensor threshold, predictor, and paired seeds. Passing requires zero healthy false alarms and full drift detection on both schedules, plus full stuck detection after the surge.

Passing sampled biases were -1.0%, -0.5%, +0.0%, +0.5%, +1.0%, +2.0%. The largest sampled symmetric passing bound was ±1.0%.

| Schedule | Inlet bias | Healthy false alarms | Stuck detected | Drift detected | Stuck median (min) | Drift median (min) |
| --- | --- | --- | --- | --- | --- | --- |
| constant | -5.0% | 20/20 | 1/20 | 18/20 | 1 | 3.0 |
| constant | -2.0% | 1/20 | 0/20 | 20/20 | — | 8.0 |
| constant | -1.0% | 0/20 | 0/20 | 20/20 | — | 10.5 |
| constant | -0.5% | 0/20 | 0/20 | 20/20 | — | 11.0 |
| constant | +0.0% | 0/20 | 0/20 | 20/20 | — | 11.5 |
| constant | +0.5% | 0/20 | 0/20 | 20/20 | — | 12.0 |
| constant | +1.0% | 0/20 | 0/20 | 20/20 | — | 13.0 |
| constant | +2.0% | 0/20 | 0/20 | 20/20 | — | 15.0 |
| constant | +5.0% | 20/20 | 3/20 | 20/20 | 1 | 19.0 |
| surge | -5.0% | 20/20 | 20/20 | 18/20 | 67.0 | 3.0 |
| surge | -2.0% | 1/20 | 20/20 | 20/20 | 65.0 | 8.0 |
| surge | -1.0% | 0/20 | 20/20 | 20/20 | 64.0 | 10.5 |
| surge | -0.5% | 0/20 | 20/20 | 20/20 | 64.0 | 11.0 |
| surge | +0.0% | 0/20 | 20/20 | 20/20 | 64.0 | 11.5 |
| surge | +0.5% | 0/20 | 20/20 | 20/20 | 64.0 | 12.0 |
| surge | +1.0% | 0/20 | 20/20 | 20/20 | 63.0 | 13.0 |
| surge | +2.0% | 0/20 | 20/20 | 20/20 | 63.0 | 15.0 |
| surge | +5.0% | 20/20 | 19/20 | 20/20 | 62 | 19.0 |

[Aggregate rates](summary.csv) · [Per-run records](runs.csv)
