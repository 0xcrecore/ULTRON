"""
ULTRON — Telegram Bot (läuft auf dem PC, NICHT auf RunPod)
=============================================================
Pollt Telegram per long-polling. Bei eingehender Nachricht vom
autorisierten User wird ein RunPod Serverless Job ausgelöst (runsync),
was den Worker aus dem Idle-Zustand aufweckt (Cold-Start falls nötig)
und danach automatisch wieder in Idle -> Scale-to-Zero geht.

Läuft dauerhaft auf dem PC — das kostet nichts an GPU-Zeit, nur der
RunPod-Worker kostet Geld, und der läuft nur während aktiver Requests.

ENV (.env):
  ULTRON_BOT_TOKEN
  ULTRON_ALLOWED_USER_ID   (z.B. 7525618433)
  RUNPOD_API_KEY
  RUNPOD_ENDPOINT_ID
"""

import os
import sys
import time
import logging
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="[ULTRON-bot] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ultron-bot")

BOT_TOKEN = os.environ.get("ULTRON_BOT_TOKEN")
ALLOWED_USER_ID = os.environ.get("ULTRON_ALLOWED_USER_ID")
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY")
RUNPOD_ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID")

if not all([BOT_TOKEN, ALLOWED_USER_ID, RUNPOD_API_KEY, RUNPOD_ENDPOINT_ID]):
    log.error(
        "Fehlende ENV-Variablen. Benötigt: ULTRON_BOT_TOKEN, "
        "ULTRON_ALLOWED_USER_ID, RUNPOD_API_KEY, RUNPOD_ENDPOINT_ID"
    )
    sys.exit(1)

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
RUNPOD_API = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/runsync"
RUNPOD_TIMEOUT_SECONDS = float(os.environ.get("RUNPOD_TIMEOUT_SECONDS", "180"))

SYSTEM_PROMPT = os.environ.get(
    "ULTRON_SYSTEM_PROMPT",
    "Du bist ULTRON, ein hilfreicher Coding-Assistent.",
)


def send_message(chat_id: int, text: str) -> None:
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i : i + max_len]
        try:
            httpx.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": chunk},
                timeout=15,
            )
        except httpx.RequestError as e:
            log.error("Telegram sendMessage fehlgeschlagen: %s", e)


def send_typing(chat_id: int) -> None:
    try:
        httpx.post(
            f"{TELEGRAM_API}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=10,
        )
    except httpx.RequestError:
        pass


def call_ultron(prompt: str) -> str:
    """Weckt RunPod (falls idle) und holt eine Antwort."""
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": {
            "payload": {
                "model": "ultron",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1024,
                "temperature": 0.7,
            }
        }
    }

    log.info("Sende Job an RunPod Endpoint %s...", RUNPOD_ENDPOINT_ID)
    try:
        with httpx.Client(timeout=RUNPOD_TIMEOUT_SECONDS) as client:
            resp = client.post(RUNPOD_API, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return "⚠ Timeout — ULTRON braucht beim Cold-Start manchmal >60s. Versuch's nochmal."
    except httpx.HTTPStatusError as e:
        log.error("RunPod HTTP-Fehler: %s", e.response.text[:300])
        return f"⚠ RunPod-Fehler ({e.response.status_code})"
    except httpx.RequestError as e:
        log.error("RunPod Verbindungsfehler: %s", e)
        return "⚠ Verbindung zu RunPod fehlgeschlagen."

    output = data.get("output", {})
    if isinstance(output, dict) and "error" in output:
        return f"⚠ ULTRON-Fehler: {output['error']}"

    try:
        return output["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        log.warning("Unerwartetes Response-Format: %s", str(data)[:500])
        return "⚠ Unerwartetes Antwortformat von ULTRON."


def poll_loop() -> None:
    log.info("ULTRON Telegram Bot gestartet. Warte auf Nachrichten...")
    offset = 0
    while True:
        try:
            resp = httpx.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35,
            )
            resp.raise_for_status()
            updates = resp.json().get("result", [])
        except httpx.RequestError as e:
            log.error("Telegram Poll-Fehler: %s — retry in 5s", e)
            time.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message")
            if not message or "text" not in message:
                continue

            chat_id = message["chat"]["id"]
            user_id = str(message["from"]["id"])
            text = message["text"]

            if user_id != str(ALLOWED_USER_ID):
                log.warning("Nicht autorisierter User: %s — ignoriert.", user_id)
                continue

            log.info("Nachricht von %s: %s", user_id, text[:80])
            send_typing(chat_id)
            reply = call_ultron(text)
            send_message(chat_id, reply)


if __name__ == "__main__":
    poll_loop()
