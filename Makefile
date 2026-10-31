.PHONY: help setup lint format test run train refresh clean docker-build docker-up

PYTHON ?= python
PIP ?= pip

help:
	@echo "HydroPulse AI Commands:"
	@echo "  make setup        - Install dependencies and setup editable package"
	@echo "  make lint         - Run ruff linter check"
	@echo "  make format       - Format code using ruff"
	@echo "  make test         - Run pytest with coverage"
	@echo "  make run          - Start Flask development server"
	@echo "  make refresh      - Trigger data refresh pipeline"
	@echo "  make train        - Train forecasting models"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-up    - Run application via docker-compose"

setup:
	$(PIP) install -r requirements-dev.txt
	$(PIP) install -e .

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

test:
	pytest

run:
	$(PYTHON) -m src.hydropulse.api.factory

refresh:
	$(PYTHON) -m src.hydropulse.pipeline.refresh

train:
	$(PYTHON) -m src.hydropulse.pipeline.train

docker-build:
	docker build -t hydropulse-ai:latest .

docker-up:
	docker compose up --build

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov
