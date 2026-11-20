# syntax=docker.io/docker/dockerfile:1
# -----------------------------------------------------------------------------
# OracleForge Cartesi Machine image.
#
# `cartesi build` runs this Dockerfile for the RISC-V target and snapshots the
# resulting filesystem into a reproducible Cartesi Machine rootfs. The image
# bundles Python, the machine-emulator-tools (which provide `rollup-init`), the
# deterministic forecasting core (vendored from packages/ai-market-generator),
# and the dApp entrypoint.
#
# Build (from this directory):   make build      # runs `make vendor` then `cartesi build`
# Run locally:                   cartesi run
# -----------------------------------------------------------------------------
FROM --platform=linux/riscv64 riscv64/python:3.11.9-slim-bookworm AS base

# machine-emulator-tools provides rollup-init, the /dev/rollup driver glue, etc.
ARG MACHINE_EMULATOR_TOOLS_VERSION=0.15.0
ADD https://github.com/cartesi/machine-emulator-tools/releases/download/v${MACHINE_EMULATOR_TOOLS_VERSION}/machine-emulator-tools-v${MACHINE_EMULATOR_TOOLS_VERSION}.deb /tmp/
RUN dpkg -i /tmp/machine-emulator-tools-v${MACHINE_EMULATOR_TOOLS_VERSION}.deb \
    && rm /tmp/machine-emulator-tools-v${MACHINE_EMULATOR_TOOLS_VERSION}.deb

# Rollups SDK metadata + the machine RAM size. 128Mi is ample for the stdlib
# forecaster; raise it before enabling the Transformer/LLM path.
LABEL io.cartesi.rollups.sdk_version=0.11.1
LABEL io.cartesi.rollups.ram_size=128Mi

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends busybox-static \
    && rm -rf /var/lib/apt/lists/* /var/log/* /var/cache/*
RUN useradd --create-home --user-group dapp

WORKDIR /opt/cartesi/dapp

# dApp runtime deps (just `requests` to talk to the rollup HTTP server).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Deterministic forecasting core. `make vendor` copies packages/ai-market-generator
# into ./vendor so it is inside the build context. Installed as a normal package
# so `from oracleforge_ai.cartesi import monte_carlo_forecast` resolves on-machine.
COPY vendor/ai-market-generator /tmp/ai
RUN pip install --no-cache-dir /tmp/ai && rm -rf /tmp/ai

COPY dapp.py handler.py ./

ENV ROLLUP_HTTP_SERVER_URL="http://127.0.0.1:5004"
ENTRYPOINT ["rollup-init"]
CMD ["python3", "dapp.py"]
