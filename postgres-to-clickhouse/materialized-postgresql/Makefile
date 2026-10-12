COMPOSE := docker compose
.PHONY: validate up test demo down
validate:
	$(COMPOSE) --profile test config --quiet
up:
	$(COMPOSE) up -d --wait --wait-timeout 240
test: validate up
	$(COMPOSE) --profile test run --build --rm tests
demo: validate up
	$(COMPOSE) --profile test run --build --rm tests python recipe.py --keep
down:
	$(COMPOSE) --profile test down --remove-orphans
