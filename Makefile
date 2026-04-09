# Makefile for GGDes project
# Run commands with: make <target>

.PHONY: help check-format format check-type check test clean install install-dev

# Default target shows help
help:
	@echo "Available targets:"
	@echo "  make install        - Install dependencies with uv"
	@echo "  make install-dev    - Install dev dependencies with uv"
	@echo ""
	@echo "  make format         - Format code with ruff"
	@echo "  make check-format   - Check linting and formatting with ruff"
	@echo "  make check-type     - Check type hints with mypy"
	@echo ""
	@echo "  make check          - Run all checks (format, lint, types)"
	@echo "  make test           - Run pytest test suite"
	@echo "  make all            - Run format, check, and test"
	@echo ""
	@echo "  make clean          - Clean generated files and caches"

# Installation targets
install:
	@echo "📦 Installing dependencies with uv..."
	uv sync

install-dev:
	@echo "📦 Installing dev dependencies with uv..."
	uv sync --extra dev

install-web:
	@echo "📦 Installing web dependencies with uv..."
	uv sync --extra web

# Formatting targets
format:
	@echo "🎨 Formatting code with ruff..."
	@uv run ruff format .
	@echo "✅ Formatting complete"

# Check targets
check-format:
	@echo "🔍 Checking formatting with ruff..."
	@uv run ruff format --check .
	@echo "✅ Format check passed"
	@echo ""
	@echo "🔍 Running linter (ruff check)..."
	@uv run ruff check .
	@echo "✅ Lint check passed"

check-type:
	@echo "🔍 Checking type hints with mypy..."
	@uv run mypy ggdes --ignore-missing-imports
	@echo "✅ Type check passed"

# Combined checks
check: check-format check-type
	@echo ""
	@echo "✅ All checks passed!"

# Testing target
test:
	@echo "🧪 Running tests with pytest..."
	@uv run pytest tests/ -v

# Combined target: format, check, test
all: format check test
	@echo ""
	@echo "✅ All tasks completed successfully!"

# Clean up generated files
clean:
	@echo "🧹 Cleaning up..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@rm -rf build/ dist/ *.egg-info/ 2>/dev/null || true
	@echo "✅ Cleanup complete"

# Development helpers
dev-setup: install-dev
	@echo "🛠️  Setting up development environment..."
	@echo "   Installing pre-commit hooks..."
	@uv run pre-commit install 2>/dev/null || echo "   (pre-commit not configured)"
	@echo "✅ Dev setup complete"

# Run the application
run:
	@uv run python -m ggdes.cli

# Run web interface
web:
	@uv run python -m ggdes.cli web

# Run TUI
tui:
	@uv run python -m ggdes.cli tui

# Run tests with coverage
test-cov:
	@echo "🧪 Running tests with coverage..."
	@uv run pytest tests/ -v --cov=ggdes --cov-report=html --cov-report=term
	@echo ""
	@echo "📊 Coverage report generated in htmlcov/"
