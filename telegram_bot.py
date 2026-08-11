"""
ULTRON — Telegram Bot (runs locally on your PC)
================================================
Polls Telegram for messages, forwards them to the RunPod serverless endpoint,
and returns responses. Also polls the bridge directory for code tasks to execute locally.

Run with:
    pip install -r telegram_bot_requirements.txt
    set -a; source .env; set +a
    python3 telegram_bot.py
"""

import os
import json
import time
import logging
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime, timezone

import httpx
import boto3
from botocore.config import Config as BotoConfig

# ── Configuration ──────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("ULTRON_BOT_TOKEN", "")
ALLOWED_USERS_RAW = os.getenv("TELEGRAM_ALLOWED_USERS", "")
ALLOWED_USERS = set(int(u.strip()) for u in ALLOWED_USERS_RAW.split(",") if u.strip())

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")
RUNPOD_ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID", "")
RUNPOD_BASE_URL = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}"

POLL_INTERVAL = 1  # seconds between Telegram polls
BRIDGE_POLL_INTERVAL = 5  # seconds between bridge directory checks

# ── Bridge via RunPod S3-compatible API ─────────────────────────────────────────
# The bridge folder lives on the RunPod Network Volume at /runpod-volume/bridge
# (worker-side path). Reached from the PC via RunPod's S3-compatible gateway.
# Docs: https://docs.runpod.io/storage/s3-api
RUNPOD_S3_ENDPOINT = os.getenv("RUNPOD_S3_ENDPOINT", "")       # e.g. https://s3api-eu-cz-1.runpod.io
RUNPOD_S3_BUCKET = os.getenv("RUNPOD_S3_BUCKET", "")           # your Network Volume ID
RUNPOD_S3_ACCESS_KEY = os.getenv("RUNPOD_S3_ACCESS_KEY", "")   # "user_..."
RUNPOD_S3_SECRET_KEY = os.getenv("RUNPOD_S3_SECRET_KEY", "")   # "rps_..."
BRIDGE_PREFIX = "bridge/"  # relative to volume root, matches BRIDGE_PATH on the worker
LOCAL_WORKDIR = Path(os.getenv("BRIDGE_LOCAL_WORKDIR", "/tmp/ultron-bridge"))

RUNPOD_S3_REGION = os.getenv("RUNPOD_S3_REGION", "eu-ro-1")  # must match the volume's datacenter

_s3 = None
if RUNPOD_S3_ENDPOINT and RUNPOD_S3_ACCESS_KEY and RUNPOD_S3_SECRET_KEY:
    _s3 = boto3.client(
        "s3",
        endpoint_url=RUNPOD_S3_ENDPOINT,
        aws_access_key_id=RUNPOD_S3_ACCESS_KEY,
        aws_secret_access_key=RUNPOD_S3_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4"),
        region_name=RUNPOD_S3_REGION,
    )

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="[BOT] %(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ── State ──────────────────────────────────────────────────────────────────────
update_offset = 0
# Map Telegram user_id -> session_id
user_sessions: dict[int, str] = {}

# ── Telegram API helpers ───────────────────────────────────────────────────────

async def tg_get(client: httpx.AsyncClient, method: str, **params) -> dict:
    # Use 40s so getUpdates(timeout=30) has breathing room before httpx times out
    resp = await client.get(f"{TELEGRAM_API}/{method}", params=params, timeout=40.0)
    return resp.json()


async def tg_post(client: httpx.AsyncClient, method: str, **data) -> dict:
    resp = await client.post(f"{TELEGRAM_API}/{method}", json=data, timeout=30.0)
    return resp.json()


