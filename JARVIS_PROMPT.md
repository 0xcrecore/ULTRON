# JARVIS – MISSION: ULTRON DEPLOYEN
## Vollständiger Agent-Prompt (v3 — RunPod-only Build, PC nur Dateiursprung)

---

## ⚠️ OBERSTES PRINZIP

**Der komplette Build- und Betriebsprozess läuft AUF RUNPOD. Der PC (`/server/ULTRON/`) ist
NUR Dateiursprung — dort liegen die Scripts, von dort werden sie zu RunPod übertragen (S3-Upload
oder direkter Git/Registry-Push aus dem RunPod-Pod heraus). Auf dem PC wird NICHT gebaut, NICHT
kompiliert, NICHT das Model geladen.**

Steuerung erfolgt über **SeekerClaw** (auf dem Seeker), wo Jarvis läuft. Jarvis nutzt dort die
RunPod-Account-API (`RUNPOD_ACC_API`) als Env-Var, um Pod/Endpoint-Aktionen auszulösen. Der
Telegram-Bot ist der einzige Kanal, über den Prompts an ULTRON geschickt werden — auch der Bot
selbst läuft NICHT dauerhaft mit eigener Rechenlast auf dem PC, sondern ist ein reiner Relay.

**ULTRON darf NIEMALS GPU-Kosten verursachen, wenn er nicht aktiv eine Anfrage bearbeitet.**

- **Min Workers = 0. Immer.** Keine Ausnahme.
- **Idle Timeout so knapp wie sinnvoll** (Default: 60s).
- **Kein Polling-Loop auf der GPU.** Der Telegram-Bot (Relay) läuft NICHT auf RunPod.
- Ihr bereits gebuchter Pod (50 GB Storage) wird für den Build-Vorgang selbst genutzt — nicht
  dauerhaft laufen lassen. Nach Build + Push + Verifikation: Pod stoppen bzw. auf Serverless-
  Endpoint mit Min Workers = 0 übergeben.
- Wenn du (JARVIS) an irgendeinem Punkt merkst, dass eine Konfiguration dazu führen könnte, dass
  die GPU auch nur eine Minute länger läuft als nötig, STOPPE und frage nach, bevor du fortfährst.

---

Du bist JARVIS. Deine Mission: den RunPod-Agenten **ULTRON** vollständig deployen und in Betrieb
nehmen — Build, Push und Verifikation **ausschließlich auf RunPod**, gesteuert über SeekerClaw
(RunPod-Account-API). ULTRON ist ein llama.cpp-basierter OpenAI-kompatibler API-Endpunkt auf
RunPod Serverless, der ein bereits hochgeladenes GGUF-Model (Qwen2.5-Coder-32B, Q4_K_M) ausführt,
und per Telegram (Bot-ID `8824386770`) für den User (@Xcrecore, ID `7525618433`) erreichbar ist.

**Workspace:** `RUNPODSTORAGE`
**Dateien Ursprung PC:** `/server/ULTRON/` — Quelle der Scripts, KEIN Ausführungsort
**Secrets/Env:** `/server/ULTRON/.env` — wird 1:1 in die RunPod-Umgebung übernommen
**Build-Ort:** RunPod Pod (bereits gebucht, 50 GB Storage) — dort werden Dockerfile,
entrypoint.sh, health_shim.py, s3_download.py etc. aus S3/Transfer empfangen und gebaut
**Steuerungs-Ort:** SeekerClaw (Seeker), Jarvis nutzt `RUNPOD_ACC_API` env var dort
**RunPod MCP:** `npx @runpod/mcp-server@latest add` (bereits eingerichtet)

---

## Secrets — `/server/ULTRON/.env` (PC, Quelle — wird zu RunPod übertragen, nicht dort ausgeführt)

```
S3_ENDPOINT_URL=https://s3api-eu-ro-1.runpod.io
S3_BUCKET_NAME=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
S3_REGION=eu-ro-1
RUNPOD_API_KEY=

DOCKERHUB_NAME=
DOCKERHUB_KEY=

ULTRON_BOT_TOKEN=
TELEGRAM_BOT_ID=8824386770
TELEGRAM_USER=7525618433

MODEL_FILENAME=

PORT=8000
PORT_HEALTH=8001
CONTEXT_SIZE=16384
N_PARALLEL=2

LLAMA_SERVER_API_KEY=
```

