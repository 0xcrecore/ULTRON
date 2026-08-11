#!/usr/bin/env bash
# ============================================================
# ULTRON — Container Entrypoint
#
# Startup sequence (FAST PATH — never blocks on download):
#   1. Create directory structure on Network Volume
#   2. Start RunPod handler immediately (background)
#      → handler responds to jobs even while model downloads
#   3. Download model if not cached (can take 15+ min first time)
#   4. Start llama-server once model is ready
#   5. Start health_shim
#   6. Signal handler that llama-server is ready
#
# WHY THIS ORDER:
#   RunPod's job timeout starts the moment the worker is assigned a job.
#   If handler.py isn't running yet, the job times out. By starting
#   handler.py first, it can immediately accept the job and return a
#   "warming up" response instead of the job expiring silently.
#
#   MODEL_READY_FILE acts as a semaphore. handler.py polls for it before
#   forwarding requests to llama-server.
# ============================================================

set -euo pipefail

log() { echo "[ULTRON] $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"; }
die() { log "FATAL: $*" >&2; exit 1; }

log "Starting ULTRON agent..."

# ── Directory structure ────────────────────────────────────────────────────────
VOLUME_PATH="${VOLUME_PATH:-/runpod-volume}"
MODEL_PATH="${MODEL_PATH:-${VOLUME_PATH}/model}"
TOOLS_PATH="${TOOLS_PATH:-${VOLUME_PATH}/tools}"
MEMORY_PATH="${MEMORY_PATH:-${VOLUME_PATH}/memory}"
BRIDGE_PATH="${BRIDGE_PATH:-${VOLUME_PATH}/bridge}"
LOG_PATH="${LOG_PATH:-${VOLUME_PATH}/logs}"
MODEL_READY_FILE="${VOLUME_PATH}/.model_ready"

mkdir -p "$MODEL_PATH" "$TOOLS_PATH" "$MEMORY_PATH" "$BRIDGE_PATH" "$LOG_PATH"
log "Volume directories ready at ${VOLUME_PATH}"

# ── Initialize tool registry if missing ───────────────────────────────────────
REGISTRY="${TOOLS_PATH}/registry.json"
if [ ! -f "$REGISTRY" ]; then
    python3 -c "
import json, datetime
d = {'version': '1.0', 'tools': [], 'created_at': datetime.datetime.utcnow().isoformat()}
open('${REGISTRY}', 'w').write(json.dumps(d, indent=2))
"
    log "Tool registry initialized"
fi

# ── Model vars ────────────────────────────────────────────────────────────────
MODEL_FILENAME="${MODEL_FILENAME:-Qwen2.5-Coder-14B-Instruct-abliterated-Q4_K_M.gguf}"
MODEL_FILE="${MODEL_PATH}/${MODEL_FILENAME}"
MODEL_REPO="${MODEL_REPO:-bartowski/Qwen2.5-Coder-14B-Instruct-abliterated-GGUF}"
LLAMA_SERVER_API_KEY="${LLAMA_SERVER_API_KEY:-ultron}"
CONTEXT_SIZE="${CONTEXT_SIZE:-8192}"
N_GPU_LAYERS="${N_GPU_LAYERS:-999}"
N_PARALLEL="${N_PARALLEL:-2}"
BATCH_SIZE="${BATCH_SIZE:-512}"

# Export so handler.py can read them
export MODEL_READY_FILE LLAMA_SERVER_API_KEY

# ── PIDs (populated below) ────────────────────────────────────────────────────
HANDLER_PID=""
LLAMA_PID=""
HEALTH_PID=""

cleanup() {
    log "Shutting down ULTRON..."
    [ -n "$HANDLER_PID" ] && kill "$HANDLER_PID" 2>/dev/null || true
    [ -n "$LLAMA_PID"  ] && kill "$LLAMA_PID"  2>/dev/null || true
    [ -n "$HEALTH_PID" ] && kill "$HEALTH_PID" 2>/dev/null || true
    log "Shutdown complete."
}
trap cleanup EXIT TERM INT