async def send_message(client: httpx.AsyncClient, chat_id: int, text: str,
                        parse_mode: str = "Markdown") -> None:
    """Send a message to a Telegram chat. Splits long messages automatically."""
    MAX_LEN = 4096
    while text:
        chunk = text[:MAX_LEN]
        text = text[MAX_LEN:]
        try:
            await tg_post(client, "sendMessage", chat_id=chat_id, text=chunk,
                          parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            # Retry without markdown
            try:
                await tg_post(client, "sendMessage", chat_id=chat_id, text=chunk)
            except Exception:
                pass

# ── RunPod API ─────────────────────────────────────────────────────────────────

SPINNER_FRAMES = ["⏳ ULTRON denkt nach.", "⏳ ULTRON denkt nach..", "⏳ ULTRON denkt nach..."]

# How long a RunPod cold-start + model download can take (seconds).
# After this threshold the bot warns the user.
COLD_START_WARN_AFTER = 60
TYPING_REFRESH = 4  # seconds; Telegram's "typing..." indicator auto-expires after ~5s


async def _keep_alive(client: httpx.AsyncClient, chat_id: int, status_msg_id: int | None,
                       stop_event: asyncio.Event) -> None:
    """Keeps 'typing...' alive and animates a status message until stop_event is set."""
    frame = 0
    elapsed = 0
    cold_start_warned = False
    while not stop_event.is_set():
        try:
            await tg_post(client, "sendChatAction", chat_id=chat_id, action="typing")
            if status_msg_id is not None:
                if not cold_start_warned and elapsed >= COLD_START_WARN_AFTER:
                    text = (
                        "⏳ ULTRON startet kalt — GPU wird hochgefahren und Modell geladen.\n"
                        "Das dauert beim ersten Mal ~10–15 Minuten. Bitte warten..."
                    )
                    cold_start_warned = True
                else:
                    text = SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]
                await tg_post(client, "editMessageText", chat_id=chat_id,
                               message_id=status_msg_id, text=text)
                frame += 1
        except Exception:
            pass  # editMessageText fails harmlessly if text is unchanged / rate-limited
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TYPING_REFRESH)
        except asyncio.TimeoutError:
            elapsed += TYPING_REFRESH


async def call_runpod(client: httpx.AsyncClient, message: str, session_id: str,
                       chat_id: int | None = None, max_wait: int = 1200) -> str:
    """Submit a job to RunPod and wait for the result.

    If chat_id is given, shows a live 'typing...' indicator plus an animated
    status message in the chat, both removed right before the final answer.
    """
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": {
            "message": message,
            "session_id": session_id,
        }
    }

    status_msg_id = None
    stop_event = asyncio.Event()
    keepalive_task = None

    if chat_id is not None:
        try:
            sent = await tg_post(client, "sendMessage", chat_id=chat_id,
                                  text=SPINNER_FRAMES[0])
            status_msg_id = sent.get("result", {}).get("message_id")
        except Exception:
            pass
        keepalive_task = asyncio.create_task(
            _keep_alive(client, chat_id, status_msg_id, stop_event))

    try:
        # Submit job
        resp = await client.post(f"{RUNPOD_BASE_URL}/run", json=payload,
                                  headers=headers, timeout=30.0)
        resp.raise_for_status()
        job_data = resp.json()
        job_id = job_data.get("id")

        if not job_id:
            return f"Error: No job ID returned from RunPod. Response: {job_data}"

        logger.info(f"RunPod job submitted: {job_id}")

        # Poll for result
        start = time.time()
        while time.time() - start < max_wait:
            await asyncio.sleep(3)
            status_resp = await client.get(f"{RUNPOD_BASE_URL}/status/{job_id}",
                                            headers=headers, timeout=15.0)
            status_data = status_resp.json()
            status = status_data.get("status", "")

            if status == "COMPLETED":
                output = status_data.get("output", {})
                if isinstance(output, dict):
                    # Detect warming_up response from handler — auto-retry
                    if output.get("status") == "warming_up":
                        msg = output.get("message", "⏳ Worker startet noch...")
                        retry_after = int(output.get("retry_after_seconds", 60))
                        logger.info(f"Worker warming up — retrying in {retry_after}s")
                        # Update the spinner message so user sees progress
                        if chat_id is not None and status_msg_id is not None:
                            try:
                                await tg_post(client, "editMessageText",
                                               chat_id=chat_id,
                                               message_id=status_msg_id,
                                               text=msg)
                            except Exception:
                                pass
                        # Wait, then resubmit
                        await asyncio.sleep(retry_after)
                        resp2 = await client.post(f"{RUNPOD_BASE_URL}/run",
                                                   json=payload, headers=headers,
                                                   timeout=30.0)
                        resp2.raise_for_status()
                        job_data2 = resp2.json()
                        new_job_id = job_data2.get("id")
                        if new_job_id:
                            job_id = new_job_id
                            start = time.time()  # reset timeout for the real job
                            logger.info(f"Retried — new job: {job_id}")
                        continue
                    return output.get("response", str(output))
                return str(output)

            elif status == "FAILED":
                error = status_data.get("error", "Unknown error")
                return f"Job failed: {error}"

            elif status in ("IN_QUEUE", "IN_PROGRESS"):
                elapsed = int(time.time() - start)
                logger.debug(f"Job {job_id} status: {status} ({elapsed}s)")
            else:
                logger.warning(f"Unexpected status: {status}")

        return f"Timeout: Job {job_id} did not complete within {max_wait}s."

    finally:
        # Stop the animation/typing and remove the status message before
        # the real answer is sent.
        stop_event.set()
        if keepalive_task is not None:
            await keepalive_task
        if chat_id is not None and status_msg_id is not None:
            try:
                await tg_post(client, "deleteMessage", chat_id=chat_id,
                               message_id=status_msg_id)
            except Exception:
                pass

