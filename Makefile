SHELL := /bin/bash

VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip
INSTALL_STAMP := $(VENV)/.bot-installed

.DEFAULT_GOAL := run

.PHONY: run setup test lint backup help check-env

run: setup check-env
	$(PYTHON) -m telegram_board_games_bot

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

help:
	@echo "make        Start the bot (default)"
	@echo "make run    Start the bot"
	@echo "make setup  Create the venv and install dependencies"
	@echo "make test   Run the test suite"
	@echo "make lint   Run Ruff"
	@echo "make backup Create a checked SQLite backup"
