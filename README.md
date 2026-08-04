# ULTRON — RunPod Serverless llama.cpp Agent

Serverless, GPU-kosten-optimierter Deployment-Stack für einen OpenAI-kompatiblen
llama.cpp-Endpoint auf RunPod. Skaliert auf **0 Worker** wenn nichts los ist —
GPU-Kosten fallen nur während aktiver Requests an.

> ⚠️ **Dieses Repo enthält KEINE Secrets und KEINE Model-Gewichte.**
> `.env` und `model/*.gguf` sind über `.gitignore` ausgeschlossen und müssen
> lokal bzw. in RunPod separat bereitgestellt werden. Halte dieses Repo
> trotzdem **privat** — es beschreibt exakt, wie dein Setup funktioniert.

---

## Architektur

```
┌─────────────┐     Telegram      ┌──────────────┐    RunPod API    ┌────────────────────┐
│   Telegram   │ ───────────────► │  telegram_bot │ ───────────────► │  RunPod Serverless   │
│   (du)       │ ◄─────────────── │  .py (auf PC) │ ◄─────────────── │  Endpoint (0-1 GPU)  │
└─────────────┘                   └──────────────┘                  └─────────┬──────────┘
                                                                                │ Cold-Start
                                                                                ▼
                                                          ┌─────────────────────────────────┐
                                                          │ entrypoint.sh                    │
                                                          │  1. Model im Volume-Cache?        │
                                                          │     nein -> S3 Download            │
                                                          │  2. llama-server starten (:8000)  │
                                                          │  3. health_shim.py starten (:8001)│
                                                          │  4. handler.py (RunPod SDK)       │
                                                          └─────────────────────────────────┘
                                                          Nach Idle-Timeout: Worker -> 0
```

**Kostenprinzip:** RunPod berechnet nur laufende Worker-Zeit. Mit `Min Workers=0`
und `Idle Timeout=60s` läuft die GPU ausschließlich während eines aktiven
Requests + der kurzen Nachlaufzeit danach. Der Telegram-Bot läuft dauerhaft
auf deinem PC (keine GPU, vernachlässigbare Kosten) und weckt RunPod bei Bedarf.

---

## Datei-Übersicht

| Datei | Zweck |
|---|---|
| `Dockerfile` | Baut llama.cpp (CUDA) + Python-Runtime für den Serverless-Worker |
| `entrypoint.sh` | Container-Start: Model-Cache-Check → S3-Download falls nötig → llama-server + Handler starten |
| `handler.py` | RunPod Serverless Handler — nimmt Jobs entgegen, leitet an lokalen llama-server weiter |
| `health_shim.py` | `/ping` auf Port 8001 → übersetzt zu llama-server `/health` |
| `requirements.txt` | Python-Deps für den Container |
| `upload_model_to_s3.sh` | **Lokal** ausführen: prüft ob Model schon in S3 liegt, lädt nur hoch wenn nötig |
| `telegram_bot.py` | **Lokal** dauerhaft laufen lassen: pollt Telegram, triggert RunPod on-demand |
| `telegram_bot_requirements.txt` | Deps für den Telegram-Bot |
| `git_setup.sh` | Erstellt privates GitHub-Repo, pusht (mit Sicherheitschecks gegen versehentliches Secret-Leak) |
| `debug_check.sh` | Prüft alle Voraussetzungen lokal (Tools, .env, Model, Git-Sicherheit, Syntax) |
| `deploy_all.sh` | All-in-One: `debug_check` → `upload_model_to_s3` → `git_setup` → RunPod-Anleitung |
| `env.example` | Vorlage für `.env` — ohne echte Werte |
| `.gitignore` | Schließt `.env`, `*.gguf`, `model/`, `__pycache__/` aus |
| `JARVIS_PROMPT.md` | Agent-Anleitung für den Deploy-Workflow |

---

## Setup

### 1. Lokale Voraussetzungen

```bash
sudo apt install docker.io awscli python3-pip
pip install runpod boto3 httpx  # falls lokal getestet werden soll
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/... # gh CLI
gh auth login
```

### 2. `.env` anlegen

```bash
cp env.example .env
nano .env   # echte Werte eintragen
```

**Nie committen.** `.gitignore` blockt das, aber `debug_check.sh` prüft es zusätzlich.

### 3. Alles auf einmal deployen

```bash
chmod +x *.sh
bash deploy_all.sh ultron-runpod-agent
```

