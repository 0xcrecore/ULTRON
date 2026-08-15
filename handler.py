"""
ULTRON — RunPod Serverless Handler
===================================
Agentic loop with tools:
  - web_search       : DuckDuckGo search + URL fetching
  - crypto_price     : Live crypto data via CoinGecko
  - code_bridge      : Write tasks to Network Volume for local PC execution
  - register_tool    : Add new tools to the registry at runtime
  - list_tools       : List all registered tools
  - clear_memory     : Clear session memory
  - memory_stats     : Show memory usage
"""

import os
import re
import json
import time
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import httpx
import runpod

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[ULTRON] %(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
LLAMA_URL = "http://127.0.0.1:8000"
LLAMA_API_KEY = os.getenv("LLAMA_SERVER_API_KEY", "ultron")
AGENT_NAME = os.getenv("AGENT_NAME", "ULTRON")
MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "30"))
MEMORY_WINDOW = int(os.getenv("MEMORY_WINDOW", "20"))
CONTEXT_SIZE = int(os.getenv("CONTEXT_SIZE", "8192"))

VOLUME_PATH = Path(os.getenv("VOLUME_PATH", "/runpod-volume"))
TOOLS_PATH = Path(os.getenv("TOOLS_PATH", "/runpod-volume/tools"))
MEMORY_PATH = Path(os.getenv("MEMORY_PATH", "/runpod-volume/memory"))
BRIDGE_PATH = Path(os.getenv("BRIDGE_PATH", "/runpod-volume/bridge"))
LOG_PATH = Path(os.getenv("LOG_PATH", "/runpod-volume/logs"))
# Semaphore written by entrypoint.sh once llama-server is ready.
# handler starts BEFORE the model downloads, so jobs arriving during the
# cold download get a "warming_up" response instead of a job timeout.
MODEL_READY_FILE = Path(os.getenv("MODEL_READY_FILE", "/runpod-volume/.model_ready"))

# Ensure directories exist
for _dir in [TOOLS_PATH, MEMORY_PATH, BRIDGE_PATH, LOG_PATH]:
    _dir.mkdir(parents=True, exist_ok=True)

# ── Load system prompt ─────────────────────────────────────────────────────────
_PROMPT_FILE = Path("/app/AGENT_PROMPT.md")
SYSTEM_PROMPT = _PROMPT_FILE.read_text() if _PROMPT_FILE.exists() else (
    f"You are {AGENT_NAME}, an advanced AI agent. "
    "You have access to tools for web search, crypto data, code execution, and more. "
    "When you want to use a tool, output exactly: "
    "<tool_call>{\"tool\": \"tool_name\", ...params...}</tool_call>\n"
    "After receiving tool results, continue reasoning and provide a helpful response."
)

# ── Memory ─────────────────────────────────────────────────────────────────────

def load_memory(session_id: str) -> list[dict]:
    """Load conversation history for a session."""
    path = MEMORY_PATH / f"context_{session_id}.json"
    try:
        if path.exists():
            data = json.loads(path.read_text())
            messages = data.get("messages", [])
            # Return last N messages
            return messages[-MEMORY_WINDOW:]
    except Exception as e:
        logger.warning(f"Failed to load memory for session {session_id}: {e}")
    return []


def save_memory(session_id: str, messages: list[dict]) -> None:
    """Save conversation history for a session."""
    path = MEMORY_PATH / f"context_{session_id}.json"
    try:
        existing = []
        if path.exists():
            data = json.loads(path.read_text())
            existing = data.get("messages", [])
        # Append new messages
        all_messages = existing + messages
        # Keep last 100 messages total
        all_messages = all_messages[-100:]
        path.write_text(json.dumps({
            "session_id": session_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "messages": all_messages,
        }, indent=2))
    except Exception as e:
        logger.warning(f"Failed to save memory for session {session_id}: {e}")


