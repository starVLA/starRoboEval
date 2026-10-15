.PHONY: help check catalog smoke
.DEFAULT_GOAL := help
PYTHON ?= python3

help:
	@echo "make check    Validate the benchmark catalog"
	@echo "make catalog  List the benchmark catalog"
	@echo "make smoke    Run the dependency-free evaluation self-check"

check:
	$(PYTHON) -B -m benchkit catalog --check

catalog:
	$(PYTHON) -B -m benchkit catalog

smoke:
	$(PYTHON) -B -m benchkit smoke
