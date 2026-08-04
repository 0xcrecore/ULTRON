#!/usr/bin/env bash
# =============================================================================
# git_setup.sh — All-in-One: Git init, Sicherheits-Check, PRIVATE GitHub Repo
#                erstellen und pushen.
#
# Voraussetzung: GitHub CLI (`gh`) installiert und eingeloggt (`gh auth login`)
#
# WICHTIG: Erstellt IMMER ein PRIVATES Repo (--private). Das Model (.gguf)
# und .env werden NIE eingecheckt (siehe .gitignore).
# =============================================================================
set -euo pipefail

log() { echo "[git_setup] $*"; }
fatal() { echo "[git_setup] FATAL: $*" >&2; exit 1; }

REPO_NAME="${1:-ultron-runpod-agent}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "${REPO_DIR}"

# --- Sicherheits-Check: .env darf NICHT vorhanden sein im Tracking ---
if [ -f ".env" ]; then
    log "⚠ .env gefunden im Verzeichnis — wird durch .gitignore ausgeschlossen."
fi

command -v git &>/dev/null || fatal "git nicht installiert."
command -v gh &>/dev/null || fatal "GitHub CLI 'gh' nicht installiert. Siehe: https://cli.github.com"

gh auth status &>/dev/null || fatal "Nicht bei GitHub eingeloggt. Führe aus: gh auth login"

# --- .gitignore Pflichtcheck ---
for pattern in ".env" "*.gguf" "model/"; do
    grep -qF "${pattern}" .gitignore 2>/dev/null || fatal ".gitignore fehlt Eintrag: ${pattern} — Abbruch aus Sicherheitsgründen."
done
log "✓ .gitignore enthält alle Pflicht-Ausschlüsse (.env, *.gguf, model/)"

# --- Git init (falls noch nicht geschehen) ---
if [ ! -d ".git" ]; then
    git init -b main
    log "✓ Git-Repo initialisiert"
else
    log "Git-Repo existiert bereits"
fi

# --- Prüfen ob .env versehentlich schon getrackt ist (z.B. vor .gitignore hinzugefügt) ---
if git ls-files --error-unmatch .env &>/dev/null 2>&1; then
    fatal ".env ist bereits im Git-Index! Führe 'git rm --cached .env' aus bevor du fortfährst."
fi

git add -A

# Doppelcheck: liegt .env im Staging?
if git diff --cached --name-only | grep -qE '^\.env$|\.gguf$'; then
    fatal "SICHERHEITS-ABBRUCH: .env oder .gguf-Datei im Staging-Bereich gefunden!"
fi

log "✓ Staged Dateien (Kontrolle):"
git diff --cached --name-only | sed 's/^/    /'

git commit -m "ULTRON: RunPod Serverless Agent — initial commit" || log "Nichts zu committen (bereits aktuell)"

# --- Privates Repo auf GitHub erstellen (falls noch nicht existiert) ---
if gh repo view "${REPO_NAME}" &>/dev/null; then
    log "Repo '${REPO_NAME}' existiert bereits auf GitHub."
    REMOTE_URL=$(gh repo view "${REPO_NAME}" --json url -q .url)
    git remote add origin "${REMOTE_URL}.git" 2>/dev/null || git remote set-url origin "${REMOTE_URL}.git"
else
    log "Erstelle PRIVATES GitHub-Repo '${REPO_NAME}'..."
    gh repo create "${REPO_NAME}" --private --source=. --remote=origin --description "ULTRON — RunPod Serverless llama.cpp Agent (privat, enthält keine Secrets/Model-Weights)"
fi

git push -u origin main

REPO_URL=$(gh repo view "${REPO_NAME}" --json url -q .url)
log "✓ Fertig! Privates Repo: ${REPO_URL}"
log ""
log "Nächste Schritte:"
log "  1. Auf RunPod: Endpoint erstellen, Container Image auf dieses Repo verweisen (Dockerfile-Build)"
log "     ODER lokal 'docker build' + Push zu Docker Hub / RunPod Registry"
log "  2. Secrets in RunPod eintragen (siehe README.md, Abschnitt 'RunPod Secrets')"
log "  3. Model-Upload: bash upload_model_to_s3.sh"
