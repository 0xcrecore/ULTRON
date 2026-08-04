# =============================================================================
# ULTRON — RunPod Serverless Worker
# llama.cpp (CUDA) + Python Handler
# =============================================================================
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    LLAMA_CUBLAS=1

# --- System deps ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential cmake curl ca-certificates \
    python3 python3-pip python3-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Build llama.cpp with CUDA support ---
WORKDIR /opt
RUN git clone --depth 1 https://github.com/ggerganov/llama.cpp.git && \
    cd llama.cpp && \
    cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release && \
    cmake --build build --config Release -j"$(nproc)" --target llama-server && \
    cp build/bin/llama-server /usr/local/bin/llama-server && \
    cd /opt && rm -rf llama.cpp

# --- Python deps ---
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# --- App code ---
COPY handler.py health_shim.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Model cache dir (network volume mounts here on RunPod)
RUN mkdir -p /runpod-volume/model

EXPOSE 8000 8001

ENTRYPOINT ["./entrypoint.sh"]
