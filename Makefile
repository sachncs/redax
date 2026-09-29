.PHONY: help dev test test-cov lint typecheck readiness download-models bench load-bench eval build-server build-wasm build-all clean install verify verify-determinism load compose-verify

# pyproject.toml requires Python 3.13+. Set PYTHON explicitly when using a
# virtualenv managed by uv, pyenv, or another environment manager.
PYTHON ?= python3.13
HOST ?= 0.0.0.0
PORT ?= 8000

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install pinned deps from the lockfile, then the package
	$(PYTHON) -m pip install --require-hashes -r requirements.lock
	$(PYTHON) -m pip install -e . --no-deps

dev: ## Run the API server with autoreload
	$(PYTHON) -m uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

test: ## Run tests
	$(PYTHON) -m pytest

test-cov: ## Run tests with the enforced coverage threshold
	$(PYTHON) -m pytest --cov=app --cov-report=term-missing

lint: ## Run ruff
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

typecheck: ## Run mypy
	$(PYTHON) -m mypy app/

readiness: ## Validate the production-readiness matrix vocabulary and shape
	$(PYTHON) scripts/validate_readiness.py > /dev/null

verify-determinism: ## Property test: same input -> identical redacted output, repeatedly
	$(PYTHON) -m pytest tests/unit/test_determinism.py -v

verify: test lint typecheck verify-determinism readiness ## Full reproducibility gate: tests, lint, typecheck, determinism, readiness contract
	@echo "verify: all checks passed"

download-models: ## Download + sha256-verify pinned model snapshots (fail-loud on mismatch)
	$(PYTHON) scripts/download_models.py

load: ## Run locust against the running server (opt-in)
	$(PYTHON) -m locust -f tests/load/locustfile.py --host http://localhost:$$(PORT)

compose-verify: ## Verify the complete local Docker Compose stack
	$(PYTHON) scripts/verify_local_compose.py

bench: ## Run latency/throughput benchmark
	$(PYTHON) scripts/bench.py

load-bench: ## Run the bounded HTTP load baseline against a running API
	$(PYTHON) scripts/load_bench.py

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
