# OracleForge Cartesi dApp — build & dev tasks.
# Requires the Cartesi CLI (https://docs.cartesi.io): `npm i -g @cartesi/cli`
# and Docker with RISC-V emulation (`docker run --privileged tonistiigi/binfmt`).

AI_PKG := ../ai-market-generator
VENDOR := vendor/ai-market-generator

.PHONY: vendor build run test clean deploy

## Copy the forecasting core into the build context (Docker can't reach parents).
vendor:
	@rm -rf vendor && mkdir -p vendor
	@cp -r $(AI_PKG) $(VENDOR)
	@rm -rf $(VENDOR)/tests $(VENDOR)/__pycache__ $(VENDOR)/oracleforge_ai/__pycache__
	@echo "vendored $(AI_PKG) -> $(VENDOR)"

## Build the Cartesi Machine image (reproducible rootfs).
build: vendor
	cartesi build

## Run the node locally (anvil + rollup server + this machine).
run:
	cartesi run

## Verify the dApp handler logic off-machine (no Docker/RISC-V needed).
test:
	python3 -m unittest discover -s tests -t .

## Deploy the machine + rollups contracts to a network (see `cartesi deploy`).
deploy: build
	cartesi deploy

clean:
	@rm -rf vendor .cartesi
