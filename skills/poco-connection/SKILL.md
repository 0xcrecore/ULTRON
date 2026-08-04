---
name: "poco-connection"
version: "2.2.1"
description: "Poco X7 Connection Skill"
emojis: "📱"
---

# Poco X7 Connection Skill

Monitor and control the **Poco X7** phone via **Termux Bridge** (127.0.0.1:8471) or **direct Tailscale** (100.94.184.0:8475).

## 🔴 LIVE-TEST 01.08.2026 23:55 — ALLES FUNKTIONIERT ✅

### Termux Bridge API (127.0.0.1:8471)
```
POST /exec  → {"cmd": "..."} → {success, stdout, stderr, error}
GET  /ping  → {"ok": true, "server": "SeekerServer", ...}
GET  /read  → ?file=/pfad → content
POST /write → {"file": "...", "text": "..."} → ok
```
- **Kein Auth** (localhost)
- Antwort heißt `success` / `stdout` / `stderr`
- **Seeker CPU load: ~14** (ziemlich hoch)

### PC Bridge API (192.168.178.67:7000)
```
POST /run → {"secret": <BRIDGE_SECRET>, "cmd": "...", "timeout": 15} → {returncode, stdout, stderr}
GET  /ping → {"bridge": "agent-bridge v2.0", "status": "online", ...}
```
- **Secret im JSON Body**, NICHT als Header ❌
- Antwort heißt `returncode` (nicht `exitCode`)
- Von node.js aus via `web_fetch` oder per `curl` via Termux Bridge

### Poco V3 Bridge API (100.94.184.0:8475)
```
GET  /ping → {"ok": true, "server": "PocoServer", ...}
POST /exec → (ungetestet)
```
- Basic Auth: `Jarvis:Abc159753#`
- Von node.js aus direkt via `web_fetch` (Tailscale) ODER via Termux Bridge

---

## 🔌 Zugang über js_eval (WICHTIG)

In `js_eval` gibt es **KEIN** `fetch()` — nur `require('http')` für lokale/localhost-Verbindungen!
Für entfernte Geräte (PC, Poco) funktioniert der Tool `web_fetch` direkt.

```javascript
// Termux Bridge Exec (localhost — nur in js_eval!)
const http = require('http');
const termuxExec = (cmd) => new Promise(resolve => {
  const data = JSON.stringify({cmd});
  const opts = {hostname:'127.0.0.1',port:8471,path:'/exec',method:'POST',
    headers:{'Content-Type':'application/json','Content-Length':Buffer.byteLength(data)},timeout:15000};
  const req = http.request(opts, res => { let b=''; res.on('data',c=>b+=c); res.on('end',()=>{ try{resolve(JSON.parse(b))}catch(e){resolve({error:'parse_failed',raw:b})} }); });
  req.on('error', e => resolve({error: e.message}));
  req.on('timeout', () => { req.destroy(); resolve({error: 'timeout'}); });
  req.write(data); req.end();
});
```

---

## ✅ PING (alle Geräte)

```javascript
// Alle 3 Geräte in einem Aufruf
const [pcStatus, pocoStatus, seekerSelf] = await Promise.all([
  web_fetch({url:'http://192.168.178.67:7000/ping'}).then(r=>r).catch(e=>({error:e.message})),
  web_fetch({url:'http://100.94.184.0:8475/ping'}).then(r=>r).catch(e=>({error:e.message})),
  Promise.resolve("OK")
]);
```

---

## 📱 POCO BEFEHLE

### Ping (direkt via web_fetch)
```javascript
const r = await web_fetch({url:'http://100.94.184.0:8475/ping'});
// {"ok":true,"server":"PocoServer","hostname":"localhost","time":"..."}
```

### Ping (via Termux Bridge)
```javascript
// Nutze termuxExec() aus dem Helper oben
const r = await termuxExec('curl -s --max-time 5 http://100.94.184.0:8475/ping 2>/dev/null || echo "OFFLINE"');
```

