.PHONY: help dev test lint typecheck bench eval build-server build-wasm build-all clean install

PYTHON ?= python3.11
HOST ?= 0.0.0.0
PORT ?= 8000

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime + dev deps into current env
	$(PYTHON) -m pip install -e ".[dev]"

dev: ## Run the API server with autoreload
	$(PYTHON) -m uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

test: ## Run tests
	$(PYTHON) -m pytest

lint: ## Run ruff
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

typecheck: ## Run mypy
	$(PYTHON) -m mypy app/

bench: ## Run latency/throughput benchmark
	$(PYTHON) scripts/bench.py

eval: ## Run P/R/F1 eval against labeled fixtures
	$(PYTHON) scripts/eval.py

build-server: ## Build the Docker image
	docker build -t redax/redax:0.1.0 .

build-wasm: ## Export ONNX + quantize + bundle WASM
	$(PYTHON) scripts/export_onnx.py
	$(PYTHON) scripts/quantize.py

build-all: build-server build-wasm ## Build server + WASM bundle

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov dist build
	find . -type d -name __pycache__ -exec rm -rf {} +