Diese `.env` bleibt die Quelle der Wahrheit. Für den Build auf RunPod werden die Werte als
Environment Variables im Pod bzw. im Serverless-Endpoint gesetzt (Schritt 1.1) — **niemals** wird
die `.env`-Datei selbst gelöscht, überschrieben oder deren Inhalt verworfen.

---

## PHASE 0: DATEIEN VOM PC ZU RUNPOD ÜBERTRAGEN (kein Build hier!)

Ziel: Scripts aus `/server/ULTRON/` (Dockerfile, entrypoint.sh, health_shim.py, s3_download.py,
requirements.txt, bot/telegram_bot.py) liegen im RunPod-Pod-Filesystem — Übertragung z. B. via
`scp`/RunPod-Web-Terminal-Upload, Git-Push in ein Repo das der Pod pullt, oder S3-Upload der
Scripts (analog zum Model) und Download im Pod. Die Wahl der Transfermethode ist frei, solange
**auf dem PC selbst kein `docker build`, kein Kompilieren und kein Laden des Models** stattfindet.

### Schritt 0.1 – Modell-Status prüfen (bereits erledigt)
```bash
source /server/ULTRON/.env
aws s3 ls \
  --region "${S3_REGION}" \
  --endpoint-url "${S3_ENDPOINT_URL}" \
  "s3://${S3_BUCKET_NAME}/models/" \
  --human-readable
```
Erwartete Ausgabe: die `.gguf`-Datei (~19.9 GB), Upload bereits abgeschlossen.

### Schritt 0.2 – Scripts zu RunPod transferieren
Vom bereits gebuchten Pod aus (SSH/Web-Terminal, gesteuert via RunPod-Account-API von
SeekerClaw aus), die Dateien aus `/server/ULTRON/` in den Pod holen — z. B.:
```bash
# Auf dem Pod ausgeführt (nicht auf dem PC):
mkdir -p /workspace/ULTRON
# Transfer via S3 (Scripts vorher als Zip nach S3 gelegt) oder Git-Pull
aws s3 cp s3://${S3_BUCKET_NAME}/build/ultron-scripts.zip /workspace/ULTRON/ \
  --endpoint-url "${S3_ENDPOINT_URL}" --region "${S3_REGION}"
cd /workspace/ULTRON && unzip ultron-scripts.zip
```

---

## PHASE 1: DOCKER IMAGE BAUEN & PUSHEN — **AUF RUNPOD, NICHT AUF DEM PC**

### Schritt 1.1 – Docker Image bauen im RunPod-Pod
```bash
cd /workspace/ULTRON
docker build -t ultron-llama:latest .
```
> Läuft im gebuchten Pod, nicht auf dem PC. Build dauert 10–20 Min (llama.cpp mit CUDA).
> Das Model wird **nicht** ins Image gebacken — es kommt zur Laufzeit aus S3/Volume.

### Schritt 1.2 – Image pushen (Docker Hub, Credentials aus `.env`)
```bash
echo "${DOCKERHUB_KEY}" | docker login -u "${DOCKERHUB_NAME}" --password-stdin
docker tag ultron-llama:latest ${DOCKERHUB_NAME}/ultron-llama:latest
docker push ${DOCKERHUB_NAME}/ultron-llama:latest
```
Merke dir die Image-URL für Phase 2.

---

## PHASE 2: RUNPOD SERVERLESS ENDPOINT ERSTELLEN

Steuerung über RunPod-MCP-Tool bzw. `RUNPOD_ACC_API` (von SeekerClaw/Jarvis aus aufgerufen).
**Jeder Parameter ist auf minimale GPU-Laufzeit optimiert.**

### Schritt 2.1 – Serverless Endpoint anlegen

| Parameter | Wert | Warum |
|-----------|------|-------|
| **Name** | `ULTRON` | |
| **GPU** | A6000 (48GB) | |
| **Container Image** | `${DOCKERHUB_NAME}/ultron-llama:latest` (aus Phase 1) | |
| **Container Disk** | ausreichend für Image + Puffer | |
| **Network Volume** | 50 GB (bereits gebucht) | Model-Cache |
| **HTTP Ports** | `8000,8001` | |
| **Min Workers** | **`0`** | **PFLICHT — Scale-to-Zero, keine Ausnahme** |
| **Max Workers** | `1` | Nur bei echtem Parallelbedarf erhöhen |
| **Idle Timeout** | **`60` Sekunden** | Kurz halten |
| **Flashboot** (falls verfügbar) | aktivieren | Schnellerer Cold-Start |

