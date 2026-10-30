# HydroPulse AI — Build Prompts for Google Antigravity

## How to use

1. Create an empty folder `hydropulse-ai/`, copy `AGENTS.md` into its root, and open the folder as an Antigravity workspace. Antigravity reads `AGENTS.md` as a workspace rule (12,000-character cap per rules file, so keep it lean).
2. Use **Planning mode** in the Agent Manager. Paste ONE phase prompt at a time. Review the Implementation Plan artifact, approve, let the agent work, then review the Walkthrough artifact before moving on.
3. Optional: save the `/phase-check` workflow below as `.agents/workflows/phase-check.md` and run it after each phase.
4. Commit after every phase. A clean git history is itself a portfolio asset.

Suggested order and rough effort: Phase 0–2 (week 1–2) · 3–4 (week 3–4) · 5–6 (week 5–6) · 7–9 (week 7–8).

---

## Phase 0 — Kickoff and scaffold

```
You are building "HydroPulse AI: Jharkhand River Health Monitoring System".
Read AGENTS.md fully and follow it for the whole project.

Phase 0 goal: a runnable, tested skeleton.

Tasks:
1. Create the repo layout from AGENTS.md section 4, pyproject.toml (or requirements.txt + requirements-dev.txt), .gitignore, .env.example, Makefile (setup, lint, test, run, train, refresh), pre-commit with ruff.
2. Implement the Flask app factory with /api/v1/health returning status, version, and generated_at. Add OpenAPI docs at /docs.
3. Create config/stations.yaml with 8–10 candidate monitoring points across the Damodar and Subarnarekha basins (for example near Ranchi, Jamshedpur, Ghatshila, Bokaro, Dhanbad, Maithon). Use approximate coordinates, mark every entry `verified: false`, and include a `snap_to_river: true` flag. Do NOT invent CWC station codes.
4. Add GitHub Actions CI (lint + tests) and a Dockerfile + docker-compose.yml.
5. Write a README skeleton: problem statement, architecture placeholder, quickstart.

Acceptance: `make setup && make test && make run` works; /api/v1/health and /docs load; CI file is valid.
Output: Implementation Plan first, then a Walkthrough artifact with a screenshot of /docs.
```

---

## Phase 1 — Data ingestion

```
Phase 1 goal: reliable, cached, provenance-tagged data ingestion.

First, web-search the CURRENT docs for: Open-Meteo forecast + historical archive API, Open-Meteo Flood API (GloFAS), and the `hydroswift` package for India-WRIS/CWC. Record URLs and parameter notes in docs/DATA_CARD.md.

Tasks:
1. ingest/openmeteo_weather.py — hourly/daily precipitation, temperature, humidity: history (ERA5 archive) and forecast, per station.
2. ingest/openmeteo_flood.py — daily river_discharge history + forecast. Implement snap_to_river(): scan a small lat/lon grid around the station and pick the cell with highest mean discharge; store the chosen cell in config and log the shift distance.
3. ingest/wris_cwc.py — optional adapter using hydroswift. Must fail gracefully (timeouts, empty results), cache, and never block the pipeline.
4. ingest/cpcb_wq.py — loader + pandera/pydantic schema validation for CPCB NWMP-style CSV (pH, DO, BOD, COD, conductivity, turbidity, fecal coliform, date, station). Include a data/raw/wq/README explaining how to obtain real files and a tiny SYNTHETIC sample clearly labelled `synthetic` for tests only.
5. Storage in SQLite via SQLAlchemy with a `provenance` column on every table.
6. A `refresh` command plus an APScheduler job (every 6 h) that updates forecasts and records `last_success_at` per source.
7. Handle the GloFAS reanalysis end date explicitly (history stops mid-2022 in the current dataset); document the gap strategy.

Tests: mocked HTTP responses (no live network in CI), retry/timeout behaviour, schema validation failures, snap_to_river on a fixture grid.
Acceptance: `make refresh` populates the DB for at least 5 stations; stale-source flag works when a source is mocked as down.
```

---

## Phase 2 — Cleaning, features, EDA

