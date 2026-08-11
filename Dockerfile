# ============================================================
# ULTRON — RunPod Serverless Worker
# Base: CUDA 12.4.1 runtime + Ubuntu 22.04
# LLM: llama.cpp prebuilt binary (no compile step)
# ============================================================
#
# WHY PREBUILT:
#   Building llama.cpp from source inside Docker hits two problems:
#   1. cuMemMap / cuMemRelease linker errors — these VMM symbols live in
#      libcuda.so (the host driver stub), which is absent at image-build time.
#      The devel image only ships the toolkit, not the driver.
#   2. Build time — compiling all 673 targets takes 8-10 min, exceeding
#      RunPod's image-build CPU ulimit of 1800s.
#
#   Solution: download a prebuilt CUDA binary from ai-dock/llama.cpp-cuda.
#   The binary dynamically links libcuda.so at *runtime*, where RunPod's
#   GPU host driver provides it — exactly correct.
#
# TO UPGRADE llama.cpp: change LLAMA_VERSION below and rebuild.
# Latest releases: https://github.com/ai-dock/llama.cpp-cuda/releases
# ============================================================

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

LABEL maintainer="ultron-agent"
LABEL runpod.serverless="true"
LABEL description="ULTRON RunPod Serverless llama.cpp Agent"

ENV DEBIAN_FRONTEND=noninteractive

# ── System packages ────────────────────────────────────────────────────────────
# deadsnakes PPA is required for python3.11 on Ubuntu 22.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    jq \
    ca-certificates \
    python3.11 \
    python3.11-dev \
    python3.11-distutils \
    # Runtime CUDA libs the prebuilt llama-server needs
    libcublas-12-4 \
    && rm -rf /var/lib/apt/lists/*

# ── Python 3.11 as default ─────────────────────────────────────────────────────
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --set python3 /usr/bin/python3.11 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python

# bootstrap pip for 3.11 (apt's python3-pip targets 3.10)
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11

# ── llama-server prebuilt binary ───────────────────────────────────────────────
# RTX 4090 = compute capability 8.9 — covered by the cuda-12.8 build.
# The binary links libcuda.so at runtime via RunPod's GPU driver — no driver
# stub needed at build time.
#
# Pinned to b9628 (latest as of 2026-08-11). Change tag + rebuild to upgrade.
ARG LLAMA_VERSION=b9628
ARG LLAMA_CUDA=12.8

RUN set -e && \
    TARBALL="llama.cpp-${LLAMA_VERSION}-cuda-${LLAMA_CUDA}-amd64.tar.gz" && \
    URL="https://github.com/ai-dock/llama.cpp-cuda/releases/download/${LLAMA_VERSION}/${TARBALL}" && \
    echo "Downloading llama.cpp ${LLAMA_VERSION} (CUDA ${LLAMA_CUDA})..." && \
    wget -q --show-progress -O /tmp/llama.tar.gz "${URL}" && \
    mkdir -p /tmp/llama && \
    tar -xzf /tmp/llama.tar.gz -C /tmp/llama && \
    # Binary lives at cuda-<ver>/llama-server inside the tarball
    find /tmp/llama -name "llama-server" -type f | head -1 \
        | xargs -I{} install -m 755 {} /usr/local/bin/llama-server && \
    rm -rf /tmp/llama /tmp/llama.tar.gz && \
    echo "llama-server installed: $(llama-server --version 2>&1 | head -1)"

# ── Python dependencies ────────────────────────────────────────────────────────
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# ── Application files ──────────────────────────────────────────────────────────
WORKDIR /app
COPY handler.py .
COPY health_shim.py .
COPY entrypoint.sh .
COPY JARVIS_PROMPT.md ./AGENT_PROMPT.md
RUN chmod +x entrypoint.sh

# ── Runtime environment defaults ───────────────────────────────────────────────
ENV VOLUME_PATH=/runpod-volume
ENV MODEL_PATH=/runpod-volume/model
ENV TOOLS_PATH=/runpod-volume/tools
ENV MEMORY_PATH=/runpod-volume/memory
ENV BRIDGE_PATH=/runpod-volume/bridge
ENV LOG_PATH=/runpod-volume/logs
ENV MODEL_FILENAME=Qwen2.5-Coder-14B-Instruct-abliterated-Q4_K_M.gguf
ENV MODEL_REPO=bartowski/Qwen2.5-Coder-14B-Instruct-abliterated-GGUF
ENV CONTEXT_SIZE=8192
ENV N_GPU_LAYERS=999
ENV N_PARALLEL=2
ENV BATCH_SIZE=512
ENV AGENT_NAME=ULTRON
ENV MAX_TOOL_ITERATIONS=10
ENV MEMORY_WINDOW=20
# LLAMA_SERVER_API_KEY — set as a Secret in RunPod endpoint settings, never here

ENTRYPOINT ["bash", "entrypoint.sh"]
