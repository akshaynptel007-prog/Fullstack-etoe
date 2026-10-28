SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

COMPOSE          ?= docker compose
COMPOSE_LOADTEST := $(COMPOSE) -f docker-compose.yml -f docker-compose.loadtest.yml
BASE_URL         ?= http://localhost:8080
ADMIN_API_KEY    ?= local-admin-key

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Local stack -------------------------------------------------------------
.PHONY: up down restart logs ps clean
up: ## Build and start the full stack (http://localhost:8080)
	$(COMPOSE) up -d --build
	@echo "App: $(BASE_URL)   RabbitMQ UI: http://localhost:15672 (flash/flash)"

down: ## Stop the stack (keeps volumes)
	$(COMPOSE) --profile observability --profile test --profile loadtest down

restart: down up ## Restart the stack

logs: ## Tail API + worker logs
	$(COMPOSE) logs -f --tail=100 api worker

ps: ## Show service status
	$(COMPOSE) ps

clean: ## Stop the stack and delete all volumes (DESTROYS local data)
	$(COMPOSE) --profile observability --profile test --profile loadtest down -v --remove-orphans

observability: ## Start Prometheus (:59090) + Grafana (:53000)
	$(COMPOSE) --profile observability up -d prometheus grafana

reset-sale: ## Reset the seeded sale (STOCK=500 STARTS_IN=30)
	BASE_URL=$(BASE_URL) ADMIN_API_KEY=$(ADMIN_API_KEY) ./scripts/reset-sale.sh --stock $${STOCK:-500} --starts-in $${STARTS_IN:-30}

# --- Quality -----------------------------------------------------------------
.PHONY: test test-backend test-frontend lint fmt
test: test-backend test-frontend ## Run all tests

test-backend: ## Backend unit + integration tests (inside Docker, against real Postgres/Redis/RabbitMQ)
	$(COMPOSE) --profile test run --rm --build backend-tests

test-frontend: ## Frontend unit tests, type-check, build and bundle-size budget
	cd frontend && npm ci && npm run typecheck && npm test && npm run build && npm run check:size

lint: ## Lint backend + frontend
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app
	cd frontend && npm run lint

fmt: ## Auto-format backend + terraform
	cd backend && uv run ruff format . && uv run ruff check --fix .
	terraform -chdir=infra/terraform fmt -recursive

# --- Load testing ------------------------------------------------------------
.PHONY: loadtest
loadtest: ## Spike test with k6 (5k users, stock 500) and verify zero oversell
	./loadtest/run.sh

# --- AWS -----------------------------------------------------------------------
.PHONY: tf-validate deploy destroy
tf-validate: ## terraform fmt-check + validate (no AWS calls)
	terraform -chdir=infra/terraform fmt -check -recursive
	terraform -chdir=infra/terraform init -backend=false -input=false >/dev/null
	terraform -chdir=infra/terraform validate

deploy: ## Provision AWS + build/push images + migrate + upload SPA
	./scripts/deploy.sh

destroy: ## Tear down all AWS resources
	./scripts/destroy.sh
