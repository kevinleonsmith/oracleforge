# OracleForge · Inference Service (Akash GPU)

The **non-deterministic** compute path. Serves sentence embeddings and LLM
question-drafting over HTTP, deployed to the Akash decentralized GPU network. Its
output only *suggests* markets upstream of generation — committed on-chain values
come from the deterministic Cartesi path — so running it on commodity GPUs is safe.

```
 generator ──RemoteEmbedder.embed()──▶ inference service (Akash GPU) ──▶ embeddings
                                         HuggingFace model + drafter
```

## Why stdlib HTTP

The server is `http.server`, not FastAPI — it keeps the GPU image small, has no web
framework to pin/patch, and runs (with a deterministic `HashingEmbedder` fallback)
with zero installs, so the whole thing is testable off-GPU. The real model stack
(`torch`, `sentence-transformers`) is the deploy-time extra.

## API

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/health` | — | `{status, embedder, dim, drafter, gpu}` |
| POST | `/embed` | `{texts: [...], normalize}` | `{model, dim, embeddings: [[...]]}` |
| POST | `/draft` | `{topic, signals: [...], category}` | `{question, model}` |

## Connect it to the generator

`RemoteEmbedder` satisfies the AI package's `Embedder` protocol, so market
generation uses GPU embeddings with a one-line swap:

```python
from oracleforge_inference.client import RemoteEmbedder
from oracleforge_ai import MarketGenerator

gen = MarketGenerator(embedder=RemoteEmbedder("http://<akash-uri>:80"))
gen.propose()   # clustering/dedupe now run on the remote model
```

(Tested end-to-end: the generator produces the same markets over HTTP as it does
in-process.)

## Run

```bash
# server locally (stdlib, HashingEmbedder fallback — no GPU needed)
python3 -m oracleforge_inference.cli serve --port 8070
# in another shell:
python3 -m oracleforge_inference.cli probe --url http://localhost:8070

# tests (stdlib only: engine, schemas, live server + client, SDL structure)
python3 -m unittest discover -s tests -t .
```

## Deploy to Akash

```bash
make build push          # build the CUDA image, push to a registry
make sdl                 # (re)generate deploy.yaml from deploy/sdl.py
provider-services tx deployment create deploy/deploy.yaml --from <wallet>
# then: create a lease with a bidding provider, send the manifest, read the URI
```

### SDL

`deploy/deploy.yaml` (GPU) and `deploy/deploy.staging.yaml` (CPU, cheaper) are
**generated** from `deploy/sdl.py` — edit the Python, run `make sdl`, not the YAML.
The GPU profile requests 1× NVIDIA (rtx4090/a100), 2 vCPU, 8Gi RAM, exposes the
service globally on port 80, and prices in `uakt`. Its structure is unit-tested.
