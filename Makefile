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

test: ## Runs unit tests in the image (FOCA's base image pins the dependencies), shows coverage and writes coverage.xml.
	docker build -t pubgrade:test .
	mkdir -p reports
	docker run --rm --user 0 --workdir /app --volume "$(CURDIR)/reports:/reports" pubgrade:test sh -c \
		"pip install --quiet --editable '.[test]' && coverage run -m pytest; status=\$$?; \
		coverage xml -o /reports/coverage.xml; chown -R $(shell id -u):$(shell id -g) /reports; \
		[ \$$status -eq 0 ] && coverage report -m"

install-pubgrade: # build ## Install pubgrade on cluster using helm.
#	kubectl create namespace $(APP_NAME) --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install $(APP_NAME) helm/ -n $(APP_NAME)

uninstall-pubgrade: ## Uninstall pubgrade.
	helm delete $(APP_NAME) -n $(APP_NAME)
	kubectl delete namespace $(APP_NAME)
