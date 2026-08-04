"""
ULTRON — Health Shim
=====================
Leichter HTTP-Server auf PORT_HEALTH (Standard 8001).
RunPod / externe Monitore fragen /ping ab; wir übersetzen das zu einem
Check gegen den lokalen llama-server /health Endpoint.

Nur Standardbibliothek — kein zusätzliches Dependency-Gewicht im Cold-Start.
"""

import os
import sys
import json
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT_HEALTH = int(os.environ.get("PORT_HEALTH", "8001"))
LLAMA_PORT = os.environ.get("LLAMA_PORT", os.environ.get("PORT", "8000"))
LLAMA_HEALTH_URL = f"http://127.0.0.1:{LLAMA_PORT}/health"


class PingHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence default noisy logging
        pass

    def do_GET(self):
        if self.path not in ("/ping", "/"):
            self.send_response(404)
            self.end_headers()
            return

        try:
            with urllib.request.urlopen(LLAMA_HEALTH_URL, timeout=5) as resp:
                ok = resp.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            ok = False

        body = json.dumps({"status": "ok" if ok else "starting"}).encode()
        self.send_response(200 if ok else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT_HEALTH), PingHandler)
    print(f"[ULTRON] Health-Shim gestartet auf Port {PORT_HEALTH} -> {LLAMA_HEALTH_URL}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
