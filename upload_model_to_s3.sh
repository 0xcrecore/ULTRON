#!/usr/bin/env bash
# =============================================================================
# upload_model_to_s3.sh — läuft LOKAL auf dem PC (nicht auf RunPod!)
#
# Verhalten:
#   1. Prüft ERST ob die Datei schon in S3 liegt (aws s3 ls)
#   2. Wenn JA  -> nichts tun, nur Bestätigung ausgeben (kein Re-Upload)
#   3. Wenn NEIN -> lokale GGUF-Datei suchen und hochladen
# =============================================================================
set -euo pipefail

log() { echo "[upload] $(date -u +'%H:%M:%S') $*"; }
fatal() { echo "[upload] FATAL: $*" >&2; exit 1; }

# --- .env laden ---
ENV_FILE="${ULTRON_ENV_FILE:-/server/ULTRON/.env}"
if [ -f "${ENV_FILE}" ]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
    log "✓ .env geladen aus ${ENV_FILE}"
else
    fatal ".env nicht gefunden unter ${ENV_FILE} (setze ULTRON_ENV_FILE um Pfad zu ändern)"
fi

: "${S3_BUCKET_NAME:?S3_BUCKET_NAME fehlt in .env}"
: "${S3_ENDPOINT_URL:?S3_ENDPOINT_URL fehlt in .env}"
: "${S3_REGION:?S3_REGION fehlt in .env}"

LOCAL_MODEL_DIR="${ULTRON_MODEL_DIR:-/server/ULTRON/model}"
MODEL_PATTERN="*Q4_K_M*.gguf"
S3_PREFIX="${S3_MODEL_PREFIX:-models/}"

command -v aws &>/dev/null || fatal "'aws' CLI nicht gefunden. Installiere mit: pip install awscli"

# --- Schritt 1: Lokale GGUF-Datei finden (brauchen wir für Dateinamen-Vergleich) ---
if [ ! -d "${LOCAL_MODEL_DIR}" ]; then
    fatal "Model-Verzeichnis nicht gefunden: ${LOCAL_MODEL_DIR}"
fi

GGUF_FILE=$(find "${LOCAL_MODEL_DIR}" -maxdepth 3 -iname "${MODEL_PATTERN}" | sort | head -n1)
if [ -z "${GGUF_FILE}" ]; then
    log "Kein Q4_K_M-Match, suche alle .gguf..."
    GGUF_FILE=$(find "${LOCAL_MODEL_DIR}" -maxdepth 3 -iname "*.gguf" | sort | head -n1)
fi
[ -n "${GGUF_FILE}" ] || fatal "Keine .gguf Datei gefunden in ${LOCAL_MODEL_DIR}"

GGUF_BASENAME=$(basename "${GGUF_FILE}")
S3_KEY="${S3_PREFIX}${GGUF_BASENAME}"
LOCAL_SIZE_BYTES=$(stat -c%s "${GGUF_FILE}" 2>/dev/null || stat -f%z "${GGUF_FILE}")

log "Lokale Datei: ${GGUF_BASENAME} ($(du -sh "${GGUF_FILE}" | cut -f1))"
log "S3-Ziel:      s3://${S3_BUCKET_NAME}/${S3_KEY}"

# --- Schritt 2: Prüfen ob Datei bereits in S3 existiert ---
log "Prüfe ob Datei bereits in S3 liegt..."

REMOTE_INFO=$(aws s3api head-object \
    --bucket "${S3_BUCKET_NAME}" \
    --key "${S3_KEY}" \
    --endpoint-url "${S3_ENDPOINT_URL}" \
    --region "${S3_REGION}" \
    2>/dev/null || true)

if [ -n "${REMOTE_INFO}" ]; then
    REMOTE_SIZE=$(echo "${REMOTE_INFO}" | grep -o '"ContentLength": [0-9]*' | grep -o '[0-9]*' || echo "0")
    log "✓ Datei existiert bereits in S3 (${REMOTE_SIZE} bytes remote vs. ${LOCAL_SIZE_BYTES} bytes lokal)."

    if [ "${REMOTE_SIZE}" = "${LOCAL_SIZE_BYTES}" ]; then
        log "✓ Größen stimmen überein — KEIN Upload nötig. Nichts zu tun."
        echo ""
        echo "MODEL_FILENAME=${GGUF_BASENAME}"
        exit 0
    else
        log "⚠ Größen weichen ab! Remote=${REMOTE_SIZE} Lokal=${LOCAL_SIZE_BYTES}"
        log "  Lade erneut hoch, um sicherzustellen dass die Datei vollständig/korrekt ist..."
    fi
else
    log "Datei noch nicht in S3 — starte Upload."
fi

# --- Schritt 3: Upload ---
log "Starte S3-Upload (das kann bei ~20GB einige Minuten dauern)..."

aws s3 cp \
    "${GGUF_FILE}" \
    "s3://${S3_BUCKET_NAME}/${S3_KEY}" \
    --endpoint-url "${S3_ENDPOINT_URL}" \
    --region "${S3_REGION}"

log "✓ Upload abgeschlossen."

# --- Schritt 4: Verifikation ---
log "Verifiziere Upload..."
aws s3 ls \
    "s3://${S3_BUCKET_NAME}/${S3_PREFIX}" \
    --endpoint-url "${S3_ENDPOINT_URL}" \
    --region "${S3_REGION}" \
    --human-readable

echo ""
log "✓ Fertig. Setze in RunPod Secrets/Env:"
echo "  MODEL_FILENAME=${GGUF_BASENAME}"
echo "  S3_MODEL_PREFIX=${S3_PREFIX}"
