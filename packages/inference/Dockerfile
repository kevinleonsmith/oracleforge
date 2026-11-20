# OracleForge inference service — GPU image for Akash.
# CUDA runtime base; installs torch (CUDA), sentence-transformers, the AI package
# and this service. The server itself is stdlib (no FastAPI/uvicorn).
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/oracleforge

# torch CUDA build + model stack
RUN pip3 install --no-cache-dir \
    torch==2.4.1 --index-url https://download.pytorch.org/whl/cu124
RUN pip3 install --no-cache-dir \
    sentence-transformers==3.0.1 transformers==4.44.2

# the forecasting core (for the Embedder interface) + this service
COPY vendor/ai-market-generator /tmp/ai
RUN pip3 install --no-cache-dir /tmp/ai && rm -rf /tmp/ai
COPY oracleforge_inference ./oracleforge_inference

ENV OF_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
    OF_DEVICE=cuda OF_HOST=0.0.0.0 OF_PORT=8070

# warm the model into the image layer so cold start is fast
RUN python3 -c "from sentence_transformers import SentenceTransformer as S; S('${OF_MODEL}')" || true

EXPOSE 8070
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"OF_PORT\"]}/health')" || exit 1

CMD ["python3", "-m", "oracleforge_inference.cli", "serve"]
