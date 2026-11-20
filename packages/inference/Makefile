# OracleForge inference service — build, SDL, Akash deploy.
# Requires: Docker (build), Akash CLI `provider-services` (deploy), a funded AKT
# wallet + certificate. See https://docs.akash.network.

AI_PKG := ../ai-market-generator
IMAGE  := ghcr.io/oracleforge/inference:0.1.0

.PHONY: vendor build push sdl test serve deploy clean

## Copy the AI package into the build context (Docker can't reach parents).
vendor:
	@rm -rf vendor && mkdir -p vendor
	@cp -r $(AI_PKG) vendor/ai-market-generator
	@rm -rf vendor/ai-market-generator/tests vendor/ai-market-generator/__pycache__ \
	        vendor/ai-market-generator/oracleforge_ai/__pycache__
	@echo "vendored $(AI_PKG)"

build: vendor
	docker build -t $(IMAGE) .

push:
	docker push $(IMAGE)

## Regenerate deploy.yaml + deploy.staging.yaml from deploy/sdl.py.
sdl:
	python3 deploy/sdl.py

## Run the server locally (stdlib; HashingEmbedder fallback with no GPU stack).
serve:
	python3 -m oracleforge_inference.cli serve

test:
	python3 -m unittest discover -s tests -t .

## Create an Akash deployment from the GPU SDL (needs a funded wallet + cert).
deploy:
	provider-services tx deployment create deploy/deploy.yaml --from $(AKASH_KEY_NAME)

clean:
	@rm -rf vendor
