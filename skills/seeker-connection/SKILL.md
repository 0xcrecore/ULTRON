# Seeker Connection Skill

Monitor and control the Seeker (Solana Phone) via the **Termux bridge** (port 8471).

## 🧪 LIVE-TEST 01.08.2026 23:55 ✅

### Termux Bridge API (127.0.0.1:8471)
```
POST /exec  → {"cmd": "..."} → {success, stdout, stderr, error}
GET  /ping  → {"ok": true, "server": "SeekerServer", ...}
GET  /read  → ?file=/pfad → content
POST /write → {"file": "...", "text": "..."} → ok
```
- **Kein Auth** (localhost)
- Antwort heißt `success` / `stdout` / `stderr` (nicht `returncode`)
- **Diese Bridge ist auf diesem Seeker!** (`load average: 14.31` — hohe Last)

### PC Bridge API (192.168.178.67:7000)
```
POST /run → {"secret": process.env.BRIDGE_SECRET, "cmd": "...", "timeout": 15} → {returncode, stdout, stderr}
GET  /ping → {"bridge": "agent-bridge v2.0", "status": "online", ...}
```
- **Secret im JSON Body**, NICHT als Header
- Antwort heißt `returncode` / `stdout` / `stderr`

## Zugang über js_eval (KEIN fetch! Nur http module!)

```javascript
const http = require('http');
const termuxExec = (cmd) => new Promise((resolve) => {
  const data = JSON.stringify({cmd});
  const req = http.request({hostname: '127.0.0.1', port: 8471, path: '/exec', method: 'POST',
    headers: {'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data)},
    timeout: 15000
  }, res => { let b=''; res.on('data',c=>b+=c); res.on('end',()=>{ try{resolve(JSON.parse(b))}catch(e){resolve({error:'parse_failed',raw:b})} }); });
  req.on('error', e => resolve({error: e.message}));
  req.on('timeout', () => { req.destroy(); resolve({error: 'timeout'}); });
  req.write(data); req.end();
});
```

```
DU (node.js, SeekerClaw)
  │
  ├── 🏠 Termux Bridge (127.0.0.1:8471) ← IMMER hier durch für alles
  │     │                                     was Tailscale braucht
  │     ├── Poco (100.94.184.0:8475)
  │     └── PC (192.168.178.67:7000) via LAN
  │
  └── 🌐 web_fetch direkt zu PC via Tailscale (100.92.87.39:7000)
        (geht weil Seeker + PC beide im selben Tailscale-Netz)
```

**REGEL:** Du bist in node.js. Du hast:
- `web_fetch` → erreicht **PC direkt** (100.92.87.39 via Tailscale, 192.168.178.67 via LAN)
- KEIN direktes curl/fetch zu Tailscale-IPs außer PC — alles andere via Termux Bridge

---

## 📋 Geräte-IPs (aktuell)

| Gerät | Tailscale | LAN | Ports | Erreichbar von node.js |
|-------|-----------|-----|-------|----------------------|
| **PC** | 100.92.87.39 | 192.168.178.67 | 7000 (Bridge) | ✅ web_fetch (beide) |
| **Seeker** | 100.65.200.44 | 192.168.178.66 | 8471 (Termux) | ✅ localhost |
| **Poco** | 100.94.184.0 | — | 8475 (V3), 8083 (V2) | ❌ nur via Termux Bridge |

> ⚠️ **IPs ändern sich** bei Tailscale-Neuverbindung! Aktuelle IPs in MEMORY.md + Skills + Poco config.

---

## 🔧 Standard-Helper

```javascript
const http = require('http');
const bridge = (cmd, timeout=15) => new Promise((resolve) => {
  const data = JSON.stringify({cmd, timeout});
  const opts = { hostname:'127.0.0.1', port:8471, path:'/exec', method:'POST', timeout:timeout*1000+2000, headers: {'Content-Type':'application/json','Content-Length': Buffer.byteLength(data)} };
  const req = http.request(opts, res => { let body=''; res.on('data',c=>body+=c); res.on('end',()=>resolve(body)); });
  req.on('error', e => resolve('ERROR:'+e.message));
  req.on('timeout', () => { req.destroy(); resolve('TIMEOUT'); });
  req.write(data); req.end();
});
```

---

## ✅ PING (alle Geräte)

```javascript
// PC direkt per web_fetch (von node.js aus, via Tailscale oder LAN)
const pcTS = await web_fetch({url: 'http://100.92.87.39:7000/ping'}).catch(() => ({ok: false}));
const pcLAN = await web_fetch({url: 'http://192.168.178.67:7000/ping'}).catch(() => ({ok: false}));

// Poco via Termux Bridge
const pocoR = await bridge('curl -s --max-time 5 -u "Jarvis:Abc159753#" http://100.94.184.0:8475/ping 2>/dev/null || echo "OFFLINE"');

// Eigenes Termux
const seeker = await bridge('echo "OK"');
```

---

## 🖥️ PC BEFEHLE (direkt per web_fetch)

### Ping
```javascript
// Per Tailscale (bevorzugt — PC + Seeker sind im selben Tailscale-Netz)
const r = await web_fetch({url: 'http://100.92.87.39:7000/ping'});

// Per LAN (Fallback)
const r2 = await web_fetch({url: 'http://192.168.178.67:7000/ping'});
```

