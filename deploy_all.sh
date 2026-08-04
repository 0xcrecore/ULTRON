#!/usr/bin/env bash
# =============================================================================
# deploy_all.sh — ALL-IN-ONE Orchestrator
#
# Führt aus, in dieser Reihenfolge:
#   1. debug_check.sh       (Voraussetzungen prüfen)
#   2. upload_model_to_s3.sh (Model -> S3, überspringt falls schon vorhanden)
#   3. git_setup.sh          (privates Repo erstellen/pushen, OHNE Model/.env)
#   4. Gibt exakte Klick-Anleitung für RunPod-Endpoint-Erstellung aus
#      (RunPod baut das Image direkt aus dem GitHub-Repo — kein manuelles
#       docker build/push nötig, wenn du das im Dashboard so einrichtest)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

REPO_NAME="${1:-ultron-runpod-agent}"

echo "############################################################"
echo "# ULTRON — ALL-IN-ONE DEPLOY"
echo "############################################################"
echo ""

echo ">>> [1/3] Vorcheck..."
bash debug_check.sh || { echo "Vorcheck fehlgeschlagen. Behebe die Fehler und versuch's erneut."; exit 1; }
echo ""

echo ">>> [2/3] Model-Upload (überspringt falls bereits in S3)..."
bash upload_model_to_s3.sh
echo ""

echo ">>> [3/3] GitHub Repo (privat) erstellen/pushen..."
bash git_setup.sh "${REPO_NAME}"
echo ""

echo "############################################################"
echo "# NÄCHSTER SCHRITT: RunPod Endpoint erstellen"
echo "############################################################"
cat <<'EOF'

Gehe zu https://www.runpod.io/console/serverless -> "New Endpoint"

1. Source: "GitHub Repo" auswählen, dein privates Repo verbinden
   (RunPod baut das Dockerfile automatisch bei jedem Push)

2. GPU: RTX 4090 (24GB)

3. Worker Config:
     Min Workers:    0     <- WICHTIG für Scale-to-Zero
     Max Workers:    1     (oder höher je nach Bedarf)
     Idle Timeout:   60    Sekunden

4. Container Disk: 10 GB
   Network Volume:  min. 30 GB (Model-Cache) — im selben Datacenter wie S3!

5. Environment Variables (siehe README.md "RunPod Secrets" für Details):
   Trage JEDEN Wert aus deiner lokalen .env einzeln im RunPod-Dashboard
   unter "Environment Variables" ein — als "Secret" markieren wo möglich.
   NIEMALS die .env-Datei selbst hochladen.

6. Ports: 8000, 8001 exposen

7. Deploy klicken. Erster Cold-Start lädt Model aus S3 (~5-10 Min bei 20GB).
   Danach liegt es im Network Volume Cache -> nächste Cold-Starts sind schnell.

EOF
