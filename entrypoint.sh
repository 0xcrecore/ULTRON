#!/usr/bin/env bash
# =============================================================================
# ULTRON entrypoint.sh
# Läuft INSIDE des RunPod Serverless Containers bei jedem Cold-Start.
#
# Logik:
#   1. Prüfe ob Model bereits im Network Volume Cache liegt (/runpod-volume/model)
#   2. Wenn JA  -> nichts tun, direkt starten (schneller Warm/Cold-Start)
#   3. Wenn NEIN -> aus S3 laden, dann im Volume cachen für nächstes Mal
#   4. llama-server starten (OpenAI-kompatible API auf Port 8000)
#   5. Health-Shim starten (Port 8001 -> /ping)
#   6. Python RunPod Handler starten (nimmt Requests entgegen)
# =============================================================================
set -euo pipefail

log() { echo "[ULTRON] $(date -u +'%H:%M:%S') $*"; }

log "Initializing ULTRON AI Backend"

# --- Pflicht-Variablen prüfen ---
: "${MODEL_FILENAME:?MODEL_FILENAME env var fehlt}"
: "${S3_BUCKET_NAME:?S3_BUCKET_NAME env var fehlt}"
: "${S3_ENDPOINT_URL:?S3_ENDPOINT_URL env var fehlt}"
: "${S3_REGION:?S3_REGION env var fehlt}"
: "${S3_ACCESS_KEY_ID:?S3_ACCESS_KEY_ID env var fehlt}"
: "${S3_SECRET_ACCESS_KEY:?S3_SECRET_ACCESS_KEY env var fehlt}"

S3_MODEL_PREFIX="${S3_MODEL_PREFIX:-models/}"
VOLUME_DIR="/runpod-volume/model"
LOCAL_MODEL_PATH="${VOLUME_DIR}/${MODEL_FILENAME}"
CONTEXT_SIZE="${CONTEXT_SIZE:-8192}"
N_PARALLEL="${N_PARALLEL:-4}"
PORT="${PORT:-8000}"
PORT_HEALTH="${PORT_HEALTH:-8001}"

mkdir -p "${VOLUME_DIR}"
export AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY}"

# --- Schritt 1: Cache-Check ---
if [ -f "${LOCAL_MODEL_PATH}" ]; then
    SIZE=$(du -sh "${LOCAL_MODEL_PATH}" | cut -f1)
    log "Model im Volume-Cache gefunden (${SIZE}) — kein Download nötig."
else
    log "Model nicht im Cache. Lade von S3..."
    log "  Quelle: s3://${S3_BUCKET_NAME}/${S3_MODEL_PREFIX}${MODEL_FILENAME}"
    log "  Ziel:   ${LOCAL_MODEL_PATH}"

    TMP_PATH="${LOCAL_MODEL_PATH}.part"

    if command -v aws &>/dev/null; then
        aws s3 cp \
            "s3://${S3_BUCKET_NAME}/${S3_MODEL_PREFIX}${MODEL_FILENAME}" \
            "${TMP_PATH}" \
            --endpoint-url "${S3_ENDPOINT_URL}" \
            --region "${S3_REGION}" \
            --no-progress
    else
        # Fallback: Python boto3, falls aws-cli im Image fehlt
        python3 - <<PYEOF
import boto3, os
s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT_URL"],
    region_name=os.environ["S3_REGION"],
    aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
)
s3.download_file(os.environ["S3_BUCKET_NAME"], "${S3_MODEL_PREFIX}${MODEL_FILENAME}", "${TMP_PATH}")
PYEOF
    fi

    mv "${TMP_PATH}" "${LOCAL_MODEL_PATH}"
    log "✓ Download abgeschlossen ($(du -sh "${LOCAL_MODEL_PATH}" | cut -f1))"
fi

# --- Schritt 2: Health-Shim starten (Hintergrund) ---
log "Starte Health-Shim auf Port ${PORT_HEALTH}"
PORT_HEALTH="${PORT_HEALTH}" LLAMA_PORT="${PORT}" python3 health_shim.py &
HEALTH_PID=$!

# --- Schritt 3: llama-server starten (Hintergrund) ---
log "Starte llama-server auf Port ${PORT} (ctx=${CONTEXT_SIZE}, parallel=${N_PARALLEL})"

LLAMA_ARGS=(
    --model "${LOCAL_MODEL_PATH}"
    --host 0.0.0.0
    --port "${PORT}"
    --ctx-size "${CONTEXT_SIZE}"
    --parallel "${N_PARALLEL}"
    --n-gpu-layers 999
    --flash-attn
)

if [ -n "${LLAMA_SERVER_API_KEY:-}" ]; then
    LLAMA_ARGS+=(--api-key "${LLAMA_SERVER_API_KEY}")
fi

llama-server "${LLAMA_ARGS[@]}" &
LLAMA_PID=$!

# --- Schritt 4: Warten bis llama-server bereit ist ---
log "Warte auf llama-server..."
for i in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
        log "✓ llama-server bereit"
        break
    fi
    sleep 2
    if [ "$i" -eq 60 ]; then
        log "FATAL: llama-server nach 120s nicht bereit"
        exit 1
    fi
done

# --- Schritt 5: RunPod Serverless Handler starten (Vordergrund) ---
log "Starte RunPod Handler (nimmt Requests entgegen)"
python3 -u handler.py

# Falls Handler beendet: aufräumen
kill "${LLAMA_PID}" "${HEALTH_PID}" 2>/dev/null || true
