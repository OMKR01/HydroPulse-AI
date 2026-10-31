# /phase-check Workflow
Quality assurance checklist run after completing each project phase.

1. **Lint & Code Hygiene**:
   - Run `ruff check .`
   - Run `ruff format --check .`
   - Ensure zero warnings or errors.

2. **Test Suite & Coverage**:
   - Run `pytest --cov=src/hydropulse --cov-report=term-missing`
   - Ensure 100% test pass rate and >=80% coverage on core logic.

3. **Integrity Rule Validation**:
   - Verify no fabricated stations, coordinates, or CWC codes in `config/stations.yaml`.
   - Verify every endpoint and dataset carries explicit `provenance` (`observed`, `model_reanalysis`, `forecast`, `synthetic`).
   - Confirm synthetic data is isolated strictly to unit tests and explicitly badged.
   - Verify that docs read metrics strictly from `reports/metrics.json` and contain no hand-typed figures.

4. **Limitations & Documentation**:
   - Update `docs/LIMITATIONS.md` with newly observed real-world gaps.
   - Ensure `README.md`, `docs/DATA_CARD.md`, and `docs/MODEL_CARD.md` reflect current state.

5. **Visual Verification**:
   - For UI/API phases, launch server, inspect `/api/v1/health` and `/docs` in browser, capture screenshot artifact.