# ── Command Handlers ───────────────────────────────────────────────────────────

async def cmd_start(client: httpx.AsyncClient, chat_id: int, user_id: int) -> None:
    text = (
        "*ULTRON is online.*\n\n"
        "I am an AI agent powered by Qwen2.5-Coder-32B running on RunPod.\n\n"
        "*Commands:*\n"
        "/help — Show this help\n"
        "/tools — List available agent tools\n"
        "/crypto — BTC/ETH/SOL live prices\n"
        "/search `<query>` — Quick web search\n"
        "/memory — Show memory stats\n"
        "/clear — Clear conversation memory\n\n"
        "Or just send any message to chat with me."
    )
    await send_message(client, chat_id, text)


async def cmd_help(client: httpx.AsyncClient, chat_id: int) -> None:
    await cmd_start(client, chat_id, 0)


async def cmd_tools(client: httpx.AsyncClient, chat_id: int, session_id: str) -> None:
    await send_message(client, chat_id, "Fetching available tools...")
    headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}", "Content-Type": "application/json"}
    resp = await client.post(
        f"{RUNPOD_BASE_URL}/runsync",
        json={"input": {"action": "list_tools"}},
        headers=headers, timeout=30.0,
    )
    data = resp.json()
    output = data.get("output", {})
    builtin = output.get("builtin_tools", [])
    custom = output.get("custom_tools", [])

    text = "*Built-in Tools:*\n"
    for t in builtin:
        text += f"• `{t['name']}` — {t['description']}\n"
    if custom:
        text += "\n*Custom Tools:*\n"
        for t in custom:
            text += f"• `{t['name']}` — {t.get('description', '')}\n"

    await send_message(client, chat_id, text)


async def cmd_crypto(client: httpx.AsyncClient, chat_id: int) -> None:
    await send_message(client, chat_id, "Fetching crypto prices...")
    headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}", "Content-Type": "application/json"}
    resp = await client.post(
        f"{RUNPOD_BASE_URL}/runsync",
        json={"input": {"message": "Show me current prices for Bitcoin, Ethereum, and Solana in USD and EUR. Also show trending coins.", "session_id": "crypto_cmd"}},
        headers=headers, timeout=60.0,
    )
    data = resp.json()
    output = data.get("output", {})
    response = output.get("response", str(output)) if isinstance(output, dict) else str(output)
    await send_message(client, chat_id, response)


