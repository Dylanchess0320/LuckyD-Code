.PHONY: install dev test coverage lint clean build help

install:
	pip install -e .

dev:
	pip install -e ".[dev,rag-full]"

test:
	pytest

coverage:
	pytest --cov=luckyd_code --cov-report=term

lint:
	mypy luckyd_code --ignore-missing-imports

clean:
	rm -rf dist/ build/ *.egg-info/ .pytest_cache/ .coverage htmlcov/

build:
	pip install build
	python -m build

help:
	@grep -E '^[a-zA-Z_-]+:' $(MAKEFILE_LIST) | sort
