---
name: "pc-control"
version: "2.2.0"
description: "Control the home Mini PC (HP EliteDesk 800 G2, Linux Mint) via HTTP bridge. Use when: user says 'run on PC', 'PC online?', 'PC-Status', 'check server', 'Führe X auf dem PC aus', 'zeig mir Speicher', 'starte Dienst neu', 'PC einschalten', 'wake PC', 'starte PC', 'PC starten', 'PC booten', or wants to execute any command / manage files on the home machine."
metadata:
  openclaw:
    emoji: "🖥️"
    requires:
      bins: []
      env:
        - BRIDGE_SECRET
        - MAC_PC
---

# PC Control Skill

Control the home Mini PC via **Fritzbox WoL** (wake on LAN) + **HTTP bridge** (port 7000).

## 🔴 VERIFIED: Live Test 01.08.2026 23:52

### Auth (wie es WIRKLICH funktioniert)
- ✅ **`secret` im JSON Body** — `{"secret": "<BRIDGE_SECRET>", "cmd": "uptime", "timeout": 8}`
- ❌ X-Bridge-Secret Header — funktioniert NICHT
- ❌ Basic Auth — funktioniert NICHT
- ❌ Bearer Token — funktioniert NICHT
- ❌ `fetch()` — gibt es in js_eval NICHT! Immer `require('http')` verwenden.

### Response Format
```json
{
  "returncode": 0,    // ⚠️ NICHT "exitCode"!
  "stdout": "...",
  "stderr": ""
}
```

### Verfügbare Endpoints
| Path | Methode | Auth | Antwort |
|------|---------|------|---------|
| `/ping` | GET | Keine | `{"bridge":"agent-bridge v2.0","hostname":"...","status":"online","uptime":"49h..."}` |
| `/run` | POST | Secret im JSON Body | `{"returncode":0,"stdout":"..."}` |
| `/skills` | GET | Keine | Liste aller PC-Skills |
| `/` | ANY | — | 404 |

## Hardware Reference

| Property         | Value                             |
|------------------|-----------------------------------|
| Model            | HP EliteDesk 800 G2 DM 65W       |
| CPU              | Intel Core i7-6700 @ 3.4 GHz     |
| RAM              | 16 GB DDR4                        |
| OS               | Linux Mint XFCE                   |
| Local IP         | 192.168.178.67                    |
| Tailscale IP     | 100.92.87.39                      |
| Bridge (LAN)     | http://192.168.178.67:7000        |
| Bridge (Tail)    | http://100.92.87.39:7000          |
| MAC              | `MAC_PC` env var                  |
| Router           | Fritzbox (192.168.178.1:49000)    |
| Skills           | /server/home/skills/              |
| Logs             | /server/home/logs/bridge.log      |

## Decision Flow

```
User wants something from PC
         │
         ▼
    pingPC() ─── online ──▶ runPC()  →  return stdout
         │
      offline
         │
         ▼
   WoL via Fritzbox UPnP (192.168.178.1:49000)
   → wait 35s
   → pingPC() ─── online ──▶ runPC()
         │
      still offline
         │
         ▼
   Tell user: PC antwortet nicht — bitte physisch prüfen
```

## Standard-Helper (für ALLE js_eval Aufrufe nutzen)

```javascript
const http = require('http');

// PC ping
const pingPC = (host='192.168.178.67') => new Promise((resolve) => {
  const req = http.get(`http://${host}:7000/ping`, {timeout: 5000}, res => {
    let data = '';
    res.on('data', c => data += c);
    res.on('end', () => { try { resolve(JSON.parse(data)); } catch(e) { resolve({error: 'parse_failed'}); } });
  });
  req.on('error', e => resolve({error: e.message}));
  req.on('timeout', () => { req.destroy(); resolve({error: 'timeout'}); });
});

