PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
XETRACK := $(VENV)/bin/xetrack

.PHONY: venv install run test clean-venv

venv: $(VENV_PYTHON)

$(VENV_PYTHON):
	$(PYTHON) -m venv --system-site-packages $(VENV)

install: $(XETRACK)

$(XETRACK): pyproject.toml $(shell find src -type f -name '*.py') | $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip install --no-build-isolation -e .

run: $(XETRACK)
	$(XETRACK)

test: $(XETRACK)
	$(VENV_PYTHON) -m unittest discover -s tests

clean-venv:
	rm -rf $(VENV)