### Exec via Termux Bridge
```javascript
const r = await termuxExec(`curl -s --max-time 8 -u "Jarvis:Abc159753#" \
  http://100.94.184.0:8475/exec \
  -X POST -H "Content-Type: application/json" \
  -d '{"cmd":"<befehl>"}' 2>/dev/null || echo 'POCO_OFFLINE'`);
```

### Exec via web_fetch (direkt)
```javascript
const r = await web_fetch({
  url: 'http://100.94.184.0:8475/exec',
  method: 'POST',
  headers: {'Content-Type': 'application/json', 'Authorization': 'Basic ' + Buffer.from('Jarvis:Abc159753#').toString('base64')},
  body: JSON.stringify({cmd: 'uptime'})
});
```

---

## 🖥️ PC BEFEHLE (vom Seeker aus)

### Ping (direkt via web_fetch)
```javascript
const r = await web_fetch({url:'http://192.168.178.67:7000/ping'});
// {"bridge":"agent-bridge v2.0","status":"online","hostname":"curl-HP-EliteDesk-800-G2-DM-65W",...}
```

### Run Command (direkt via web_fetch)
```javascript
// ⚠️ Secret im JSON Body, NICHT als Header!
const r = await web_fetch({
  url: 'http://192.168.178.67:7000/run',
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({secret: process.env.BRIDGE_SECRET, cmd: 'uptime', timeout: 15})
});
// { returncode: 0, stdout: "...", stderr: "" }
```

### Run Command (via Termux Bridge → curl)
```javascript
const r = await termuxExec(`curl -s -X POST http://192.168.178.67:7000/run \
  -H 'Content-Type: application/json' \
  -d '{"secret":"'$BRIDGE_SECRET'","cmd":"uptime","timeout":15}' \
  2>/dev/null || echo 'PC_OFFLINE'`);
```

### PC Einschalten (WoL)
→ Nutze den **pc-control** Skill (hat WoL + Fritzbox UPnP implementiert)

### PC Ausschalten
```javascript
const r = await web_fetch({
  url: 'http://192.168.178.67:7000/run',
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({secret: process.env.BRIDGE_SECRET, cmd: 'shutdown -h now', timeout: 15})
});
```

---

## ⚠️ Error Handling

| Symptom | Grund | Lösung |
|---------|-------|--------|
| POCO_OFFLINE | Deep Sleep (nachts/inaktiv) | Normal, wacht bei Nutzung auf |
| ECONNREFUSED (8471) | Termux tot | PM2 auf Seeker neustarten |
| Bridge timeout | Tailscale tot / IP geändert | Neue IP rausfinden, überall updaten |
| Poco 403/401 | Auth falsch | V3: Basic `Jarvis:Abc159753#` |
| web_fetch parse fail | Bridge antwortet Nicht-JSON | Raw response checken |

---

## 🔗 IP-Tabelle

| Gerät | Tailscale | LAN | Ports |
|-------|-----------|-----|-------|
| **Poco** | 100.94.184.0 | — | 8475 (V3), 8083 (V2) |
| **PC** | 100.92.87.39 | 192.168.178.67 | 7000 (Bridge) |
| **Seeker** | 100.65.200.44 | — | 8471 (Termux) |

> ⚠️ Tailscale-IPs ändern sich bei Neuverbindung. Bei Fehlern zuerst alle pingen.

---

## 💡 Prinzipien

- **Poco direkt per web_fetch** (Tailscale 100.94.184.0:8475) — schnellster Weg
- **Poco via Termux Bridge** — Backup (dauert länger, aber zuverlässiger)
- **PC per web_fetch** (LAN oder Tailscale) direkt
- **js_eval** für lokale Termux-Bridge-Zugriffe (dort KEIN fetch(), nur require('http'))
- **In Skills/Telegram-Replies** immer `web_fetch` verwenden (das geht da)