// PC run command (secret im JSON Body! Kein Header!)
const runPC = (cmd, host='192.168.178.67', timeout=15) => new Promise((resolve) => {
  const data = JSON.stringify({secret: process.env.BRIDGE_SECRET, cmd, timeout});
  const opts = {
    hostname: host, port: 7000, path: '/run', method: 'POST',
    headers: {'Content-Type':'application/json','Content-Length': Buffer.byteLength(data)},
    timeout: (timeout+3)*1000
  };
  const req = http.request(opts, res => {
    let b=''; res.on('data',c=>b+=c);
    res.on('end',()=>{ try { resolve(JSON.parse(b)); } catch(e) { resolve({returncode: -1, stderr: b}); }});
  });
  req.on('error', e => resolve({returncode: -1, stderr: e.message}));
  req.on('timeout', () => { req.destroy(); resolve({returncode: -1, stderr: 'timeout'}); });
  req.write(data); req.end();
});
```

### Usage Examples

```javascript
// Check if PC is online
const status = await pingPC();
if (status.error) console.log('PC: ❌ OFFLINE');
else console.log(`PC: ✅ ONLINE (${status.uptime})`);

// Run a command
const r = await runPC('uptime && free -h');
if (r.returncode === 0) console.log(r.stdout);
else console.error(`Exit ${r.returncode}: ${r.stderr}`);

// On Tailscale
const ts = await pingPC('100.92.87.39');
console.log('Tailscale:', ts.error ? '❌' : '✅', ts.uptime||'');
```

## WoL via Fritzbox

```javascript
const http = require('http');
const mac = process.env.MAC_PC;

const soapBody = `<?xml version="1.0"?>
<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:X_AVM-DE_WakeOnLANByMACAddress xmlns:u="urn:dslforum-org:service:Hosts:1">
      <NewMACAddress>${mac}</NewMACAddress>
    </u:X_AVM-DE_WakeOnLANByMACAddress>
  </s:Body>
</s:Envelope>`;

const result = await new Promise((resolve) => {
  const req = http.request({
    hostname: '192.168.178.1', port: 49000, path: '/upnp/control/hosts',
    method: 'POST', timeout: 5000,
    headers: {
      'Content-Type': 'text/xml; charset="utf-8"',
      'SOAPAction': 'urn:dslforum-org:service:Hosts:1#X_AVM-DE_WakeOnLANByMACAddress',
      'Content-Length': Buffer.byteLength(soapBody)
    }
  }, (res) => { res.resume(); res.on('end', () => resolve({ status: res.statusCode })); });
  req.on('error', (e) => resolve({ error: e.message }));
  req.on('timeout', () => { req.destroy(); resolve({ error: 'timeout' }); });
  req.write(soapBody);
  req.end();
});

console.log('WoL:', result.status === 200 ? '✅' : '❌', result);
```

## Full Flow: Ping → WoL (falls offline) → Execute

```javascript
const http = require('http');
const SECRET = process.env.BRIDGE_SECRET;
const MAC = process.env.MAC_PC;

// Helpers
const pingPC = (host='192.168.178.67') => new Promise((resolve) => {
  const req = http.get(`http://${host}:7000/ping`, {timeout: 5000}, res => {
    let data=''; res.on('data',c=>data+=c);
    res.on('end',()=>{ try { resolve(JSON.parse(data)); } catch(e) { resolve({error:'parse'}); } });
  });
  req.on('error', e => resolve({error: e.message}));
  req.on('timeout', () => { req.destroy(); resolve({error: 'timeout'}); });
});

const wol = () => new Promise((resolve) => {
  const soapBody = `<?xml version="1.0"?>
<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:X_AVM-DE_WakeOnLANByMACAddress xmlns:u="urn:dslforum-org:service:Hosts:1">
      <NewMACAddress>${MAC}</NewMACAddress>
    </u:X_AVM-DE_WakeOnLANByMACAddress>
  </s:Body>
</s:Envelope>`;
  const req = http.request({
    hostname:'192.168.178.1', port:49000, path:'/upnp/control/hosts',
    method:'POST', timeout:5000,
    headers:{'Content-Type':'text/xml; charset="utf-8"', 'SOAPAction':'urn:dslforum-org:service:Hosts:1#X_AVM-DE_WakeOnLANByMACAddress','Content-Length':Buffer.byteLength(soapBody)}
  }, (res) => { res.resume(); res.on('end',()=>resolve(true)); });
  req.on('error',()=>resolve(false)); req.on('timeout',()=>{req.destroy();resolve(false)});
  req.write(soapBody); req.end();
});

