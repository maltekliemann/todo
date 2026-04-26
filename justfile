default:
    @just --list

install:
    uv tool install --from . todo --reinstall --no-cache

test:
    python -m pytest tests/

lint:
    ruff check src/ tests/
    mypy

fmt:
    ruff check --fix src/ tests/
    ruff format src/ tests/

cov:
    python -m pytest tests/ --cov=todo --cov-report=term-missing