### Exec
```javascript
const r = await web_fetch({
  url: 'http://100.92.87.39:7000/run',
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({secret: process.env.BRIDGE_SECRET, cmd: 'uptime', timeout: 15})
});
// ⚠️ Secret im JSON Body! Kein X-Bridge-Secret Header! Antwort: { returncode: 0, stdout: "...", stderr: "" }
```

### PC Ausschalten
```javascript
// ⚠️ Secret im JSON Body, NICHT als Header!
await web_fetch({
  url: 'http://100.92.87.39:7000/run',
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({secret: process.env.BRIDGE_SECRET, cmd: 'shutdown -h now', timeout: 15})
});
```

### PC Einschalten (WoL)
```javascript
// Nutze pc-control Skill (hat WoL via Fritzbox UPnP implementiert)
const skill = await skill_read({name: 'pc-control'});
```

---

## 📱 POCO BEFEHLE (via Termux Bridge)

Alle Poco-Befehle gehen gleich — siehe **poco-connection Skill** für Details.

Struktur:
```javascript
const r = await bridge(`curl -s --max-time 8 -u "Jarvis:Abc159753#" \
  http://100.94.184.0:8475/exec \
  -X POST -H "Content-Type: application/json" \
  -d '{"cmd":"<befehl>"}' 2>/dev/null || echo 'POCO_OFFLINE'`);
```

### Ping
```javascript
const r = await bridge('curl -s --max-time 5 -u "Jarvis:Abc159753#" http://100.94.184.0:8475/ping 2>/dev/null || echo "POCO_OFFLINE"');
```

### File write (z.B. Config aktualisieren)
```javascript
const config = { targets: { pc: { tailscale_ip: "100.92.87.39", ... }, seeker: { ... } } };
const r = await bridge(`curl -s --max-time 8 -u "Jarvis:Abc159753#" \
  http://100.94.184.0:8475/write \
  -X POST -H "Content-Type: application/json" \
  -d '{"file":"/data/data/com.termux/files/home/pocoserver/config.json","text":${JSON.stringify(JSON.stringify(config, null, 2))}}' \
  2>/dev/null || echo 'POCO_OFFLINE'`);
```

---

## 🔄 NASHLÄUFIGE WORKFLOWS

### 1️⃣ Alle IPs aktualisieren (wenn Tailscale neu verbindet)

**Immer diese 4 Dateien updaten:**

1. **MEMORY.md** — `## Device IPs` section
2. **skills/poco-connection/SKILL.md** — Geräte-IPs Tabelle (oben)
3. **skills/seeker-connection/SKILL.md** — Geräte-IPs Tabelle (oben)
4. **Poco config.json** — per Bridge schreiben (Workflow 2)

### 2️⃣ Poco Config schreiben

```javascript
const config = {
  targets: {
    pc: { name: "HP EliteDesk", tailscale_ip: "100.92.87.39", bridge_port: 7000, type: "http_bridge" },
    seeker: { name: "Solana Seeker", tailscale_ip: "100.65.200.44", bridge_port: 8471, type: "http_bridge" }
  },
  last_updated: datetime(),
  notes: "Poco erreicht PC + Seeker per HTTP über Tailscale"
};

const r = await bridge(`curl -s --max-time 8 -u "Jarvis:Abc159753#" \
  http://100.94.184.0:8475/write \
  -X POST -H "Content-Type: application/json" \
  -d '{"file":"/data/data/com.termux/files/home/pocoserver/config.json","text":${JSON.stringify(JSON.stringify(config, null, 2))}}' \
  2>/dev/null || echo 'POCO_OFFLINE'`);
```

### 3️⃣ Von Poco aus PC anpingen (unterwegs)

```javascript
const r = await bridge(`curl -s --max-time 8 -u "Jarvis:Abc159753#" \
  http://100.94.184.0:8475/exec \
  -X POST -H "Content-Type: application/json" \
  -d '{"cmd":"curl -s --max-time 5 http://100.92.87.39:7000/ping 2>/dev/null || echo PC_OFFLINE"}' \
  2>/dev/null || echo 'POCO_OFFLINE'`);
```

### 4️⃣ Ophanim Status checken (auf Seeker Termux)

```javascript
const data = await f('ls ~/ophanim-server/data/ 2>/dev/null | wc -l');
const lastPost = await f('cat ~/ophanim-server/last_post_time.txt 2>/dev/null || echo "no_file"');
```

---

## ⚠️ Error Handling

| Symptom | Grund | Lösung |
|---------|-------|--------|
| ECONNREFUSED (8471) | Termux bridge down | PM2 auf Seeker Termux neustarten |
| PC Timeout (LAN) | PC aus | WoL via Fritzbox |
| PC Timeout (Tailscale) | Tailscale down | LAN-IP probieren |
| POCO_OFFLINE | Deep Sleep | Normal, wacht bei Nutzung auf |
| Bridge empty stdout | falscher BRIDGE_SECRET | Env Var prüfen |

---

## 💡 Prinzipien

- **PC direkt per web_fetch** (Tailscale oder LAN) — kein Umweg nötig
- **Poco immer via Termux Bridge** (8471) — node.js hat kein direktes curl zu Tailscale-IPs
- Bei IP-Änderung: **4 Dateien updaten** (MEMORY.md + beide Skills + Poco config)
- Poco ist **nur Tailscale** — keine LAN-Verbindung
- BRIDGE_SECRET aus env (nicht hardcoded)