const runPC = (cmd, host='192.168.178.67', timeout=15) => new Promise((resolve) => {
  const data = JSON.stringify({secret:SECRET, cmd, timeout});
  const opts = { hostname:host, port:7000, path:'/run', method:'POST',
    headers:{'Content-Type':'application/json','Content-Length':Buffer.byteLength(data)},
    timeout:(timeout+3)*1000 };
  const req = http.request(opts, res=>{let b='';res.on('data',c=>b+=c);res.on('end',()=>{try{resolve(JSON.parse(b))}catch(e){resolve({returncode:-1,stderr:b})}})});
  req.on('error', e => resolve({returncode:-1,stderr:e.message}));
  req.on('timeout', ()=>{req.destroy();resolve({returncode:-1,stderr:'timeout'})});
  req.write(data); req.end();
});

// === FULL FLOW ===
const host = '192.168.178.67';
let pong = await pingPC(host);
if (!pong.error) {
  console.log(`PC ✅ ONLINE (${pong.uptime})`);
  const result = await runPC('uptime && free -h');
  console.log(result.returncode === 0 ? result.stdout : `ERR: ${result.stderr}`);
} else {
  console.log('PC offline → WoL...');
  await wol();
  console.log('Warte 35s...');
  await new Promise(r => setTimeout(r, 35000));
  pong = await pingPC(host);
  if (pong.error) {
    console.log('PC ❌ immer noch offline — bitte physisch prüfen');
  } else {
    const result = await runPC('df -h /server && free -h');
    console.log(result.returncode === 0 ? result.stdout : `ERR: ${result.stderr}`);
    // NACH ERLEDIGUNG PC WIEDER AUSSCHALTEN (außer User sagt was anderes)
    const off = await runPC('shutdown -h now');
    console.log('PC ausgeschaltet:', off.returncode === 0 ? '✅' : '⚠️');
  }
}
```

## Common Commands

```bash
# Status
uptime && free -h && df -h /server
ps aux --sort=-%cpu | head -15

# Bridge
systemctl status agent-bridge
systemctl restart agent-bridge
tail -50 /server/home/logs/bridge.log

# Audio (PulseAudio — user session prefix nötig)
PULSE_SERVER=unix:/run/user/1000/pulse/native pactl set-sink-volume @DEFAULT_SINK@ 60%

# PC ausschalten
shutdown -h now
```

## Error Handling

| Symptom              | Cause                   | Fix                                              |
|----------------------|-------------------------|--------------------------------------------------|
| Timeout/ECONNREFUSED | PC offline              | WoL via Fritzbox → wait 35s → retry              |
| WoL OK, kein Ping    | PC kalt, BIOS WoL aus   | BIOS → Power → Wake On LAN = Enabled             |
| HTTP 403/unauthorized | Falscher/fehlender Secret | Secret im JSON Body senden, nicht als Header!   |
| `returncode: 1`      | Command failed          | `stderr` Feld lesen                              |
| `returncode: 124`    | Timeout zu kurz         | `timeout` erhöhen oder `nohup cmd &`             |

## Wichtige Regeln (aus SOUL.md)

- **PC ist TABU** ohne explizite Aufforderung + Zustimmung
- Erst prüfen ob alles API-basiert geht (Seeker Node.js!)
- Nur wenn es **wirklich nicht anders geht**, PC anmachen
- **Nach Erledigung sofort ausschalten**, außer User sagt was anderes

## Cross-Device Connectivity

| From | URL |
|------|-----|
| Seeker (local) | `http://192.168.178.67:7000` or `http://100.92.87.39:7000` |
| Poco X7 (Tailscale) | `http://100.92.87.39:7000` |
| External (Tailscale) | `http://100.92.87.39:7000` |