def clear_memory(session_id: str) -> bool:
    """Delete memory for a session."""
    path = MEMORY_PATH / f"context_{session_id}.json"
    try:
        if path.exists():
            path.unlink()
        return True
    except Exception:
        return False

# ── Tool Registry ──────────────────────────────────────────────────────────────

def load_registry() -> dict:
    """Load the tool registry."""
    path = TOOLS_PATH / "registry.json"
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as e:
        logger.warning(f"Failed to load tool registry: {e}")
    return {"version": "1.0", "tools": []}


def save_registry(registry: dict) -> None:
    """Save the tool registry."""
    path = TOOLS_PATH / "registry.json"
    path.write_text(json.dumps(registry, indent=2))


def register_tool(name: str, description: str, endpoint: str = "", schema: dict = None) -> dict:
    """Register a new tool in the registry."""
    registry = load_registry()
    # Check for duplicate
    for tool in registry["tools"]:
        if tool["name"] == name:
            tool.update({"description": description, "endpoint": endpoint,
                          "schema": schema or {}, "updated_at": datetime.now(timezone.utc).isoformat()})
            save_registry(registry)
            return {"status": "updated", "tool": name}
    # Add new tool
    registry["tools"].append({
        "name": name,
        "description": description,
        "endpoint": endpoint,
        "schema": schema or {},
        "registered_at": datetime.now(timezone.utc).isoformat(),
    })
    save_registry(registry)
    return {"status": "registered", "tool": name, "total_tools": len(registry["tools"])}

# ── Tools Implementation ───────────────────────────────────────────────────────

async def tool_web_search(query: str, max_results: int = 5) -> dict:
    """Search the web using DuckDuckGo (no API key required)."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                headers={"User-Agent": "ULTRON-Agent/1.0"},
            )
            data = resp.json()

        results = []

        # Instant answer
        if data.get("AbstractText"):
            results.append({
                "type": "instant_answer",
                "title": data.get("Heading", ""),
                "text": data["AbstractText"],
                "url": data.get("AbstractURL", ""),
                "source": data.get("AbstractSource", ""),
            })

        # Related topics
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if "Text" in topic:
                results.append({
                    "type": "related",
                    "text": topic.get("Text", ""),
                    "url": topic.get("FirstURL", ""),
                })
            elif "Topics" in topic:  # grouped results
                for sub in topic.get("Topics", [])[:2]:
                    results.append({
                        "type": "related",
                        "text": sub.get("Text", ""),
                        "url": sub.get("FirstURL", ""),
                    })

        return {"tool": "web_search", "query": query, "results": results[:max_results]}

    except Exception as e:
        return {"tool": "web_search", "error": str(e), "query": query}


async def tool_fetch_url(url: str, max_chars: int = 3000) -> dict:
    """Fetch and extract text content from a URL."""
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "ULTRON-Agent/1.0"})
            html = resp.text

        # Try BeautifulSoup first, fallback to regex
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        except ImportError:
            # Fallback: strip HTML tags with regex
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()

        # Trim to max_chars
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [truncated at {max_chars} chars]"

        return {
            "tool": "fetch_url",
            "url": url,
            "status_code": resp.status_code,
            "content": text,
        }

    except Exception as e:
        return {"tool": "fetch_url", "error": str(e), "url": url}


async def tool_crypto_price(coins: str = "bitcoin,ethereum,solana",
                             currencies: str = "usd,eur") -> dict:
    """Get live crypto prices from CoinGecko (no API key required)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coins, "vs_currencies": currencies,
                        "include_24hr_change": "true", "include_market_cap": "true"},
                headers={"Accept": "application/json"},
            )
            prices = resp.json()

        return {"tool": "crypto_price", "coins": coins, "data": prices,
                "timestamp": datetime.now(timezone.utc).isoformat()}

    except Exception as e:
        return {"tool": "crypto_price", "error": str(e)}


