---
name: autonomous-workflow
description: Begrenzte autonome Programmier- und Build-Workflows mit Telegram-Unterbrechung.
version: 1.2.0
triggers:
  - autonom arbeiten
  - autonomer workflow
  - programmierauftrag ausführen
  - im loop arbeiten
  - workflow unterbrechen
  - ohne nachfragen fertig bauen
---

# Autonomous Workflow

## Zweck
Bounded, checkpoint-basierte und jederzeit unterbrechbare Workflows für Programmierung, Builds, Monitoring und Automatisierung.

## Dauerhafte Nutzerpräferenzen
- Mr. Stark erteilt Start, Resume und Abbruch.
- Neue Telegram-Nachrichten haben sofort Vorrang und unterbrechen an der nächsten sicheren Grenze.
- Maximal 100 Schritte pro Workflow.
- Kein zweiter Telegram-Poller und keine zweite Telethon-Control-Schleife.
- `/server/ophanim` enthält ausschließlich Ophanim-Dateien.
- `/server/website` bleibt unverändert.
- PC nur bei explizitem Auftrag und Zustimmung; zuerst API-/Seeker-Lösungen verwenden.
- Keine Platzhalter oder unbestätigte öffentliche Posts.
- Keine Credentials, Tokens oder Wallet-Key-Material in Logs, Checkpoints oder Antworten.
- Keine Umgehung von Bestätigungen, Wallet-Policies, Berechtigungen oder Interrupts.

## Ausführung
1. Auftrag in höchstens 100 nummerierte Schritte zerlegen.
2. Für lange Aufträge `workflow-state.json` und redigiertes `workflow.log` verwenden.
3. Vor jedem consequential Schritt auf neue Owner-Nachrichten prüfen.
4. Nach jedem größeren Schritt verifizieren und checkpointen.
5. Bei Unterbrechung sofort speichern und stoppen; nicht automatisch fortsetzen.
6. Nach Resume exakt am letzten verifizierten Schritt weitermachen.
7. Abschluss mit erledigten, übersprungenen und offenen Schritten melden.

Jeder Schritt besitzt mindestens `id`, `description`, `status`, Zeitstempel und eine kurze Notiz. Statuswerte: `pending`, `running`, `done`, `failed`, `skipped`, `cancelled`.

## Grenzen und Ressourcen
- Keine unbounded Schleifen, kein Busy-Polling und kein zweiter Message-Listener.
- Wiederkehrende Checks über SeekerClaw-Cron oder systemd-Timer.
- Für längere Prozesse: detached/asynchron starten, PID/Checkpoint/Fortschritt/Fehler loggen und Status-/Cancel-Pfad anbieten.
- Hohe, aber endliche Timeouts nutzen; Host- und Tool-Limits bleiben maßgeblich.
- Keine blinden Wiederholungen nach Timeout oder Fehler; erst Status und Logs prüfen.

## Friday-Profil
Für lokale kleine Modelle bevorzugt:
- Kontext 4096 Tokens
- Reasoning-Budget 256–512
- moderate Batch-/Micro-Batch-Werte
- begrenzte CPU-Threads
- `mlock=false`, sofern kein Stabilitätsgrund dagegen spricht
- Konfigurationsbackup vor Änderungen
- RAM und Antwortqualität nach Änderungen prüfen

## Ophanim-Pipeline
`Collector → Friday Analyse/Filter → Controller Status/Fehler → Ophanim Poster`

Friday analysiert, filtert und priorisiert. Der Poster prüft vor Veröffentlichung Quelle, Qualität, Sicherheit, Duplikate, Tageslimit, Mindestabstand und FloodWait. Statusmeldungen werden nur bei Fehlern, Recovery oder relevanten Zustandsänderungen gesendet.

## PC-Konvention
- Root: `/server`
- Skill-Ordner: `/server/<skill>/`
- Ophanim-only: `/server/ophanim/`
- Website: `/server/website/`, nicht verändern
- Nach temporärem PC-Einsatz wieder ausschalten, außer Mr. Stark ordnet es anders an.

## Sicherheitsstopps
Stoppen und fragen bei Fundbewegungen, Nachrichten/Anrufen, destruktiven Änderungen, Credential-/Key-Handhabung, unklarer Veröffentlichung oder PC-Einschalten ohne ausdrückliche Freigabe.

## Completion Report
Kurz melden: Service-Status, erledigte Schritte, Checkpoint-Pfad, Ressourcenprofil, offene Risiken und ob tatsächlich veröffentlicht wurde.

## Version / Changelog
- 1.2.0: Dauerhafte Mr.-Stark-Präferenzen, Task-Loop-, Friday-, Ophanim- und PC-Regeln vereinheitlicht.
- 1.1.1: Asynchroner Fallback für längere Operationen ergänzt.
- 1.1.0: Endliche Timeouts, Checkpoints und resumierbare Transfers ergänzt.
- 1.0.0: Initiale bounded Workflow-Policy.
