"""
ULTRON — RunPod Serverless Handler
===================================
Nimmt Serverless-Jobs entgegen und leitet sie an den lokal im Container
laufenden llama-server (OpenAI-kompatible API auf Port 8000) weiter.

RunPod startet diesen Prozess NUR wenn ein Job in der Queue liegt.
Nach IDLE_TIMEOUT (in der Endpoint-Konfiguration, nicht hier) ohne neue
Jobs wird der Worker automatisch beendet -> 0 GPU-Kosten im Leerlauf.

Erwartetes Job-Input-Format (RunPod runsync/run):
{
  "input": {
    "endpoint": "chat/completions",     # optional, default: chat/completions
    "payload": { ... OpenAI-kompatibler Body ... }
  }
}
"""

import os
import sys
import logging
import httpx
import runpod

logging.basicConfig(
    level=logging.INFO,
    format="[ULTRON-handler] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ultron")

LLAMA_PORT = os.environ.get("PORT", "8000")
LLAMA_BASE_URL = f"http://127.0.0.1:{LLAMA_PORT}"
LLAMA_API_KEY = os.environ.get("LLAMA_SERVER_API_KEY", "")

DEFAULT_ENDPOINT = "v1/chat/completions"
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "300"))


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if LLAMA_API_KEY:
        h["Authorization"] = f"Bearer {LLAMA_API_KEY}"
    return h


def handler(job: dict) -> dict:
    """
    RunPod ruft diese Funktion pro Job auf.
    """
    job_input = job.get("input", {}) or {}
    endpoint = job_input.get("endpoint", DEFAULT_ENDPOINT).lstrip("/")
    payload = job_input.get("payload")

    if payload is None:
        # Erlaube auch flaches Format: {"input": {"messages": [...], ...}}
        payload = {k: v for k, v in job_input.items() if k != "endpoint"}

    if not payload:
        return {"error": "Kein 'payload' im Job-Input gefunden."}

    url = f"{LLAMA_BASE_URL}/{endpoint}"
    log.info("Weiterleitung an llama-server: %s", url)

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(url, json=payload, headers=_headers())
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        log.error("llama-server HTTP-Fehler: %s — %s", e.response.status_code, e.response.text[:500])
        return {"error": f"llama-server HTTP {e.response.status_code}", "detail": e.response.text[:1000]}
    except httpx.RequestError as e:
        log.error("Verbindungsfehler zu llama-server: %s", e)
        return {"error": f"Verbindungsfehler: {e}"}
    except Exception as e:  # noqa: BLE001
        log.exception("Unerwarteter Fehler im Handler")
        return {"error": f"Unerwarteter Fehler: {e}"}


if __name__ == "__main__":
    log.info("ULTRON Handler startet — wartet auf RunPod Jobs...")
    runpod.serverless.start({"handler": handler})