async def cmd_clear(client: httpx.AsyncClient, chat_id: int, session_id: str) -> None:
    headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}", "Content-Type": "application/json"}
    await client.post(
        f"{RUNPOD_BASE_URL}/runsync",
        json={"input": {"action": "clear_memory", "session_id": session_id}},
        headers=headers, timeout=15.0,
    )
    await send_message(client, chat_id, "Memory cleared. Starting fresh.")


async def cmd_memory(client: httpx.AsyncClient, chat_id: int, session_id: str) -> None:
    headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}", "Content-Type": "application/json"}
    resp = await client.post(
        f"{RUNPOD_BASE_URL}/runsync",
        json={"input": {"action": "memory_stats", "session_id": session_id}},
        headers=headers, timeout=15.0,
    )
    data = resp.json()
    output = data.get("output", {})
    text = (
        f"*Memory Stats*\n"
        f"Total sessions: {output.get('total_sessions', '?')}\n"
        f"Your messages: {output.get('current_session', {}).get('message_count', '?')}\n"
        f"Memory window: {output.get('memory_window', '?')} messages"
    )
    await send_message(client, chat_id, text)

async def cmd_wake(client: httpx.AsyncClient, chat_id: int, session_id: str) -> None:
    """Send a no-op health ping to RunPod to pre-warm the worker."""
    await send_message(client, chat_id,
                       "🔌 Sende Wake-up-Ping an RunPod... (dauert bei Kaltstart ~10–15 Min)")
    try:
        response = await call_runpod(client, "__health__", session_id, chat_id=chat_id,
                                     max_wait=1200)
        await send_message(client, chat_id, f"✅ Worker ist online!\n{response}")
    except Exception as e:
        await send_message(client, chat_id, f"❌ Wake fehlgeschlagen: {e}")


# ── Bridge Polling (via RunPod S3-compatible API) ──────────────────────────────

def _s3_list_pending_tasks() -> list[str]:
    """List task JSON keys under bridge/ that aren't *_result.json."""
    keys = []
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=RUNPOD_S3_BUCKET, Prefix=BRIDGE_PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".json") and not key.endswith("_result.json"):
                keys.append(key)
    return keys


def _s3_get_json(key: str) -> dict:
    obj = _s3.get_object(Bucket=RUNPOD_S3_BUCKET, Key=key)
    return json.loads(obj["Body"].read())


def _s3_put_json(key: str, data: dict) -> None:
    _s3.put_object(Bucket=RUNPOD_S3_BUCKET, Key=key,
                    Body=json.dumps(data, indent=2).encode("utf-8"))


