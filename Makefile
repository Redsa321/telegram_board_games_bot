SHELL := /bin/bash

VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip
INSTALL_STAMP := $(VENV)/.bot-installed

.DEFAULT_GOAL := run

.PHONY: run admin setup test lint backup migrate-postgres help check-env

run: setup check-env
	$(PYTHON) -m telegram_board_games_bot

admin: setup check-env
	$(PYTHON) -m telegram_board_games_bot.admin_web

setup: $(INSTALL_STAMP)

$(PYTHON):
	python3 -m venv $(VENV)

$(INSTALL_STAMP): pyproject.toml requirements.lock | $(PYTHON)
	$(PIP) install -r requirements.lock
	$(PIP) install --no-deps -e .
	@touch $(INSTALL_STAMP)

check-env:
	@test -f .env || { echo "Missing .env. Run: cp .env.example .env"; exit 1; }

test: setup
	@$(PYTHON) -c "import pytest" 2>/dev/null || $(PIP) install pytest
	$(PYTHON) -m pytest -q

lint: setup
	@$(PYTHON) -c "import ruff" 2>/dev/null || $(PIP) install ruff
	$(PYTHON) -m ruff check .

backup: setup
	$(PYTHON) -m telegram_board_games_bot.backup backup --output backups --keep 7

migrate-postgres: setup check-env
	@test -n "$(SOURCE)" || { echo "Usage: make migrate-postgres SOURCE=/absolute/path/to/bot.db"; exit 1; }
	$(PYTHON) -m telegram_board_games_bot.migrate_to_postgres --source "$(SOURCE)" --confirm

help:
	@echo "make        Start the bot (default)"
	@echo "make run    Start the bot"
	@echo "make admin  Start the admin web server"
	@echo "make setup  Create the venv and install dependencies"
	@echo "make test   Run the test suite"
	@echo "make lint   Run Ruff"
	@echo "make backup Create a checked database backup"
	@echo "make migrate-postgres SOURCE=/path/to/bot.db  Import SQLite into configured PostgreSQL"