# ── STEP 1: Start handler immediately so RunPod can assign jobs ───────────────
# handler.py checks MODEL_READY_FILE and returns {"status":"warming_up"} until
# llama-server is ready, instead of blocking or timing out.
log "Starting RunPod handler (early start — model may still be loading)..."
python3 /app/handler.py >> "${LOG_PATH}/handler.log" 2>&1 &
HANDLER_PID=$!
log "Handler started (PID: ${HANDLER_PID})"

# Give handler a moment to register with RunPod
sleep 3

# ── STEP 2: Download model if not cached ──────────────────────────────────────
# Remove stale ready-file in case a previous run left it but the model is gone
[ ! -f "$MODEL_FILE" ] && rm -f "$MODEL_READY_FILE"

if [ -f "$MODEL_FILE" ]; then
    FILE_SIZE=$(du -sh "$MODEL_FILE" | cut -f1)
    log "Model already cached: ${MODEL_FILE} (${FILE_SIZE}) — skipping download"
else
    log "Downloading model (~20 GB). Jobs will receive 'warming_up' until done."
    log "  Repo: ${MODEL_REPO}  File: ${MODEL_FILENAME}"

    python3 - <<PYEOF
import os, sys
try:
    from huggingface_hub import hf_hub_download
    path = hf_hub_download(
        repo_id=os.environ["MODEL_REPO"],
        filename=os.environ["MODEL_FILENAME"],
        local_dir=os.environ["MODEL_PATH"],
        local_dir_use_symlinks=False,
    )
    print(f"[ULTRON] Download complete: {path}")
except Exception as e:
    print(f"[ULTRON] huggingface_hub failed: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF

    # Fallback: wget
    if [ ! -f "$MODEL_FILE" ]; then
        HF_URL="https://huggingface.co/${MODEL_REPO}/resolve/main/${MODEL_FILENAME}"
        log "Falling back to wget: ${HF_URL}"
        wget --no-verbose --show-progress -O "$MODEL_FILE" "$HF_URL" \
            || die "Model download failed"
    fi

    [ -f "$MODEL_FILE" ] || die "Model file missing after download"
    FILE_SIZE=$(du -sh "$MODEL_FILE" | cut -f1)
    log "Download complete: ${FILE_SIZE}"
fi

# ── STEP 3: Start llama-server ────────────────────────────────────────────────
log "Starting llama-server on port 8000..."
log "  Context: ${CONTEXT_SIZE} | GPU layers: ${N_GPU_LAYERS} | Parallel: ${N_PARALLEL}"

llama-server \
    --model "$MODEL_FILE" \
    --host 0.0.0.0 \
    --port 8000 \
    --n-gpu-layers "$N_GPU_LAYERS" \
    --ctx-size "$CONTEXT_SIZE" \
    --parallel "$N_PARALLEL" \
    --flash-attn \
    --mlock \
    --no-mmap \
    --batch-size "$BATCH_SIZE" \
    --ubatch-size "$BATCH_SIZE" \
    --api-key "$LLAMA_SERVER_API_KEY" \
    --log-disable \
    >> "${LOG_PATH}/llama-server.log" 2>&1 &

LLAMA_PID=$!
log "llama-server started (PID: ${LLAMA_PID})"

# ── STEP 4: Wait for llama-server health ──────────────────────────────────────
log "Waiting for llama-server to become ready..."
MAX_WAIT=300
ELAPSED=0
until curl -sf "http://127.0.0.1:8000/health" \
    -H "Authorization: Bearer ${LLAMA_SERVER_API_KEY}" > /dev/null 2>&1; do
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        die "llama-server did not become ready within ${MAX_WAIT}s"
    fi
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    log "  Waiting... (${ELAPSED}s elapsed)"
done
log "llama-server is ready!"

# ── STEP 5: Signal handler that llama-server is ready ─────────────────────────
# handler.py polls this file. Once it exists, full inference is enabled.
touch "$MODEL_READY_FILE"
log "Model ready signal written: ${MODEL_READY_FILE}"

# ── STEP 6: Start health shim ─────────────────────────────────────────────────
log "Starting health shim on port 8001..."
python3 /app/health_shim.py >> "${LOG_PATH}/health-shim.log" 2>&1 &
HEALTH_PID=$!
log "Health shim started (PID: ${HEALTH_PID})"

log "ULTRON is fully online."

# Keep container alive — wait for handler (our main process)
wait "$HANDLER_PID"
