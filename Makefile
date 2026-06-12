.PHONY: help install lint format format-check typecheck ci-local hooks build clean

PYTHON := uv run
PKG    := giulia

help:
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies (including dev)
	uv sync

lint: ## Run ruff linter
	$(PYTHON) ruff check .

format: ## Auto-format with ruff
	$(PYTHON) ruff format .

format-check: ## Check formatting without modifying files
	$(PYTHON) ruff format --check .

typecheck: ## Run pyright type checker
	$(PYTHON) pyright

ci-local: ## Run the full CI pipeline locally (fail-fast)
	uv sync
	$(PYTHON) ruff check .
	$(PYTHON) ruff format --check .
	$(PYTHON) pyright

hooks: ## Install pre-commit hooks
	$(PYTHON) pre-commit install

build: ## Build the giulia wheel and sdist
	uv build --project packages/giulia --out-dir dist

clean: ## Remove build artifacts and caches
	rm -rf dist/ build/ .coverage htmlcov/ .pytest_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find packages -name "*.egg-info" -exec rm -rf {} +
