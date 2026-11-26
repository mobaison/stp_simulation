# STP Digital Twin — Industrial Command Center UI

A local BNR–MBR simulation dashboard with a 3D process view, a Gemini plant assistant and a persistent simulation archive.

## Run locally

Requirements: Python 3.10+ and Node.js 18+.

Terminal A:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Terminal B:

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173.

## Plant assistant and history

For chat, configure `backend/.env` with your API keys:
- **`GEMINI_API_KEY`**: Primary LLM key (e.g. `gemini-3.5-flash-lite`).
- **`GROQ_API_KEY`**: Fallback LLM key (e.g. `llama-3.3-70b-versatile`). If Gemini fails due to high demand (HTTP 503), rate limits, or connectivity, the assistant automatically fails over to Groq without interrupting the operator.

The Plant AI Assistant features:
- **Draggable & Floating**: Grab the header bar to float the chat window anywhere across your screens.
- **Resizable**: Drag the bottom-right corner grip or toggle maximize/restore.
- **Clean Formatting**: Formats responses into structured Markdown headers, bullet points, and plain numerical units (without LaTeX math notation or raw tags).
- **Quick Diagnostic Chips**: Instant one-click queries for Effluent Quality, Alarms, BNR Trains, Energy, and Membranes.
- **Copy & Clear**: One-click clipboard copy and reset history controls.

Play or use +60s to record steps. Pause keeps the same session open. Reset closes it. Open History to compare session totals, inspect effluent, flow, energy and alarm onset times, export CSV, or delete a session. Comparison runs are independent. SQLite stores complete step measurements and applied controls under backend/history. Its index supplies session summaries without loading step data. If the server restarts, committed steps from the interrupted session appear in History. The active physics model restarts at its initial state.

Run a single backend worker for one shared local plant. History grows with use. Opening a session detail loads its steps into browser memory. CSV exports stream one row per step. The dashboard's live trend keeps the latest 360 samples. Run backend tests with `python -m unittest -v` from backend and compile the dashboard with `npm run build` from frontend.

## What changed visually

- Dark navy/cyan control-room dashboard; angled panels, luminous highlights, compact KPIs and line charts.
- A large, rotatable Three.js 3D plant scene with concrete base, water bodies, membrane cassette placeholders, railings, pump assemblies and equipment status indicators.
- The plant is arranged in a diagram-inspired process order: facility lift → coarse screen → grit removal → fine screen, two EQ tanks linked to grit/fine screening, four parallel BNR process trains (anaerobic, pre-anoxic, aerobic, post-anoxic), four membrane tanks, common treated effluent.
- Moving particles on pipe edges show calculated simulated flow where active. Recycle links are colored separately.
- Click a tank to inspect its level, COD, TSS and NH4. Switch tag visibility to see the plant more clearly.
- Dashboard cards for influent/effluent quality, flow and quality history, alarm log, simulated energy, permeate TMP proxies, water mass-balance residual.
- Tab overlay for advanced process controls, process data and equipment inventory.
- Fault toggle illustrates a stuck EQ1 displayed sensor (it does not change physics).
- Scenario comparison runs fresh baseline and lift/aeration failure cases without mutating the active state.

## Diagram vs assumptions

The system is a **simulation-based academic prototype**. It does not connect to the actual plant's SCADA or instrumentation. Geometry is engineering-illustrative, not a validated CAD reconstruction. The supplied 66-ft diameter × 15-ft depth tank remains provisionally assigned to EQ Basin 1; the actual equipment attribution is unknown. All other sizes, pump curves/roles, elevations, reaction kinetics, membrane rejection fractions, power estimates and operating setpoints are assumed.

Your supplied reference figures are retained as references rather than forcibly imposed performance outputs: design 7.5 MGD (earlier supplied); reported outlet 3.1 MGD; influent BOD 20–50 mg/L, average 35; influent TSS 5; treated outlet COD 5 and TSS 2 mg/L; electricity reference 19.65 kWh/hr (scope ambiguous). The influent COD 80 mg/L and NH4/NO3 values are assumptions.

Equipment from the diagram **not yet modeled in full physical detail**: mechanical fine/coarse screen mechanics, grit removal dynamics, odor control, RAS splitter-box geometry, multiple separate blower trains, HPA/alum/carbon dosing, citric acid/CIP cleaning equipment, sludge-holding and dewatering systems. The existing simplified process model uses reaction proxies, membrane rejection, recycle loops and wasting sinks; it is not ASM or a calibrated MBR model.

## Simulation engineering details

