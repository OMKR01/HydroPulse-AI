# Contributing to HydroPulse AI

Thank you for your interest in contributing to **HydroPulse AI: Jharkhand River Health Monitoring System**!  
Owner: Om Kumar (MCA, Amity Ranchi).

HydroPulse AI is built to provide verifiable, reproducible hydrological forecasting and river health tracking for the Damodar and Subarnarekha basins in Jharkhand. Because this platform serves environmental researchers, reviewers, and disaster management stakeholders, **scientific honesty and data integrity always beat flash.**

---

## 1. Non-Negotiable Integrity Rules

Before writing any code, every contributor must understand and adhere to the project's core integrity principles:

1. **Never fabricate data or metrics**: Never invent monitoring stations, geographic coordinates, CWC station codes, flood events, or validation metrics. Every station must be verified from official gazettes or marked `verified: false` in `config/stations.yaml`.
2. **Strict data provenance**: Every dataset record carries a provenance tag: `observed | model_reanalysis | forecast | synthetic`. Synthetic data is permitted ONLY for isolated unit tests or explicit offline fallback, and must display an explicit "DEMO DATA" banner in the UI.
3. **Reproducible metrics**: All metrics in reports or documentation must be programmatically generated into `reports/metrics.json` via reproducible scripts (`python -m src.hydropulse.pipeline.train`). Never hand-type a number.
4. **GloFAS attribution**: River discharge derived from Open-Meteo Flood API is European Centre for Medium-Range Weather Forecasts (ECMWF) GloFAS v4 hydrological model output, **not** an in-situ stream gauge reading. Always declare it as such.
5. **Advisory status**: HydroPulse AI is an advisory decision-support system. Official flood warnings and evacuation alerts are issued exclusively by the **Central Water Commission (CWC)** and the **Jharkhand State Disaster Management Authority (JSDMA)**.

---

## 2. Development Setup

### Prerequisites
- Python 3.11 (3.11–3.14 supported)
- Git 2.30+
- Docker Engine & Docker Compose (optional, for containerized testing)

### Step-by-Step Environment Setup
```bash
# 1. Fork and clone the repository
git clone https://github.com/<your-username>/HydroPulse-AI.git
cd HydroPulse-AI

# 2. Create and activate a virtual environment
python -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows PowerShell:
.\venv\Scripts\Activate.ps1

# 3. Upgrade pip and install development dependencies
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .

# 4. Copy environment configuration
cp .env.example .env
```

---

## 3. Coding & Quality Standards

All pull requests must pass the following automated quality checks:

### 1. Code Linting & Formatting
We use [Ruff](https://github.com/astral-sh/ruff) for lightning-fast linting and code formatting:
```bash
# Check code for lint errors
ruff check .

# Automatically apply safe fixes
ruff check --fix .

# Verify code formatting
ruff format --check .

# Automatically format code
ruff format .
```

### 2. Type Hints
Public functions, methods, and API route handlers must include complete Python type annotations:
```python
def calculate_spi(rainfall_series: pd.Series, scale_months: int = 3) -> pd.Series:
    """Compute Standardized Precipitation Index using two-parameter Gamma distribution."""
    ...
```

### 3. Testing & Coverage
We require a minimum of **80% code coverage** on all modules under `src/hydropulse/`:
```bash
# Run complete test suite with coverage
pytest --cov=src/hydropulse --cov-report=term-missing --cov-report=xml

# Run a specific test module
pytest tests/test_models.py -v
```

### 4. Data Leakage Prevention
Hydrological forecasting models strictly prohibit temporal data leakage:
- Shuffling time-series data during train/test splitting is strictly forbidden.
- Feature aggregations (lags, rolling means, antecedent precipitation) may use **past observations only** ($t \le 0$).
- Feature scalers and quantile thresholds must be fitted **exclusively on the training window**.
- Every model change must pass the temporal leakage test suite in `tests/test_leakage.py`.

---

## 4. Git Workflow & Conventional Commits

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification to ensure clean, automated changelogs:

### Commit Format
```
<type>(<scope>): <short description in imperative present tense>

[optional detailed body explaining *why* the change was made]
```

### Allowed Types
- `feat`: A new feature or machine learning model capability (e.g. `feat(api): add bilingual Hindi alerts`)
- `fix`: A bug fix or correction (e.g. `fix(wqi): handle zero dissolved oxygen without division by zero`)
- `test`: Adding or updating test suites (e.g. `test(events): add hit-rate evaluation for 2016 Damodar flood`)
- `docs`: Documentation additions or updates (e.g. `docs: add deployment instructions for Render`)
- `refactor`: Code reorganization that neither adds a feature nor fixes a bug
- `perf`: A code change that improves inference latency or memory consumption
- `ci`: Changes to CI/CD workflows, Dockerfiles, or container orchestration

---

## 5. Pull Request Submission Checklist

Before submitting a Pull Request, verify that you have completed each of the following:

- [ ] Branch is rebased onto the latest `main` branch.
- [ ] `ruff check .` reports zero errors or warnings.
- [ ] `ruff format --check .` passes.
- [ ] `pytest --cov=src/hydropulse` passes with all tests green and $\ge 80\%$ test coverage.
- [ ] No temporary files, local `.env`, SQLite databases (`*.db`), or raw scratch files are tracked.
- [ ] Any changed or new configuration settings are documented in `.env.example` and `config/settings.py`.
- [ ] Relevant documentation in `docs/` (`ARCHITECTURE.md`, `DATA_CARD.md`, `MODEL_CARD.md`, `LIMITATIONS.md`) has been updated to reflect new functionality.
