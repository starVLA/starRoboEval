.PHONY: help check catalog smoke
.DEFAULT_GOAL := help
PYTHON ?= python3

help:
	@echo "make check    Parse active source, check ownership and validate the catalog"
	@echo "make catalog  List all 13 benchmark migration targets"
	@echo "make smoke    Run the dependency-free evaluation self-check"

check:
	$(PYTHON) -B -m benchkit catalog --check
	$(PYTHON) -B -m benchkit.checks.check_boundaries

catalog:
	$(PYTHON) -B -m benchkit catalog

smoke:
	$(PYTHON) -B -m benchkit smoke
