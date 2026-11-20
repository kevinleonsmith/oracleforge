# OracleForge · Cartesi dApp

The **deterministic compute layer**. Packages the OracleForge forecaster as a
[Cartesi Rollups](https://docs.cartesi.io) application: the Monte Carlo / Bayesian
math runs inside a RISC-V Cartesi Machine, and every result is committed as a
**notice** — verifiable on-chain and replayable under a fraud proof.

## Why this exists

The headline AI probability a market opens with is committed state, so it must be
reproducible: same inputs → byte-identical output on every validator and on
dispute replay. A GPU model can't give that. So the settlement-relevant forecast
runs here, in the deterministic machine, seeded from a hash of its inputs. The
non-deterministic GPU path (HF embeddings, LLM drafting) only *suggests* markets
upstream and never produces committed state.

## Contents

| File | Role |
|------|------|
| `Dockerfile` | Builds the Cartesi Machine rootfs (RISC-V Python + emulator tools + the forecaster) |
| `dapp.py` | Machine entrypoint: the rollup advance/inspect HTTP loop (I/O glue only) |
| `handler.py` | Pure request → output logic (forecast / bayes), unit-tested off-machine |
| `Makefile` | `vendor` · `build` · `run` · `test` · `deploy` |
| `tests/` | Off-machine handler tests (no Docker needed) |
| `samples/` | Example request payloads |

## Request / response

Requests are JSON, hex-encoded on the wire. Advance (state-changing) requests
return a **notice**; inspect (read-only) requests return a **report**.

```json
// advance input
{"op": "forecast", "question": "Will US CPI print below 2.6% YoY?", "priors": [0.62], "samples": 50000}
// notice emitted
{"op": "forecast", "prob_bps": 8697, "prob_yes": 0.8697, "seed": 1734…, "input_hash": "0x…", "samples": 50000}
```

Also supports `{"op": "bayes", "prior_prob": 0.5, "likelihood_ratio": 3.0}`.

## Develop

```bash
# verify the handler logic — no Docker/RISC-V required
make test

# build the machine image (vendors the forecaster, then `cartesi build`)
make build

# run locally: anvil + rollup node + this machine
make run

# then send a forecast request (Cartesi CLI):
cartesi send generic --input "$(cat samples/forecast.json)"
# inspect (read-only):
curl "http://localhost:8080/inspect/$(cat samples/forecast.json | xxd -p | tr -d '\n')"
```

Prereqs for build/run: **[Cartesi CLI](https://docs.cartesi.io/cartesi-rollups/development/installation/)**
(`npm i -g @cartesi/cli`) and Docker with RISC-V emulation
(`docker run --privileged --rm tonistiigi/binfmt --install all`).

## How a market uses it

1. The AI generator (`packages/ai-market-generator`) assembles a forecast request.
2. The request is sent to this dApp as an advance.
3. The machine runs `monte_carlo_forecast` and emits a notice with `prob_bps`.
4. The relayer reads the notice and calls `MarketEngine.createMarket(..., aiProbBps)`
   on Gnosis — so the market's opening probability is a value anyone can reproduce
   and, if challenged, prove on-chain.

> The RAM size and SDK version are set via `LABEL` in the Dockerfile. Bump RAM
> before enabling any model-backed path; the stdlib forecaster fits comfortably
> in 128Mi.