def _s3_download(key: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    _s3.download_file(RUNPOD_S3_BUCKET, key, str(local_path))


async def poll_bridge() -> None:
    """Poll the RunPod Network Volume (via S3 API) for pending code tasks,
    execute them locally, and write results back."""
    if _s3 is None:
        logger.warning("Bridge disabled: RUNPOD_S3_* env vars not set. "
                        "Set RUNPOD_S3_ENDPOINT / RUNPOD_S3_BUCKET / "
                        "RUNPOD_S3_ACCESS_KEY / RUNPOD_S3_SECRET_KEY to enable.")
        return

    LOCAL_WORKDIR.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            for task_key in await asyncio.to_thread(_s3_list_pending_tasks):
                try:
                    task = await asyncio.to_thread(_s3_get_json, task_key)
                    if task.get("status") != "pending":
                        continue

                    task_id = task["task_id"]
                    logger.info(f"Executing bridge task: {task_id}")

                    # code_file on the worker side looks like bridge/<id>.py
                    # (BRIDGE_PATH=/runpod-volume/bridge -> relative key bridge/<id>.py)
                    code_key = f"{BRIDGE_PREFIX}{task_id}.{task.get('language', 'py')[:2]}"
                    local_code = LOCAL_WORKDIR / f"{task_id}.py"
                    await asyncio.to_thread(_s3_download, code_key, local_code)

                    result = subprocess.run(
                        ["python3", str(local_code)],
                        capture_output=True, text=True, timeout=60,
                    )

                    result_data = {
                        "task_id": task_id,
                        "status": "completed",
                        "return_code": result.returncode,
                        "stdout": result.stdout[:5000],
                        "stderr": result.stderr[:2000],
                        "executed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    result_key = f"{BRIDGE_PREFIX}{task_id}_result.json"
                    await asyncio.to_thread(_s3_put_json, result_key, result_data)

                    task["status"] = "completed"
                    await asyncio.to_thread(_s3_put_json, task_key, task)

                    logger.info(f"Bridge task {task_id} completed (rc={result.returncode})")

                except Exception as e:
                    logger.error(f"Bridge task error ({task_key}): {e}")

        except Exception as e:
            logger.error(f"Bridge poll error: {e}")

        await asyncio.sleep(BRIDGE_POLL_INTERVAL)

# ── Main Polling Loop ──────────────────────────────────────────────────────────

async def main():
    global update_offset

    if not BOT_TOKEN:
        logger.error("ULTRON_BOT_TOKEN is not set. Check your .env file.")
        return
    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        logger.error("RUNPOD_API_KEY or RUNPOD_ENDPOINT_ID is not set.")
        return

    logger.info("ULTRON Telegram bot starting...")
    logger.info(f"Allowed users: {ALLOWED_USERS or 'ALL (no restriction)'}")
    logger.info(f"RunPod endpoint: {RUNPOD_ENDPOINT_ID}")

    # Start bridge polling in background
    asyncio.create_task(poll_bridge())

    async with httpx.AsyncClient() as client:
        # Verify bot token
        me = await tg_get(client, "getMe")
        if not me.get("ok"):
            logger.error(f"Invalid bot token: {me}")
            return
        bot_name = me["result"]["username"]
        logger.info(f"Bot connected: @{bot_name}")

        logger.info("Polling for updates...")
        while True:
            try:
                updates = await tg_get(client, "getUpdates",
                                        offset=update_offset, timeout=30, limit=10)
                if not updates.get("ok"):
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                for update in updates.get("result", []):
                    update_offset = update["update_id"] + 1
                    message = update.get("message", {})
                    if not message:
                        continue

                    chat_id = message["chat"]["id"]
                    user_id = message["from"]["id"]
                    text = message.get("text", "").strip()

                    if not text:
                        continue

                    # Access control
                    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
                        await send_message(client, chat_id,
                                           "Access denied. Your user ID is not authorized.")
                        continue

                    # Get or create session ID for this user
                    if user_id not in user_sessions:
                        user_sessions[user_id] = f"tg_{user_id}"
                    session_id = user_sessions[user_id]

                    logger.info(f"Message from {user_id}: {text[:80]}")

                    # Route commands
                    if text.startswith("/start"):
                        await cmd_start(client, chat_id, user_id)
                    elif text.startswith("/help"):
                        await cmd_help(client, chat_id)
                    elif text.startswith("/wake"):
                        await cmd_wake(client, chat_id, session_id)
                    elif text.startswith("/tools"):
                        await cmd_tools(client, chat_id, session_id)
                    elif text.startswith("/crypto"):
                        await cmd_crypto(client, chat_id)
                    elif text.startswith("/clear"):
                        await cmd_clear(client, chat_id, session_id)
                    elif text.startswith("/memory"):
                        await cmd_memory(client, chat_id, session_id)
                    elif text.startswith("/search "):
                        query = text[8:].strip()
                        response = await call_runpod(client,
                            f"Search the web for: {query}", session_id, chat_id=chat_id)
                        await send_message(client, chat_id, response)
                    else:
                        # Regular message — call_runpod shows typing + a live
                        # status message on its own, removed before the reply.
                        try:
                            response = await call_runpod(client, text, session_id,
                                                          chat_id=chat_id)
                            await send_message(client, chat_id, response)
                        except Exception as e:
                            logger.error(f"RunPod call failed: {e}")
                            await send_message(client, chat_id,
                                               f"Error communicating with ULTRON: {e}")

            except Exception as e:
                logger.error(f"Polling error: {type(e).__name__}: {e or 'no details'}")
                await asyncio.sleep(5)

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