### Schritt 2.2 – Environment Variables setzen (Werte aus `/server/ULTRON/.env`)

```
S3_ENDPOINT_URL=<aus .env>
S3_BUCKET_NAME=<aus .env>
S3_ACCESS_KEY_ID=<aus .env>
S3_SECRET_ACCESS_KEY=<aus .env>
S3_REGION=<aus .env>

MODEL_FILENAME=<aus .env>
S3_MODEL_PREFIX=models/
VOLUME_MODEL_DIR=/runpod-volume/models

PORT=8000
PORT_HEALTH=8001
CONTEXT_SIZE=16384
N_PARALLEL=2

LLAMA_SERVER_API_KEY=<aus .env — dringend empfohlen, abliterated Model>
```

Nach Erstellung: `RUNPOD_ENDPOINT_ID` des neuen Endpoints notieren — wird in Phase 3 für den
Telegram-Bot gebraucht (Übergabe an SeekerClaw-Env, nicht zwingend zurück in die PC-`.env`).

### Schritt 2.3 – Expose HTTP Ports
- Port `8000` → llama-server (OpenAI API)
- Port `8001` → Health-Shim (`/ping`)

### Schritt 2.4 – Build-Pod stoppen
Sobald Image gepusht und Endpoint läuft: den ursprünglich gebuchten Pod (aus Phase 0/1) stoppen
oder terminieren — er wird für Betrieb nicht mehr gebraucht, nur der Serverless-Endpoint läuft
(mit Min Workers = 0).

---

## PHASE 3: DEPLOYMENT TESTEN

### Schritt 3.1 – Ersten Cold-Start auslösen
```bash
curl "https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/openai/v1/models" \
  -H "Authorization: Bearer ${RUNPOD_ACC_API}"
```

### Schritt 3.2 – Logs beobachten (RunPod MCP)
Erwartete Sequenz:
```
[ULTRON] Initializing ULTRON AI Backend
[ULTRON] Model im Volume-Cache gefunden       ← ab dem 2. Start
  ODER
[ULTRON] Lade von S3...                       ← 1. Cold-Start
[ULTRON] ✓ Download abgeschlossen
[ULTRON] Health-Shim gestartet
[ULTRON] Starte llama-server auf Port 8000
```

### Schritt 3.3 – Chat-Test
```bash
curl "https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/openai/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${RUNPOD_ACC_API}" \
  -d '{
    "model": "Qwen2.5-Coder-32B-abliterated",
    "messages": [{"role": "user", "content": "Sag: ULTRON ist online."}],
    "max_tokens": 50
  }'
```

### Schritt 3.4 – Scale-to-Zero verifizieren (WICHTIG, nicht überspringen)
Nach dem Test 2–3 Minuten warten (länger als Idle Timeout), dann per RunPod-MCP/API prüfen:
**Worker-Anzahl muss auf 0 zurückgegangen sein.** Falls nicht, Idle-Timeout- und
Min-Workers-Einstellung erneut prüfen, bevor mit Phase 4 fortgefahren wird.

---

## PHASE 4: TELEGRAM-BOT — REINER RELAY, GESTEUERT ÜBER SEEKERCLAW/JARVIS

Der Telegram-Bot ist der einzige Kanal, über den Prompts an ULTRON geschickt werden. Er läuft
**nicht als eigenständiger Dauerprozess auf dem PC** — die Steuerung/Verwaltung erfolgt über
Jarvis in SeekerClaw, wo `RUNPOD_ACC_API` als Env-Var hinterlegt ist. SeekerClaw ruft bei
eingehenden Telegram-Nachrichten den RunPod-Endpoint auf, leitet die Antwort zurück — es entsteht
kein Polling-Loop und keine dauerhafte GPU-Belastung.

- Bot-Token: `ULTRON_BOT_TOKEN` (aus `.env`)
- Bot-ID: `8824386770`
- Erlaubter User: `7525618433` (@Xcrecore) — Nachrichten anderer User-IDs werden ignoriert,
  kein RunPod-Request wird ausgelöst.
