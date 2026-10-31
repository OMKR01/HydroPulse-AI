@echo off
REM Windows Make Helper for HydroPulse AI

if "%1" == "setup" (
    pip install -r requirements-dev.txt
    pip install -e .
    goto end
)
if "%1" == "lint" (
    ruff check .
    ruff format --check .
    goto end
)
if "%1" == "format" (
    ruff format .
    ruff check --fix .
    goto end
)
if "%1" == "test" (
    pytest
    goto end
)
if "%1" == "run" (
    python -m src.hydropulse.api.factory
    goto end
)
if "%1" == "refresh" (
    python -m src.hydropulse.pipeline.refresh
    goto end
)
if "%1" == "train" (
    python -m src.hydropulse.pipeline.train
    goto end
)

echo Usage: make.bat [setup^|lint^|format^|test^|run^|refresh^|train]
:end