```
Phase 2 goal: a leak-free feature pipeline and an exploratory analysis that tells a story.

Tasks:
1. features/cleaning.py — gap detection, outlier flags (do not silently delete), unit normalisation, train-only scaling.
2. features/lags.py — lagged rainfall (1–14 d), rolling sums (3/7/14/30 d), antecedent wetness proxy, day-of-year sin/cos, discharge lags, upstream-station features where topology is known in config.
3. features/spi.py — SPI-1/3/6 with a gamma fit on a reference period.
4. features/static_attrs.py — optional static catchment attributes.
5. notebooks/01_eda.ipynb — seasonality of Damodar vs Subarnarekha, monsoon peaks, rainfall-to-discharge lag, missingness map, and a data-quality summary table.
6. tests/test_leakage.py — proves no feature at time t uses information from t+1 or later (perturb the future and assert features at t are unchanged).

Acceptance: processed parquet files per station, an EDA notebook that runs top-to-bottom, leakage test green.
```

---

## Phase 3 — Flood forecasting models

```
Phase 3 goal: honest, well-evaluated multi-horizon flood forecasting.

Tasks:
1. models/baselines.py — persistence, climatology, ridge.
2. models/lgbm.py — direct multi-horizon LightGBM (t+1…t+7).
3. models/lstm.py — PyTorch seq2seq or direct multi-horizon LSTM. Train (a) per-station and (b) one multi-station model with station embeddings or static attributes.
4. Hybrid correction: model the residual of raw GloFAS forecast vs target so the ML layer acts as a local post-processor. Compare against raw GloFAS.
5. models/quantile.py — P10/P50/P90 via quantile loss; check calibration (coverage of the 80% band).
6. evaluation/metrics.py — NSE, KGE, RMSE, MAE per horizon; alert metrics POD/FAR/CSI/F1/PR-AUC; peak-timing error.
7. Chronological split + blocked CV. Everything seeded. Log runs to reports/runs/ and write reports/metrics.json.
8. SHAP / permutation importance for LightGBM; attention or gradient-based sensitivity for LSTM if feasible.
9. docs/MODEL_CARD.md: intended use, data, splits, metrics, failure modes, where the model should NOT be trusted.

Acceptance: a comparison table (baseline vs LGBM vs LSTM vs hybrid) generated from reports/metrics.json, hydrograph plots for the worst and best test years, and an honest paragraph on where the LSTM does not help.
```

---

## Phase 4 — Drought and water-quality health

```
Phase 4 goal: complete the "river health" half of the project.

Tasks:
1. models/drought.py — SPI-based drought category + low-flow flag (discharge < station Q90) + a combined drought status with 30-day outlook from forecast rainfall/discharge.
2. models/wqi.py — weighted-arithmetic WQI with documented weights; CPCB designated-best-use classification (A–E). First web-search CPCB's official criteria table and cite it in DATA_CARD.md; unit-test boundary values.
3. Seasonal decomposition + Mann-Kendall trend for each water-quality parameter per station.
4. Pollution-hotspot flagging for the mining/industrial belt (Bokaro–Dhanbad stretch) based on BOD/COD/DO thresholds, labelled as "indicative" unless real monitoring data is loaded.
5. Optional: a simple classifier that predicts next-month WQI class from season + upstream rainfall, with the same leakage discipline as Phase 3.

Acceptance: unit tests for SPI, WQI, class boundaries; a notebook showing drought history for one station and WQI seasonality; DATA_CARD updated.
```

---

## Phase 5 — Backend API

```
Phase 5 goal: production-style Flask API over the models.

Tasks: implement every endpoint in AGENTS.md section 7 with Pydantic (or marshmallow) schemas, a consistent error envelope, caching, rate limiting, request timeouts, explicit CORS, structured logging with request IDs, and OpenAPI docs.
Every payload includes generated_at, data_provenance, is_stale.
Add /alerts that returns active Watch/Warning/Danger items with a plain-language message in English and Hindi, plus a machine-readable "reasons" list (top features from the explainability step).
Add contract tests (schemas), error-path tests, and a Locust or k6 smoke script in scripts/.

Acceptance: >=80% coverage on api/, all endpoints documented, p95 latency under 300 ms on cached responses locally.
```

---

## Phase 6 — Dashboard

