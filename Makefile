.PHONY: help dev test lint typecheck download-models bench eval build-server build-wasm build-all clean install verify verify-determinism load

# pyproject.toml requires-python >= 3.11; mypy runs against 3.12. Override
# with `PYTHON=python3.11 make verify` if you must lock to a specific
# interpreter.
PYTHON ?= python3
HOST ?= 0.0.0.0
PORT ?= 8000

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install pinned deps from the lockfile, then the package
	$(PYTHON) -m pip install -r requirements.lock
	$(PYTHON) -m pip install -e . --no-deps

dev: ## Run the API server with autoreload
	$(PYTHON) -m uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

test: ## Run tests
	$(PYTHON) -m pytest

lint: ## Run ruff
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

typecheck: ## Run mypy
	$(PYTHON) -m mypy app/

verify-determinism: ## Property test: same input -> identical redacted output, repeatedly
	$(PYTHON) -m pytest tests/unit/test_determinism.py -v

verify: test lint typecheck verify-determinism ## Full reproducibility gate: tests, lint, typecheck, determinism
	@echo "verify: all checks passed"

download-models: ## Download + sha256-verify pinned model snapshots (fail-loud on mismatch)
	$(PYTHON) scripts/download_models.py

load: ## Run locust against the running server (opt-in)
	$(PYTHON) -m locust -f tests/load/locustfile.py --host http://localhost:$$(PORT)

bench: ## Run latency/throughput benchmark
	$(PYTHON) scripts/bench.py

eval: ## Run P/R/F1 eval against labeled fixtures
	$(PYTHON) scripts/eval.py

build-server: ## Build the Docker image
	$(PYTHON) scripts/download_models.py && docker build -t redax/redax:0.1.0 .

build-wasm: ## Export ONNX + quantize + bundle WASM
	$(PYTHON) scripts/export_onnx.py
	$(PYTHON) scripts/quantize.py

build-all: build-server build-wasm ## Build server + WASM bundle

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov dist build
	find . -type d -name __pycache__ -exec rm -rf {} +