async def tool_crypto_trending() -> dict:
    """Get trending crypto coins from CoinGecko."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/search/trending",
                headers={"Accept": "application/json"},
            )
            data = resp.json()

        trending = [
            {
                "name": coin["item"]["name"],
                "symbol": coin["item"]["symbol"],
                "market_cap_rank": coin["item"].get("market_cap_rank"),
                "price_btc": coin["item"].get("price_btc"),
            }
            for coin in data.get("coins", [])[:10]
        ]

        return {"tool": "crypto_trending", "trending": trending,
                "timestamp": datetime.now(timezone.utc).isoformat()}

    except Exception as e:
        return {"tool": "crypto_trending", "error": str(e)}


async def tool_code_bridge(code: str, language: str = "python",
                            job_id: str = "", description: str = "") -> dict:
    """
    Write a code task to the Network Volume bridge directory.
    The local PC agent (telegram_bot.py) polls this directory and executes tasks.
    """
    task_id = job_id or f"task_{int(time.time())}"
    task_file = BRIDGE_PATH / f"{task_id}.json"
    code_file = BRIDGE_PATH / f"{task_id}.{language[:2]}"  # .py, .sh, etc.

    task = {
        "task_id": task_id,
        "language": language,
        "description": description,
        "code": code,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_file": str(code_file),
    }

    task_file.write_text(json.dumps(task, indent=2))
    code_file.write_text(code)

    return {
        "tool": "code_bridge",
        "task_id": task_id,
        "status": "written",
        "task_file": str(task_file),
        "code_file": str(code_file),
        "instruction": (
            f"Task written to bridge. Your local PC agent should execute: "
            f"{code_file} and write results to {BRIDGE_PATH}/{task_id}_result.json"
        ),
    }


async def tool_bridge_result(task_id: str, max_wait: float = 45.0,
                               poll_interval: float = 3.0) -> dict:
    """Poll for the result of a code bridge task executed by the local PC.

    The local PC polls the bridge via S3 every ~5s and writes back
    bridge/<task_id>_result.json. We wait up to max_wait seconds so the agent
    can receive the actual stdout/stderr in the same turn instead of "pending".
    """
    result_file = BRIDGE_PATH / f"{task_id}_result.json"
    waited = 0.0
    try:
        while waited < max_wait:
            if result_file.exists():
                try:
                    payload = json.loads(result_file.read_text())
                except json.JSONDecodeError:
                    payload = {"raw": result_file.read_text(errors="replace")}
                return {"tool": "bridge_result", "task_id": task_id,
                        "status": "completed", "result": payload}
            await asyncio.sleep(poll_interval)
            waited += poll_interval
        return {"tool": "bridge_result", "task_id": task_id,
                "status": "pending",
                "note": f"Kein Ergebnis nach {max_wait}s — der PC hat noch nicht "
                        f"geantwortet. Später nochmal bridge_result aufrufen."}
    except Exception as e:
        return {"tool": "bridge_result", "error": str(e)}


def tool_list_tools() -> dict:
    """List all registered tools (built-in + custom)."""
    builtin = [
        {"name": "web_search", "description": "Search the web via DuckDuckGo"},
        {"name": "fetch_url", "description": "Fetch and extract text from a URL"},
        {"name": "crypto_price", "description": "Get live crypto prices (CoinGecko)"},
        {"name": "crypto_trending", "description": "Get trending crypto coins"},
        {"name": "code_bridge", "description": "Write code tasks for local PC execution"},
        {"name": "bridge_result", "description": "Check result of a bridge task"},
        {"name": "register_tool", "description": "Register a new custom tool"},
        {"name": "list_tools", "description": "List all available tools"},
        {"name": "clear_memory", "description": "Clear session conversation memory"},
        {"name": "memory_stats", "description": "Show memory usage statistics"},
    ]
    registry = load_registry()
    custom = registry.get("tools", [])
    return {
        "tool": "list_tools",
        "builtin_count": len(builtin),
        "custom_count": len(custom),
        "builtin_tools": builtin,
        "custom_tools": custom,
    }


def tool_memory_stats(session_id: str = "") -> dict:
    """Return memory usage statistics."""
    sessions = list(MEMORY_PATH.glob("context_*.json"))
    stats = {
        "tool": "memory_stats",
        "total_sessions": len(sessions),
        "memory_window": MEMORY_WINDOW,
    }
    if session_id:
        history = load_memory(session_id)
        stats["current_session"] = {
            "session_id": session_id,
            "message_count": len(history),
        }
    return stats

# ── Tool Dispatcher ────────────────────────────────────────────────────────────

async def dispatch_tool(tool_call: dict, session_id: str = "", job_id: str = "") -> str:
    """Route a tool call to the appropriate function and return result as string."""
    tool = tool_call.get("tool", "")

    try:
        if tool == "web_search":
            result = await tool_web_search(
                query=tool_call.get("query", ""),
                max_results=tool_call.get("max_results", 5),
            )
        elif tool == "fetch_url":
            result = await tool_fetch_url(
                url=tool_call.get("url", ""),
                max_chars=tool_call.get("max_chars", 3000),
            )
        elif tool == "crypto_price":
            result = await tool_crypto_price(
                coins=tool_call.get("coins", "bitcoin,ethereum,solana"),
                currencies=tool_call.get("currencies", "usd,eur"),
            )
        elif tool == "crypto_trending":
            result = await tool_crypto_trending()
        elif tool == "code_bridge":
            result = await tool_code_bridge(
                code=tool_call.get("code", ""),
                language=tool_call.get("language", "python"),
                job_id=job_id,
                description=tool_call.get("description", ""),
            )
        elif tool == "bridge_result":
            result = await tool_bridge_result(tool_call.get("task_id", ""))
        elif tool == "register_tool":
            result = register_tool(
                name=tool_call.get("name", ""),
                description=tool_call.get("description", ""),
                endpoint=tool_call.get("endpoint", ""),
                schema=tool_call.get("schema"),
            )
        elif tool == "list_tools":
            result = tool_list_tools()
        elif tool == "clear_memory":
            sid = tool_call.get("session_id", session_id)
            success = clear_memory(sid)
            result = {"tool": "clear_memory", "session_id": sid, "success": success}
        elif tool == "memory_stats":
            result = tool_memory_stats(session_id)
        else:
            # Check custom tool registry
            registry = load_registry()
            custom = next((t for t in registry["tools"] if t["name"] == tool), None)
            if custom and custom.get("endpoint"):
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(custom["endpoint"], json=tool_call)
                        result = resp.json()
                except Exception as e:
                    result = {"error": f"Custom tool '{tool}' failed: {e}"}
            else:
                result = {"error": f"Unknown tool: '{tool}'. Use list_tools to see available tools."}

    except Exception as e:
        logger.exception(f"Tool '{tool}' raised an exception")
        result = {"tool": tool, "error": str(e)}

    return json.dumps(result, ensure_ascii=False)

# ── LLM Call ──────────────────────────────────────────────────────────────────

async def call_llm(messages: list[dict], max_tokens: int = 1024,
                   temperature: float = 0.7, stream: bool = False) -> str:
    """Send messages to llama-server and return the assistant reply."""
    payload = {
        "model": "ultron",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    try:
        # 300s: generous for large model under load; well within RunPod's job timeout
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{LLAMA_URL}/v1/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {LLAMA_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise

# ── Tool Call Parser ───────────────────────────────────────────────────────────

_TOOL_PATTERN = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)


def extract_tool_calls(text: str) -> list[dict]:
    """Extract all <tool_call>...</tool_call> blocks from LLM output."""
    calls = []
    for match in _TOOL_PATTERN.finditer(text):
        try:
            calls.append(json.loads(match.group(1).strip()))
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse tool call JSON: {e}\nRaw: {match.group(1)}")
    return calls


def strip_tool_calls(text: str) -> str:
    """Remove all tool call blocks from text."""
    return _TOOL_PATTERN.sub("", text).strip()

# ── Agentic Loop ──────────────────────────────────────────────────────────────

async def run_agent(user_message: str, session_id: str, job_id: str,
                    max_tokens: int = 1024, temperature: float = 0.7) -> dict:
    """
    Main agentic loop:
    1. Load memory
    2. Call LLM
    3. Parse tool calls
    4. Execute tools
    5. Loop with tool results
    6. Save memory and return final response
    """
    # Load conversation history
    history = load_memory(session_id)
    new_messages = []  # messages added this turn

    # Build initial message list
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    new_messages.append({"role": "user", "content": user_message})

    tool_iterations = 0
    final_response = ""
    tool_calls_log = []

    while tool_iterations <= MAX_TOOL_ITERATIONS:
        # Call the LLM
        logger.info(f"[{job_id}] LLM call #{tool_iterations + 1} | messages: {len(messages)}")
        assistant_reply = await call_llm(messages, max_tokens=max_tokens, temperature=temperature)

        # Check for tool calls
        calls = extract_tool_calls(assistant_reply)

        if not calls:
            # No tool calls — this is the final answer
            final_response = strip_tool_calls(assistant_reply)
            messages.append({"role": "assistant", "content": assistant_reply})
            new_messages.append({"role": "assistant", "content": assistant_reply})
            break

        # Execute all tool calls
        tool_results = []
        for call in calls:
            logger.info(f"[{job_id}] Executing tool: {call.get('tool')}")
            result_str = await dispatch_tool(call, session_id=session_id, job_id=job_id)
            tool_calls_log.append({"tool": call.get("tool"), "call": call})
            tool_results.append(f"Tool result for {call.get('tool')}:\n{result_str}")

        # Add assistant message and tool results to context
        messages.append({"role": "assistant", "content": assistant_reply})
        new_messages.append({"role": "assistant", "content": assistant_reply})

        tool_result_content = "\n\n".join(tool_results)
        tool_message = {"role": "user", "content": f"[Tool Results]\n{tool_result_content}\n\nPlease continue based on these results."}
        messages.append(tool_message)
        new_messages.append(tool_message)

        tool_iterations += 1

        if tool_iterations > MAX_TOOL_ITERATIONS:
            final_response = strip_tool_calls(assistant_reply) + "\n\n[Max tool iterations reached]"
            break

    # Save memory
    save_memory(session_id, new_messages)

    return {
        "response": final_response or strip_tool_calls(assistant_reply),
        "session_id": session_id,
        "tool_iterations": tool_iterations,
        "tools_used": [t["tool"] for t in tool_calls_log],
        "job_id": job_id,
    }

# ── RunPod Handler ─────────────────────────────────────────────────────────────

def _coerce_message(raw):
    """Normalize a user chat message into a plain string (handles str, list, dict)."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts = []
        for item in raw:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                content = item.get("content")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for segment in content:
                        if isinstance(segment, str):
                            parts.append(segment)
                        elif isinstance(segment, dict) and isinstance(segment.get("text"), str):
                            parts.append(segment["text"])
        return "\n".join(parts) if parts else str(raw)
    if isinstance(raw, dict):
        content = raw.get("content")
        if content is not None:
            return _coerce_message(content)
        return str(raw)
    return str(raw)


