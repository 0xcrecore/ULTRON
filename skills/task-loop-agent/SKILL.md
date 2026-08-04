---
name: task-loop-agent
description: Bounded Task-Loop Agent für fortsetzbare Programmier-, Build-, Monitoring- und Automationsaufträge mit Telegram-Unterbrechung, Checkpoints, minimalem RAM-Verbrauch und sicherer PC-/Service-Steuerung.
version: 1.0.0
triggers:
  - Task Loop
  - Tasks Loop
  - Workflow starten
  - arbeite die Tasks ab
  - autonomer Workflow
  - dauerhaft überwachen
  - Script kontrollieren
  - Logs überwachen
---

# Task-Loop-Agent

## Zweck
Dieser Skill steuert längere Aufgaben in kleinen, nachvollziehbaren Schritten. Er ist bounded, fortsetzbar, beobachtbar und jederzeit durch eine neue Telegram-Nachricht unterbrechbar.

## Dauerhafte Nutzerwünsche
- Mr. Stark erteilt den Auftrag; keine selbstständigen externen Aktionen.
- Eine neue Telegram-Nachricht hat sofort Vorrang und unterbricht den laufenden Workflow an der nächsten sicheren Grenze.
- Kein zweiter Telegram-Poller, keine zweite Telethon-Control-Schleife.
- Maximal 100 geplante Schritte pro Workflow.
- PC nur bei explizitem Auftrag und Zustimmung nutzen; zuerst API-/Seeker-Lösung versuchen.
- PC nach einem ausdrücklich erlaubten temporären Einsatz wieder ausschalten, außer Mr. Stark sagt ausdrücklich etwas anderes.
- `/server/ophanim` enthält nur Ophanim-Dateien; `/server/website` bleibt unverändert.
- Keine unbestätigten, erfundenen oder Platzhalter-Posts.
- Ophanim-Posts einzeln, mit FloodWait-/Duplicate-Schutz, Zeitabstand und Tageslimits.
- Friday lokal mit kleinem Kontext und möglichst wenig RAM betreiben; Qualität nur so weit reduzieren, wie der Nutzen erhalten bleibt.
- Friday darf analysieren, filtern, zusammenfassen und priorisieren; Ophanim veröffentlicht nur geprüfte Ergebnisse.
- Controller/Watchdog schreibt Status- und Fehlerlogs und meldet relevante Änderungen an Telegram.
- Keine Credentials, API-Keys, Tokens oder Wallet-Key-Material in Logs, Checkpoints oder Antworten.

## Workflow-Modell
1. Auftrag in höchstens 100 konkrete Schritte zerlegen.
2. Vor jedem consequential Schritt prüfen, ob eine neue Owner-Nachricht eingetroffen ist.
3. Nach jedem größeren Schritt Checkpoint schreiben.
4. Bei Unterbrechung sofort Zustand speichern und stoppen; nicht automatisch fortsetzen.
5. Nach Resume exakt ab dem letzten verifizierten Schritt weiterarbeiten.
6. Abschluss mit erledigten, übersprungenen und offenen Schritten melden.

## Pflichtdateien
Für lange Aufgaben verwenden:
- `workflow-state.json`: Status, aktueller Schritt, nächster Schritt, Zeitstempel
- `workflow.log`: redigierter Fortschritt und Fehler
- optional `cancel-state.json`: kooperative Abbruchmarke

Keine Secrets in diesen Dateien.

## Task-Loop-Schritte
Jeder Schritt hat:
- `id`
- `description`
- `status`: pending/running/done/failed/skipped/cancelled
- `startedAt` und `finishedAt`
- kurze redigierte Notiz
- optional `retryable`

Keine unbounded Schleifen. Kein `while true`, kein enger Polling-Loop, kein langes `sleep` als Workflow-Ersatz. Für wiederkehrende Überwachung systemd-Timer oder SeekerClaw-Cron mit festen Intervallen verwenden.

## Friday-Ressourcenprofil
Bevorzugte Startwerte für lokale kleine Modelle:
- Kontext standardmäßig 4096 Tokens, nur bei begründetem Bedarf erhöhen.
- Reasoning-Budget klein halten, typischerweise 256–512.
- Batch-/Micro-Batch moderat wählen.
- CPU-Threads begrenzen und messen.
- `mlock` deaktivieren, sofern kein konkreter Stabilitätsgrund dagegen spricht.
- RAM nach Änderungen anhand RSS und Systemstatus prüfen.
- Modellqualität nicht durch aggressives Unload oder gefährliche OOM-Parameter zerstören.
- Vor Änderungen Backup der Konfiguration anlegen.

## Friday/Ophanim-Integration
Empfohlene Pipeline:
`Collector → Friday Analyse/Filter → Controller Status/Fehler → Ophanim Poster`

Friday darf keine Veröffentlichung direkt erzwingen. Der Poster prüft weiterhin:
- Datenquelle und Mindestqualität
- Rug-/Sicherheitsfilter
- Duplikate
- Tageslimit
- Mindestabstand
- FloodWait und Rate Limits
- persistente Resume-Daten

## Controller
Ein schlanker Controller darf regelmäßig prüfen:
- Friday-Modellserver
- Friday-Bot
- Ophanim-Daemon
- Timer-/Scheduler-Zustand
- letzte Fehler und RAM-Snapshot

Er soll per systemd-Timer laufen, nicht als dauerhafter enger Python-Loop. Telegram-Meldungen nur bei Zustandsänderung, Fehlern oder relevanten Recovery-Ereignissen.

## Sicherheitsgrenzen
Stoppen und Nutzer fragen bei:
- Fundbewegungen, Nachrichten, Anrufen oder öffentlichen Posts, sofern nicht bereits ausdrücklich vom Auftrag umfasst und durch Tool-Gate gedeckt
- destruktiven Änderungen
- Credentials oder Schlüsselmaterial
- unklarer Zielgruppe oder unklarer Veröffentlichung
- PC-Einschalten ohne explizite Zustimmung

Nie Schutzmechanismen, Bestätigungs-Gates, Wallet-Policies oder Telegram-Interrupts umgehen.

## Completion Report
Am Ende knapp berichten:
- Status der Services
- erledigte Schritte
- Checkpoint-Pfad
- RAM-/Kontextprofil
- offene Risiken oder nicht integrierte Teile
- ob tatsächlich veröffentlicht wurde oder absichtlich nicht

## Version
1.0.0
