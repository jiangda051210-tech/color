.PHONY: install install-dev lint lint-fix format format-check typecheck check test test-blindspots test-security e2e release-gate run run-prod docker-build docker-run clean

PYTHON ?= python
PIP := $(PYTHON) -m pip
RUFF := $(PYTHON) -m ruff
MYPY := $(PYTHON) -m mypy
PYTEST := $(PYTHON) -m pytest

RUFF_TARGETS := elite_runtime.py elite_quality_history.py run_full_e2e_flow.py run_release_gate.py test_production_blindspots.py test_security_and_perf.py
RUFF_LINT_FLAGS := --select F,B --ignore B007,B008,B904,B905

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements.txt
	$(PIP) install ruff mypy

lint:
	$(RUFF) check $(RUFF_TARGETS) $(RUFF_LINT_FLAGS)

lint-fix:
	$(RUFF) check $(RUFF_TARGETS) --fix $(RUFF_LINT_FLAGS)

format:
	$(RUFF) format $(RUFF_TARGETS)

format-check:
	$(RUFF) format --check $(RUFF_TARGETS)

typecheck:
	$(MYPY) --ignore-missing-imports elite_runtime.py elite_quality_history.py run_release_gate.py

check: lint format-check typecheck

test:
	$(PYTEST) test_production_blindspots.py test_security_and_perf.py -v --tb=short

test-blindspots:
	$(PYTEST) test_production_blindspots.py -v --tb=short

test-security:
	$(PYTEST) test_security_and_perf.py -v --tb=short

e2e:
	$(PYTHON) run_full_e2e_flow.py

release-gate:
	$(PYTHON) run_release_gate.py --quick-check

run:
	$(PYTHON) -m uvicorn elite_api:app --host 0.0.0.0 --port 8877 --reload --log-level info

run-prod:
	$(PYTHON) -m uvicorn elite_api:app --host 0.0.0.0 --port 8877 --workers 2 --log-level info

docker-build:
	docker build -t senia-elite-color:latest .

docker-run:
	docker run --rm -p 8877:8877 \
	  -v "$$(pwd)/data:/data" \
	  --env-file .env \
	  senia-elite-color:latest

clean:
	$(PYTHON) -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]; [f.unlink() for f in pathlib.Path('.').rglob('*.pyc') if f.exists()]; [shutil.rmtree(pathlib.Path(n), ignore_errors=True) for n in ('.pytest_cache', '.mypy_cache', '.ruff_cache', 'dist', 'build')]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').glob('*.egg-info')]"