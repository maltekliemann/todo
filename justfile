default:
    @just --list

install:
    uv tool install --from . todo --reinstall --no-cache

test:
    uv run pytest tests/

lint:
    uv run ruff check src/ tests/
    uv run ruff format --check src/ tests/
    uv run mypy

fmt:
    uv run ruff check --fix src/ tests/
    uv run ruff format src/ tests/

cov:
    uv run pytest tests/ --cov=todo --cov-report=term-missing
