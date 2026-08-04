#!/usr/bin/env bash
# =============================================================================
# debug_check.sh — Prüft lokale Voraussetzungen VOR dem Deploy.
# Läuft auf dem PC. Meldet klar was fehlt/falsch ist, bricht nicht sofort ab
# (sammelt alle Probleme und zeigt sie am Ende gesammelt).
# =============================================================================
set -uo pipefail

PASS=0
FAIL=0
WARN=0

ok()   { echo "  ✓ $*"; PASS=$((PASS+1)); }
bad()  { echo "  ✗ $*"; FAIL=$((FAIL+1)); }
warn() { echo "  ⚠ $*"; WARN=$((WARN+1)); }

echo "=== ULTRON Deploy-Vorcheck ==="
echo ""

# --- 1. Tools ---
echo "[1/6] CLI-Tools"
for tool in docker git gh aws python3; do
    if command -v "$tool" &>/dev/null; then
        ok "$tool gefunden ($(command -v "$tool"))"
    else
        bad "$tool nicht installiert"
    fi
done
echo ""

# --- 2. .env ---
echo "[2/6] .env Datei"
ENV_FILE="${ULTRON_ENV_FILE:-/server/ULTRON/.env}"
if [ -f "${ENV_FILE}" ]; then
    ok ".env gefunden: ${ENV_FILE}"
    set -a; source "${ENV_FILE}"; set +a
    for var in S3_ENDPOINT_URL S3_BUCKET_NAME S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY S3_REGION ULTRON_BOT_TOKEN; do
        if [ -n "${!var:-}" ]; then
            ok "${var} gesetzt"
        else
            bad "${var} fehlt oder leer in .env"
        fi
    done
else
    bad ".env nicht gefunden unter ${ENV_FILE}"
fi
echo ""

# --- 3. Model lokal ---
echo "[3/6] Lokales Model"
MODEL_DIR="${ULTRON_MODEL_DIR:-/server/ULTRON/model}"
if [ -d "${MODEL_DIR}" ]; then
    GGUF=$(find "${MODEL_DIR}" -iname "*.gguf" 2>/dev/null | head -n1)
    if [ -n "${GGUF}" ]; then
        SIZE=$(du -sh "${GGUF}" 2>/dev/null | cut -f1)
        ok "GGUF gefunden: $(basename "${GGUF}") (${SIZE})"
        if [[ "${GGUF}" != *"Q4_K_M"* ]]; then
            warn "Datei enthält nicht 'Q4_K_M' im Namen — bitte Quantisierung prüfen"
        fi
    else
        bad "Keine .gguf Datei in ${MODEL_DIR} gefunden"
    fi
else
    bad "Model-Verzeichnis fehlt: ${MODEL_DIR}"
fi
echo ""

# --- 4. Git-Sicherheit ---
echo "[4/6] Git-Sicherheitscheck"
cd "$(dirname "${BASH_SOURCE[0]}")"
if [ -f ".gitignore" ]; then
    ok ".gitignore vorhanden"
    for pattern in ".env" "*.gguf" "model/"; do
        if grep -qF "${pattern}" .gitignore; then
            ok ".gitignore deckt '${pattern}' ab"
        else
            bad ".gitignore FEHLT Eintrag: ${pattern}"
        fi
    done
else
    bad ".gitignore fehlt komplett"
fi

if [ -d ".git" ]; then
    if git ls-files 2>/dev/null | grep -qE '\.env$|\.gguf$'; then
        bad "KRITISCH: .env oder .gguf ist bereits im Git-Tracking!"
    else
        ok "Kein .env/.gguf im Git-Tracking"
    fi
fi
echo ""

# --- 5. Docker Syntax-Check ---
echo "[5/6] Dockerfile Syntax"
if [ -f "Dockerfile" ]; then
    if command -v docker &>/dev/null; then
        if docker build --check . &>/dev/null; then
            ok "Dockerfile Syntax OK"
        else
            warn "Dockerfile-Check nicht eindeutig (docker build --check evtl. nicht unterstützt) — manuell prüfen"
        fi
    fi
else
    bad "Dockerfile fehlt"
fi
echo ""

# --- 6. Python Syntax-Check aller Scripte ---
echo "[6/6] Python-Syntax"
for f in handler.py health_shim.py telegram_bot.py; do
    if [ -f "$f" ]; then
        if python3 -m py_compile "$f" 2>/tmp/pyerr_$$; then
            ok "$f — Syntax OK"
        else
            bad "$f — Syntaxfehler: $(cat /tmp/pyerr_$$)"
        fi
        rm -f /tmp/pyerr_$$
    else
        bad "$f fehlt"
    fi
done
echo ""

echo "=== Ergebnis: ${PASS} OK, ${WARN} Warnungen, ${FAIL} Fehler ==="
if [ "${FAIL}" -gt 0 ]; then
    echo "-> Bitte Fehler beheben bevor du deployst."
    exit 1
else
    echo "-> Alles bereit für Deployment."
    exit 0
fi