- Cold-Start bei 32B-Modell: 1–2 Min — Timeout im Relay entsprechend großzügig setzen (≥300s).

---

## PHASE 5: VERIFIKATION & ABSCHLUSS

- [ ] Model in S3 vorhanden und verifiziert (Phase 0.1 — bereits erledigt)
- [ ] Scripts vom PC zu RunPod transferiert, PC selbst hat NICHT gebaut (Phase 0.2)
- [ ] Docker Image im RunPod-Pod gebaut und zu Docker Hub gepusht (Phase 1)
- [ ] RunPod Endpoint erstellt: **Min Workers = 0**, Idle Timeout = 60s, 50 GB Volume (Phase 2)
- [ ] Alle Environment Variables im Endpoint gesetzt (Phase 2.2)
- [ ] Build-Pod nach Fertigstellung gestoppt (Phase 2.4)
- [ ] Erster Cold-Start erfolgreich — Model aus S3 geladen (Phase 3)
- [ ] `/ping` auf Port 8001 antwortet mit 200 (Phase 3)
- [ ] Chat-Completion funktioniert (Phase 3)
- [ ] **Worker skaliert nach Idle-Timeout nachweislich auf 0 zurück** (Phase 3.4 — kritisch)
- [ ] Telegram-Relay über SeekerClaw/Jarvis funktioniert, antwortet nur @Xcrecore (Phase 4)
- [ ] End-to-End-Test: Telegram-Nachricht → SeekerClaw → RunPod Cold-Start → Antwort → Worker 0

---

## TROUBLESHOOTING

| Problem | Lösung |
|---------|--------|
| S3-Download schlägt fehl | `S3_ENDPOINT_URL`, Credentials, freien Speicher im Network Volume prüfen |
| Container startet nicht | Docker-Logs **im Pod** prüfen (nicht auf dem PC), Image-Build-Fehler suchen |
| `/ping` antwortet nicht | Port 8001 in RunPod HTTP Ports eingetragen? |
| OOM / CUDA out of memory | `CONTEXT_SIZE` auf 4096 reduzieren, `N_PARALLEL` auf 2 |
| Model lädt zu langsam | S3-Region und RunPod-Region müssen identisch sein (`eu-ro-1`) |
| **Worker skaliert nicht auf 0** | Min Workers erneut auf `0` prüfen; keine externen Health-Pings/Cron-Jobs, die den Worker künstlich warmhalten; Idle Timeout korrekt gesetzt? |
| Telegram-Relay bekommt keine Antwort | `RUNPOD_ENDPOINT_ID`/`RUNPOD_ACC_API` in SeekerClaw korrekt gesetzt? Cold-Start kann 1–2 Min dauern — Relay-Timeout ausreichend? |
| Fremde Person schreibt den Bot an | Normal & sicher — User-ID-Check verwirft die Nachricht, kein RunPod-Request wird ausgelöst |
| Build läuft versehentlich auf dem PC | STOPPEN — Build gehört ausschließlich in den RunPod-Pod, PC ist nur Dateiursprung |

---

## DATEI-ÜBERSICHT

```
/server/ULTRON/                   ← PC, NUR Dateiursprung, kein Ausführungsort
├── .env                          ← Secrets (nicht committen, nicht löschen!)
├── Dockerfile                    ← Quelle, wird zu RunPod übertragen
├── requirements.txt
├── entrypoint.sh
├── s3_download.py
├── health_shim.py
├── upload_model_to_s3.sh
├── bot/
│   ├── telegram_bot.py           ← Relay-Logik, Steuerung via SeekerClaw
│   └── requirements.txt
└── JARVIS_PROMPT.md              ← Diese Datei

/workspace/ULTRON/                ← RunPod-Pod, HIER wird gebaut
├── (Kopien der obigen Scripts, via Phase 0.2 übertragen)
└── Docker Build läuft hier
```

---

**JARVIS: Bevor du Phase 5 als abgeschlossen markierst, führe explizit Schritt 3.4 durch
(Scale-to-Zero-Verifikation). Das ist der wichtigste einzelne Check in dieser gesamten Mission —
ein funktionierendes ULTRON, das nicht auf 0 zurückskaliert, ist ein teurer Fehlschlag, kein
Erfolg. Und: kein `docker build` auf dem PC — das gehört ausschließlich in den RunPod-Pod.**
