.PHONY: install install-dev lint format typecheck test test-blindspots e2e release-gate run clean

# ── Setup ─────────────────────────────────────────────────────────────────────

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt
	pip install ruff mypy pytest pytest-asyncio httpx

# ── Code quality ──────────────────────────────────────────────────────────────

lint:
	ruff check .

lint-fix:
	ruff check --fix .

format:
	ruff format .

format-check:
	ruff format --check .

typecheck:
	mypy --ignore-missing-imports elite_runtime.py elite_quality_history.py

check: lint format-check typecheck

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	pytest test_production_blindspots.py -v --tb=short

e2e:
	python run_full_e2e_flow.py

release-gate:
	python run_release_gate.py --quick-check

# ── Run ───────────────────────────────────────────────────────────────────────

run:
	python -m uvicorn elite_api:app --host 0.0.0.0 --port 8877 --reload --log-level info

run-prod:
	python -m uvicorn elite_api:app --host 0.0.0.0 --port 8877 --workers 2 --log-level info

# ── Docker ────────────────────────────────────────────────────────────────────

docker-build:
	docker build -t senia-elite-color:latest .

docker-run:
	docker run --rm -p 8877:8877 \
	  -v "$$(pwd)/data:/data" \
	  --env-file .env \
	  senia-elite-color:latest

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build *.egg-info
