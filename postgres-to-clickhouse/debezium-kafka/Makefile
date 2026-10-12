COMPOSE := docker compose --file compose.yaml
PYTHON ?= python3

.PHONY: validate unit up smoke test logs down
validate:
	$(COMPOSE) config --quiet

unit:
	$(PYTHON) -m unittest discover -s tests -v

up: validate
	$(COMPOSE) up -d --wait --wait-timeout 300

smoke:
	$(PYTHON) scripts/smoke.py

test: unit
	PYTHON="$(PYTHON)" bash scripts/test.sh

logs:
	$(COMPOSE) logs --no-color

down:
	$(COMPOSE) down --remove-orphans