async def handler(job: dict) -> dict:
    """
    RunPod serverless entry point (async — RunPod SDK supports async handlers).
    Accepts job input and returns agent response.

    Expected input format:
    {
        "input": {
            "message": "Your question here",
            "session_id": "optional_session_id",
            "max_tokens": 1024,
            "temperature": 0.7,
            "payload": { ... }  // OpenAI-compatible alternative
        }
    }
    """
    job_id = job.get("id", f"job_{int(time.time())}")
    job_input = job.get("input", {})

    logger.info(f"[{job_id}] Received job")

    try:
        # Support both direct message and OpenAI-compatible payload
        if "payload" in job_input:
            # OpenAI-compatible mode: extract last user message
            payload = job_input["payload"]
            messages_list = payload.get("messages", [])
            user_message = ""
            for msg in reversed(messages_list):
                if msg.get("role") == "user":
                    user_message = _coerce_message(msg["content"])
                    break
            if not user_message:
                user_message = str(payload)
        elif "message" in job_input:
            user_message = _coerce_message(job_input["message"])
        else:
            return {"error": "No 'message' or 'payload' found in job input"}

        session_id = job_input.get("session_id", job_id)
        max_tokens = int(job_input.get("max_tokens", 1024))
        temperature = float(job_input.get("temperature", 0.7))

        # Fast no-op health ping — used by /wake command to pre-warm the worker.
        # Also handles the "warming_up" period: if the model isn't ready yet,
        # __health__ returns how far along the startup is.
        if user_message.strip() == "__health__":
            if MODEL_READY_FILE.exists():
                return {"response": "✅ ULTRON ist online und bereit.", "agent": AGENT_NAME}
            # Model still downloading — report progress
            model_file = Path(os.getenv("MODEL_PATH", "/runpod-volume/model")) / \
                         os.getenv("MODEL_FILENAME", "Qwen2.5-Coder-14B-Instruct-abliterated-Q4_K_M.gguf")
            downloaded_gb = round(model_file.stat().st_size / 1e9, 1) if model_file.exists() else 0
            return {
                "status": "warming_up",
                "message": f"⏳ Modell wird heruntergeladen... {downloaded_gb} GB / ~9 GB",
                "agent": AGENT_NAME,
            }

        # If llama-server isn't ready yet, return a warming-up response
        # instead of letting the job hang until it times out.
        if not MODEL_READY_FILE.exists():
            model_file = Path(os.getenv("MODEL_PATH", "/runpod-volume/model")) / \
                         os.getenv("MODEL_FILENAME", "Qwen2.5-Coder-14B-Instruct-abliterated-Q4_K_M.gguf")
            downloaded_gb = round(model_file.stat().st_size / 1e9, 1) if model_file.exists() else 0
            logger.info(f"[{job_id}] Model not ready yet ({downloaded_gb} GB downloaded) — returning warming_up")
            return {
                "status": "warming_up",
                "message": (
                    f"⏳ ULTRON startet kalt. Modell wird geladen ({downloaded_gb} GB / ~9 GB).\n"
                    "Bitte in 1–2 Minuten erneut versuchen."
                    if downloaded_gb > 0 else
                    "⏳ ULTRON startet kalt. Modell-Download beginnt gleich (~9 GB, ~10 Min).\n"
                    "Bitte später erneut versuchen oder /wake verwenden."
                ),
                "retry_after_seconds": 60,
                "agent": AGENT_NAME,
            }

        # Handle special actions directly (no LLM needed)
        action = job_input.get("action", "")
        if action == "list_tools":
            return tool_list_tools()
        elif action == "clear_memory":
            return {"success": clear_memory(session_id), "session_id": session_id}
        elif action == "memory_stats":
            return tool_memory_stats(session_id)
        elif action == "health":
            return {"status": "ok", "agent": AGENT_NAME}

        # Run the agentic loop — handler is async so we await directly
        result = await run_agent(
            user_message=user_message,
            session_id=session_id,
            job_id=job_id,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        logger.info(f"[{job_id}] Completed | tools_used: {result.get('tools_used')}")
        return result

    except Exception as e:
        logger.exception(f"[{job_id}] Handler error: {e}")
        return {"error": str(e), "job_id": job_id}


# ── RunPod Serverless Start — REQUIRED ────────────────────────────────────────
# RunPod scans for this call to verify serverless compatibility.
# Must be at module level, not inside if __name__ == "__main__"

runpod.serverless.start({"handler": handler})