```
Phase 6 goal: a dashboard that is understandable "at a glance" (the project's Pulse idea).

Use Jinja templates + Leaflet + Chart.js, no SPA framework. Build:
1. Full-width map with station markers (risk colour + icon + label), basin polygons if available, layer toggles (flood risk, drought, water quality).
2. Station drawer: hydrograph with forecast band and alert thresholds, SPI/drought status, WQI gauge + CPCB class, "Why this alert?" panel, data-provenance badge, last-updated time.
3. Top bar: alert count, language toggle (EN/Hindi), advisory disclaimer, DEMO DATA badge whenever any synthetic source is active.
4. Loading, empty, error, and stale-data states for every widget.
5. Responsive layout, keyboard navigation, ARIA labels, colour-blind-safe palette.

Run the app, open it in the browser, and attach screenshots (desktop + mobile width) to the Walkthrough. Fix anything that looks broken before finishing.
Acceptance: Lighthouse accessibility >= 90 and no console errors.
```

---

## Phase 7 — Validation against historical floods

```
Phase 7 goal: prove the system on real past events.

Tasks:
1. Web-search for documented flood and severe-rain events in the Damodar and Subarnarekha basins (news, CWC, state disaster management, peer-reviewed papers). Create data/events/historical_floods.yaml with date, basin, description, and a source URL for EVERY entry. Skip any event you cannot source.
2. evaluation/events.py — for each event: did the system raise Watch/Warning/Danger, with how many days of lead time, and how far was the predicted peak from the observed/model peak? Include a false-alarm analysis on non-event periods.
3. Produce reports/event_validation.md and plots; compare against raw GloFAS and a persistence baseline.
4. Write docs/LIMITATIONS.md honestly: GloFAS is model output, sparse gauges, point-snapping uncertainty, no dam-release data, advisory only.

Acceptance: a table of events with hit/miss/lead-time and a clear, truthful summary.
```

---

## Phase 8 — DevOps, hardening, docs

```
Phase 8 goal: make it look and behave like a real service.

Tasks: multi-stage Dockerfile, docker-compose (app + scheduler), health checks, config via env vars, GitHub Actions (lint, tests, coverage badge, Docker build), a deploy guide for a free tier (Render, Railway, or Hugging Face Spaces), pinned dependencies, and a security pass (dependency audit, input validation, no secrets in git).
Complete docs: README (with architecture diagram, screenshots, results table pulled from reports/metrics.json), ARCHITECTURE.md (Mermaid), MODEL_CARD.md, DATA_CARD.md, LIMITATIONS.md, CONTRIBUTING.md.
Acceptance: fresh clone -> `docker compose up` -> dashboard works; CI green.
```

---

## Phase 9 — Portfolio, report, interview kit

```
Phase 9 goal: convert the work into exam, CV, and interview material.

Generate, using only real numbers from reports/metrics.json and the repo:
1. docs/DISSERTATION_MAP.md — mapping from repo artifacts to dissertation chapters (Introduction, Literature Review, Methodology, Implementation, Results, Conclusion, Future Work).
2. docs/CV_BULLETS.md — 4–6 resume bullets in action + method + measurable-result form, with placeholders for any metric not yet computed.
3. docs/INTERVIEW_KIT.md — 25 likely questions with concise answers grounded in this project: why LSTM vs gradient boosting, leakage prevention, NSE vs KGE, handling sparse gauges, why hybrid GloFAS correction, alert-threshold choice, false-alarm cost, deployment, limitations, what you would do with more time.
4. docs/DEMO_SCRIPT.md — a 3-minute screen-recording script and a 60-second elevator pitch.
5. A short LinkedIn/GitHub project description (under 150 words).
Do not claim anything the repo cannot demonstrate.
```

---

## Optional workflow: `.agents/workflows/phase-check.md`

```
# /phase-check
1. Run ruff, mypy (light), and pytest with coverage; report failures.
2. Confirm AGENTS.md section 9 quality gates one by one with evidence.
3. Grep the repo for hard-coded metrics in docs and confirm each comes from reports/metrics.json.
4. Confirm no synthetic data is presented as real (check provenance tags and the DEMO DATA badge).
5. Update docs/LIMITATIONS.md with anything new discovered.
6. Output a short pass/fail checklist and the exact next phase prompt to run.
```

---

## Stretch ideas (only after Phase 8)

- Telegram bot that sends Watch/Warning alerts in Hindi and English (free API).
- Plain-language advisory bulletins generated by an LLM from structured model output, with strict guardrails (no new facts, always shows the underlying numbers).
- Lead-time analysis: how many hours or days earlier than a threshold crossing the system warned.
- Reservoir-aware features (Tenughat, Maithon, Panchet, Chandil) if release data can be sourced.
- Model-drift monitor that compares recent forecast errors with the test-set distribution and flags retraining.
