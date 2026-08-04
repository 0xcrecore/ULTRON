---
name: ophanim-userbot
description: Telegram Userbot (Ophanim) — überwacht Solana-Quellkanäle, sammelt Tokendaten und postet Einzel-Analysen in die Degen Lab Sol Gruppe. Kein PC — alles API-basiert auf dem Seeker Node.js.
emoji: 🤖
triggers:
  - ophanim
  - userbot
  - post token
  - post news
  - post wallets
  - send to group
  - degen lab
  - post jetzt
requires:
  env:
    - OPHANIM_API_ID
    - OPHANIM_HASH
    - OPHANIM_SESSION
    - BIRDEYE_API_KEY
  tools:
    - web_search
    - web_fetch
    - js_eval
    - cron_create
    - cron_list
    - cron_cancel
    - telegram_send
---

# Ophanim Userbot Skill

## Überblick
Ophanim ist ein **Telegram Userbot** zur Solana-Marktanalyse und zum Posten in die **Degen Lab Sol Gruppe** (`-1002358673313`).

**Wichtig: Ophanim ist nur ein Werkzeug, kein autonomer Bot.**
Der Agent (Jarvis) analysiert, filtert und gibt grün.
**Betrieb:** Rein API-basiert auf dem Seeker Node.js (KEIN PC!)
**Verbindung:** Telethon über env `OPHANIM_API_ID`, `OPHANIM_HASH`, `OPHANIM_SESSION`

---

## Posting-Plan (täglich)

### Früh/Start: News + Wallets auf einmal
**1 News-Post** (Solana Ökosystem + Solana Seeker News)
**1 Winrate-Wallet-Post** (gesammelt, mehrere Wallets in einem Post)

### Über den Tag verteilt: 5 Token-Posts (einzeln)
Die Top-5-Token des Tages — aber **nicht sofort posten**:
1. Tokens über den Tag sammeln & analysieren
2. **Rug-Check abwarten** (genug Liquidität, kein Dump, Community vorhanden)
3. Nur posten wenn **safe** — Usecase + Community checken
4. Über den Tag verteilt einzeln posten

---

## Post-Formate

### 1. News-Post (1x täglich, gesammelt)
```
📰 Solana Daily — [Datum]

• Headline 1 — Kurzanalyse
• Headline 2 — Kurzanalyse
• Headline 3 — Kurzanalyse

🪙 Solana Seeker: [Seeker-relevante News]

#Solana #DegenLab
```

### 2. Winrate-Wallet-Post (1x täglich, gesammelt)
```
🐋 Top Winrate Wallets — [Datum]

1. WalletAddress
   🏆 94% Winrate | 63 Trades | $3.20 avg
   📅 Aktiv seit 3 Monaten — Insider-Prio

2. WalletAddress
   🏆 91% Winrate | 47 Trades | $2.80 avg
   📅 Aktiv seit 2 Monaten — Fokussiert (24 Tokens)

3. WalletAddress
   🏆 93% Winrate | 38 Trades | $4.10 avg
   📅 Aktiv seit 2.5 Monaten — Frühe Käufe

Budget je Wallet: $2-5 pro Trade empfohlen
```

**Wallet-Filter:**
- Winrate **90%+**
- **Lang aktiv** (2+ Monate, keine Dust-Wallets)
- **Fokussiert** (max ~50-100 Tokens gekauft, kein Massenspam)
- **Insider Priority** — frühe Käufe, hohe Trefferquote

### 3. Token-Post (einzehn, 5x über den Tag)
```
🚀 $TOKEN — Lowcap Gem

📊 Price: $X.XX | MC: $X,XXX
💧 Liquidity: $XX,XXX
👥 Community: [Telegram/Discord aktiv?]
🎯 Usecase: [Kurzbeschreibung]

🔗 CA: ContractAddress
🔍 DexScreener: https://dexscreener.com/solana/PAIR_ADDRESS

🏆 Geprüft — sicher, frühe Phase, aktive Community
```

**Token-Auswahl (streng):**
- **Chain:** Solana ONLY
- **Liquidität:** > $10K
- **MC:** Unter $5M (frühe Phase)
- **Rug-Check bestanden:** Mint Authority revoked ✅ / Freeze Authority revoked ✅ / LP gebrannt ✅
- **Usecase:** Nicht nur Meme — Community + Nutzen vorhanden
- **Organic Volume:** Kein Wash-Trading
- **Warte ab:** Token über den Tag beobachten — erst posten wenn kein Dump/Massenverkauf
- **Nur Top 5 des Tages** — die absolut besten & sichersten

---

## Workflow (im Detail)

### 1. Tokens sammeln (über den Tag)
- DexScreener API: `/token-profiles/latest/v1` → neueste Solana Token
- Source Chats per Userbot auslesen
- Merken in Memory (keine Duplikate)

### 2. Analyse & Rug-Check
- **Jupiter Security Check:** Mint/Freeze Authority, organicScore, isSus
- **Liquidität checken:** > $10K?
- **Community checken:** Telegram/Discord aktiv?
- **Usecase checken:** Was macht das Token?
- **Beobachten:** Preisverhalten über Stunden — kein Dump?
- Nur die **Top 5 absolut besten** kommen durch

### 3. Posten
- Einzeln über den Tag verteilt
- 30min+ Abstand zwischen Posts (max 5/Tag)
- Per Telethon API an die Gruppe
- Jeder Post einzeln (keine Batches)

### 4. Winrate Wallets (1x täglich)
- Birdeye API / Helius RPC: Wallet-Historie analysieren
- Filter: 90%+ Winrate, lang aktiv, fokussiert
- Top 3-5 Wallets sammeln in einem Post

### 5. News (1x täglich)
- Solana Ökosystem News + Solana Seeker News
- Ein Post, gesammelt

---

## Cron-Konfiguration
Tägliche Postings über den Tag verteilt:
- **10:00 UTC** — News + Winrate Wallets (zusammen)
- **12:00 UTC** — Token #1
- **14:00 UTC** — Token #2
- **16:00 UTC** — Token #3
- **18:00 UTC** — Token #4
- **20:00 UTC** — Token #5

Agent analysiert & filtert Tokens laufend — wartet mit Posten bis Rug-Check sicher ist.

## Verworfene Lösungen
- ❌ PC-Bridge (zu umständlich, User will nicht)
- ❌ Bot in Gruppe (Bot nicht in Zielgruppe → Userbot only)
- ❌ Batch-Posts (einzeln posten)
- ❌ Zu frühes Posten (erst beobachten, dann posten)