Das führt aus: Vorcheck → Model-Upload (S3, mit Skip-if-exists) → privates
GitHub-Repo erstellen & pushen → gibt dir die exakte RunPod-Dashboard-Anleitung aus.

Oder einzeln:

```bash
bash debug_check.sh          # nur prüfen
bash upload_model_to_s3.sh   # nur Model hochladen
bash git_setup.sh MEIN_REPO_NAME
```

---

## RunPod Secrets — sicher eintragen

**Die `.env`-Datei wird NIEMALS hochgeladen, committed oder ins Image gebacken.**
So bekommst du die Werte sicher nach RunPod:

1. Gehe zu **RunPod Console → Settings → Secrets**
   (oder direkt im Endpoint unter "Environment Variables")
2. Für jede Zeile in deiner lokalen `.env`: Key + Value einzeln eintragen.
   RunPod verschlüsselt Secrets separat von normalen Env-Vars — wo die Option
   "Secret" vs. "Environment Variable" angeboten wird, nimm **Secret** für:
   - `S3_ACCESS_KEY_ID`
   - `S3_SECRET_ACCESS_KEY`
   - `ULTRON_BOT_TOKEN`
   - `LLAMA_SERVER_API_KEY`
3. Normale (nicht-geheime) Konfigurationswerte wie `MODEL_FILENAME`,
   `CONTEXT_SIZE`, `S3_REGION` können als reguläre Environment Variables rein.
4. Beim Endpoint-Deploy referenzierst du die Secrets per Name — RunPod injiziert
   sie zur Laufzeit in den Container. Sie landen nie im Repo, nie im Image-Layer.

**Nie tun:** `.env` per `COPY .env` ins Dockerfile aufnehmen, `.env` in ein
öffentliches Repo pushen, Secrets als Klartext in `runpod.toml` o.ä. committen.

---

## RunPod Endpoint Konfiguration

| Parameter | Wert |
|---|---|
| GPU | RTX 4090 (24GB) |
| Min Workers | **0** (Scale-to-Zero) |
| Max Workers | 1 (oder mehr je nach Last) |
| Idle Timeout | 60s |
| Container Disk | 10 GB |
| Network Volume | ≥ 30 GB, **gleiche Region wie S3-Bucket** (`eu-ro-1`) |
| Ports | 8000 (llama-server), 8001 (health) |

Bei `Source: GitHub Repo` baut RunPod das `Dockerfile` bei jedem Push automatisch
neu — kein manuelles `docker build`/`push` nötig.

---

## Testen

```bash
ENDPOINT_URL="https://api.runpod.ai/v2/DEIN_ENDPOINT_ID"

# Sync-Request (wartet auf Antwort, weckt Worker falls idle)
curl "${ENDPOINT_URL}/runsync" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "payload": {
        "model": "ultron",
        "messages": [{"role": "user", "content": "Sag: ULTRON ist online."}],
        "max_tokens": 50
      }
    }
  }'
```

Telegram-Bot lokal starten:

```bash
pip install -r telegram_bot_requirements.txt
set -a; source .env; set +a
python3 telegram_bot.py
```

---

## Troubleshooting

| Problem | Lösung |
|---|---|
| S3-Download schlägt fehl | `S3_ENDPOINT_URL`, Credentials, freien Speicher im Network Volume prüfen |
| Cold-Start sehr langsam | S3-Region und RunPod-Region müssen identisch sein (`eu-ro-1`) |
| `/ping` antwortet nicht | Port 8001 in RunPod "Expose HTTP Ports" eingetragen? |
| OOM / CUDA out of memory | `CONTEXT_SIZE` auf 4096 reduzieren, `N_PARALLEL` auf 2 |
| Worker skaliert nicht auf 0 | `Min Workers=0` und `Idle Timeout` im Endpoint-Dashboard prüfen |
| `git_setup.sh` bricht ab | Meist Sicherheitscheck — `.env`/`.gguf` versehentlich getrackt, siehe Fehlermeldung |

---

## Sicherheitshinweis

Dieses Repo ist als **privat** vorgesehen (`git_setup.sh` erzwingt `--private`).
Es dokumentiert Infrastruktur/Deployment-Tooling. Es enthält keine Model-Gewichte
und keine Secrets. Behandle den Telegram-Bot-Token und die S3-Credentials mit
der gleichen Sorgfalt wie ein Passwort — bei Verdacht auf Leak: in RunPod/Telegram
sofort rotieren (`ULTRON_SHIELD_BOT` → BotFather → `/revoke`).
