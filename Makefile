IMAGE_NAME_PUBGRADE=akash7778/pubgrade
IMAGE_NAME_UPDATER=akash7778/pubgrade-updater
APP_NAME=pubgrade



.PHONY: help

help: ## This help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help


build: ## Builds two container images (main-service, build-complete-updater).
	docker build -t $(IMAGE_NAME_PUBGRADE) .
	docker build -f build-complete-updater/Dockerfile -t $(IMAGE_NAME_UPDATER) .

test: ## Runs unit tests and shows coverage.
	coverage run --source pubgrade -m pytest
	coverage report -m

install-pubgrade: build ## Install application on cluster using helm.
	kubectl create namespace $(APP_NAME)
	sed -i 's#akash7778/pubgrade:test_build#$(IMAGE_NAME_PUBGRADE)#g' deployment/values.yaml
	sed -i 's#akash7778/notify-completion#$(IMAGE_NAME_UPDATER)#g' deployment/values.yaml
	helm install deployment/ $(APP_NAME) -n $(APP_NAME)