- Each storage unit obeys finite-volume water conservation; each BOD/COD/TSS/NH4/NO3 mass advects with the transferred volume.
- Fine-screen flow is split equally across the four parallel treatment trains, subject to receiving tank capacity. Screen and train transfers use an assumed level-dependent flow up to a capacity limit. The free-draining effluent tank raises a low-level alarm when its level is low and no treated water is discharged during the step.
- Aerobic NH4-N is converted into NO3-N on a nitrogen-mass basis; denitrification removes NO3-N via an assumed rate.
- The dashboard has six wastewater presets that load editable concentrations for one incoming stream. The raw municipal preset uses the medium-strength raw domestic sewage example in [U.S. EPA Technical Guidance Manual, Book II, Table A-6](https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=200055WG.TXT) (BOD₅ 200, COD 500, TSS 200, ammonia nitrogen 25 and nitrate nitrogen 0 mg/L). It represents an illustrative literature case. The industrial preset represents a concentration scenario only and has no toxicity or pretreatment model.
- Aerobic-tank pH is an independently imposed simulation setting, with a default of 7.2. The ammonia conversion coefficient is a design-basis assumption of 5.799 h⁻¹ for approximately 1 mg/L effluent ammonia at the balanced default settings. The pH factor is one from 6.8 to 8.0 and tapers linearly to zero at pH 5.5 and 9.5. The model has no pH transport or alkalinity balance. The selected preset and applied pH are recorded in session controls.
- BOD/COD biological removal uses assumed first-order rates for both soluble and particulate mass. The membranes retain 99.98% of advected TSS and particulate COD/BOD. The soluble organic fractions pass. Particulate inputs use the declared design-basis assumptions in [DESIGN_BASIS.md](DESIGN_BASIS.md). No rigorous fouling pressure-network solver is used.
- A 3.1 MGD limit caps total permeate request; model transfer is further limited by available tank volume and outlet storage.
- The baseline uses a 2,063.571 US gal/min permeate request and a 390 US gal/min equalization return request. The wasting ratio of 0.006719201 yields about 37.628 US gal/min of sludge wasting and 1,862.372 US gal/min of treated flow at 1,900 US gal/min influent.
- Pump and blower energy use illustrative head, efficiency and power parameters. Recycle power uses actual transferred recycle flow. Compare accumulated energy across equal elapsed intervals. Do not use numerical results for plant compliance or operational decisions.
- Mass and pollutant-balance diagnostics are provided for auditing numerical behavior.
- Effluent concentrations use pollutant mass divided by the volume discharged during each simulation step. Steps with no discharge have no effluent sample. Archived sessions recorded before this change have blank effluent concentration columns in CSV exports.
- History retains 360 snapshots; each click/clock step appends one point.
- This is a single-session in-memory backend; the model resets when the server restarts. Multiple browser users share the same backend state.

## Research warm-up

The pre-adoption Step 2 comparison is archived under `results/step2/`. Run `python backend/verify_step2.py --output results/current_engine_verification` to reproduce that reporting-interval check with the current engine and the original liquid-quality criteria. The research warm-up is separate from interactive reset. For new research runs, `prepare_initial_state(Controls())` in `backend/warmup.py` checks 60-minute ranges in effluent NH₄-N and COD, TSS in the direct membrane permeate, and TSS in each membrane tank. It also checks net water inventory, alarms, and rejected inflow, then requires a further 24 hours of stability. By the end of that verification window, the absolute in-process TSS inventory change must be below 1% of the TSS admitted over the same 24 hours. The default time limit is 90 simulated days. Construct independent runs with `new_twin()`, which copies the verified water volumes and constituent masses and starts the experiment clock, energy, and alarm history afresh.

Run `python backend/verify_final_design.py` to verify both influents at each of the four ammonia rates and rerun the joint ±25% particulate-fraction sensitivity. The inputs use the adopted model v2 COD and BOD decay multipliers. The initializer seeds solids from the settled transfer map and verifies the state for another 24 simulated hours. The eight checkpoints under `results/model_v2/` carry bulk and particulate masses. The seeded warm-up does not estimate cold-start solids time.

## Step 3 simulation study

From the project root, run `python run_experiments.py` to verify the frozen input hashes, generate raw data and regenerate the tables and figures under `results/step3/`. Use `--workers 4` to limit process concurrency, `--phase simulate` for raw artifacts, or `--phase report` to redraw the report from existing CSVs. The reporting phase uses Matplotlib. The protocol fixes the paired equipment grid, separate command-only level predictor, sensor conditions, and detection thresholds. See [design basis](DESIGN_BASIS.md), [detection protocol](DETECTION_PROTOCOL.md), and [study results](results/step3/STEP3_RESULTS.md).

Run `python -m unittest discover -s backend` for the backend tests and `python -m unittest test_step3` for the synthetic study-rule tests.

## Tests

```bash
cd backend
python -m unittest -v
```

Five numerical tests cover water/quality conservation, capacity limiting, pump stop, reset and membrane solids retention.

## Suggested next engineering development

After verifying the local browser build and full interactive workflow, replace the illustrative geometry with CAD-grade equipment assemblies and incorporate the previously missing sludge holding, blowers, recirculation pump banks, and dosing lines, while keeping the mathematical topology versioned separately from visualization geometry.
