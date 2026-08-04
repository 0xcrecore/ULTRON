---
name: 🤖 friday
description: Steuere und überwache den Friday AI Agent (@Friday_AgentV1bot) auf dem HP EliteDesk 800 G2 (Linux Mint 22.1). Status check, Start/Neustart, Logs lesen, und Updates einspielen.
triggers:
  - friday
  - friday agent
  - @friday_agentv1bot
  - friday läuft
  - bot friday
  - friday bot
  - friday neu starten
  - friday neustart
  - friday status
  - friday log
  - friday update
  - friday patchen
requires:
  bridge: pc-control
  env: [BRIDGE_SECRET, MAC_PC, FRIDAY_BOT_TOKEN]
---

# 🤖 Friday Agent Skill

## System-Info

- **Host:** HP EliteDesk 800 G2 — Linux Mint 22.1 (Xia)
- **RAM:** ~24 GB total, ~3.2 GB frei bei laufendem Friday
- **Pfad:** `/server/AgentFriday/`
- **Größe:** ~6.1 GB (inkl. Daten/Memory)
- **PC-IP:** `192.168.178.67`
- **Bridge-Port:** 7000

## Architektur

### Bot-Service (Python, manuell gestartet via nohup)
| Datei | Zweck |
|---|---|
| `telegram_bot.py` | Telegram Long-Polling (python-telegram-bot), reagiert mit 🤖 auf jede Nachricht |
| `agent.py` | Core AI Logik: `process_message()`, Memory, Skills-System |
| `llm.py` | LLM-Client via httpx → lokaler llama-server (`localhost:8080`) |
| `config.py` | Config-Klasse aus `.env` — Token, LLM_URL, Pfade, Parameter |
| `.env` | Secrets: FRIDAY_BOT_TOKEN, LLAMA_SERVER, usw. |
| `logs/bot.log` | Aktuelles Bot-Log |
| `skills/` | Skills-Verzeichnis (bewerbung, ophanim-userbot, pc-control, poco-connection, seeker-connection) |
| `data/memory/` | JSON-Memory-Dateien |

### LLM-Server (systemd Service: `llama-jarvis.service`)
| Eigenschaft | Wert |
|---|---|
| Binary | `/server/SeekerClawAI/bin/llama-server` |
| Model | `/server/models/jarvis.gguf` (Qwen3-4B, Q4_K_M) |
| Port | `127.0.0.1:8080` |
| Context | 65.536 Token |
| Threads | 4 |
| Cache | q4_0 (K+V) |
| GPU | 0 layers (CPU-only) |
| Restart | always, 5s delay |
| User | root |

### Bot Features
- ✅ **🤖 Reaction** auf jede eingehende Nachricht (setMessageReaction API)
- ✅ **Typing-Indikator** während der LLM-Verarbeitung
- ✅ **Allowed Users:** Xcrecore, 7525618433 (alle anderen werden ignoriert)
- ✅ **Skills-System** mit Unterverzeichnissen
- ✅ **Memory** (JSON, max 50 History-Einträge)
- ✅ **Logging** nach `logs/bot.log`
- ✅ **Version:** 1.0.0
- ✅ **Sprache:** Deutsch (Default)

### LLM Parameter
| Parameter | Wert |
|---|---|
| temperature | 0.7 |
| top_p | 0.9 |
| max_tokens | 8.192 |
| timeout | 300s |

## Aktionen

### Status prüfen
```python
# Bridge-Call Template:
{
  "secret": process.env.BRIDGE_SECRET,
  "cmd": "ps aux | grep '[t]elegram_bot'",
  "timeout": 5
}
```
**Erfolg:** Zeigt PID + Laufzeit. Log-Check: `tail -20 /server/AgentFriday/logs/bot.log`

### Starten / Neustarten
```python
# 1. Alle alten Instanzen killen
pkill -f "telegram_bot.py"
sleep 2

# 2. Log leeren
> /server/AgentFriday/logs/bot.log

# 3. Neu starten (detached via Python subprocess)
python3 -c "
import subprocess, os
subprocess.Popen(
  ['python3', '/server/AgentFriday/telegram_bot.py'],
  cwd='/server/AgentFriday',
  stdout=open('/server/AgentFriday/logs/bot.log', 'w'),
  stderr=subprocess.STDOUT,
  close_fds=True,
  preexec_fn=os.setsid
)
"

# 4. 15s warten, dann prüfen:
ps aux | grep "[t]elegram_bot"
tail -20 /server/AgentFriday/logs/bot.log
```

### Logs lesen
- Letzte 30 Zeilen: `tail -30 /server/AgentFriday/logs/bot.log`
- Letzte Fehler: `grep -i "error\|exception\|traceback" /server/AgentFriday/logs/bot.log`

### PC einschalten (falls aus)
- **WoL:** Fritzbox UPnP → `192.168.178.1:49000` → `X_AVM-DE_WakeOnLANByMACAddress`
- **MAC:** aus env `MAC_PC`
- **Warten:** 35s nach WoL, dann Bridge `/ping` checken

### PC ausschalten (nach Erledigung)
```python
{
  "secret": process.env.BRIDGE_SECRET,
  "cmd": "shutdown -h now",
  "timeout": 15
}
```
**→ IMMER ausschalten nach Erledigung, außer User sagt was anderes**

## Bekannte Probleme

### Bot läuft aber antwortet nicht
1. Prüfen ob LLM-Server läuft: `curl -s http://127.0.0.1:8080/v1/models`
2. Prüfen ob `llama-jarvis.service` aktiv ist: `systemctl is-active llama-jarvis.service`
3. Log checken: `tail -30 /server/AgentFriday/logs/bot.log`

### Mehrere Bot-Instanzen (Conflict-Error)
Telegram erlaubt nur **einen** Long-Poller pro Bot. Lösung: `pkill -f "telegram_bot.py"` → dann sauber neustarten.

### Bot startet nicht / stürzt ab
- Prüfen ob Python3 installiert: `which python3`
- Dependencies checken: `pip list 2>/dev/null | grep -E "python-telegram-bot|httpx|python-dotenv"`
- Fehlende Module: `pip install python-telegram-bot httpx python-dotenv`

## Hinweise

- **Nie selbstständig PC einschalten** — erst fragen, nur mit Zustimmung
- **Nach Erledigung PC ausschalten** (außer User sagt anders)
- **Bridge hat 30s Timeout** — lange Tasks (Bot-Neustart) über detach + späteren Check
- **Bot-Patch:** Wenn Änderungen nötig, Dateien per Bridge lesen/schreiben, dann neustarten
- **Skill ist READ-ONLY für mich** — ich lese den Status, führe Aktionen nur auf Befehl aus