.PHONY: install dev test coverage lint typecheck secrets-scan clean build help

install:
	pip install -e .

dev:
	pip install -e ".[dev,rag-full]"

test:
	pytest

coverage:
	pytest --cov=luckyd_code --cov-report=term

lint:
	mypy luckyd_code

typecheck: lint

# Scan git history for accidentally committed secrets.
# Run this once after cloning, especially if you cloned before v1.2.1.
secrets-scan:
	@command -v gitleaks >/dev/null 2>&1 || (echo "Install gitleaks: https://github.com/gitleaks/gitleaks" && exit 1)
	gitleaks detect --source . --log-level warn

clean:
	rm -rf dist/ build/ *.egg-info/ .pytest_cache/ .coverage htmlcov/

build:
	pip install build
	python -m build

help:
	@grep -E '^[a-zA-Z_-]+:' $(MAKEFILE_LIST) | sort
