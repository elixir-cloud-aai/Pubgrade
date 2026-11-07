IMAGE_NAME_PUBGRADE=elixircloud/pubgrade:dev
IMAGE_NAME_UPDATER=elixircloud/pubgrade-updater:dev
APP_NAME=pubgrade



.PHONY: help

help: ## This help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help


build: ## Builds two container images (main-service, build-complete-updater).
	docker build -t $(IMAGE_NAME_PUBGRADE) .
	docker build -f build-complete-updater/Dockerfile -t $(IMAGE_NAME_UPDATER) .

test: ## Installs the locked dependencies (uv), runs the unit tests with coverage and writes coverage.xml.
	uv sync --locked
	uv run --locked pytest --cov --cov-report=term-missing --cov-report=xml

lint: ## Runs the linters, type checks and security checks of pre-commit on all files.
	uv sync --locked --all-groups
	uv run --locked pre-commit run --all-files
	uv run --locked pre-commit run --all-files --hook-stage manual gitleaks-all

install-pubgrade: # build ## Install pubgrade on cluster using helm (values in HELM_ARGS, see the README).
#	kubectl create namespace $(APP_NAME) --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install $(APP_NAME) helm/ -n $(APP_NAME) $(HELM_ARGS)

uninstall-pubgrade: ## Uninstall pubgrade.
	helm delete $(APP_NAME) -n $(APP_NAME)
	kubectl delete namespace $(APP_NAME)
