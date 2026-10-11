# Changelog

All notable changes to WH3 Save Editor. Downloads: https://github.com/davehornik/WH3SaveEditor/releases

## v1.2.4 — 2026-10-11

**Added**
- Changelog page: the "Changelog" button at the bottom of the sidebar opens the version history inside the app. When a newer release is available, its release notes are shown on top with a link to the download.

**Fixed**
- Multiplayer → Singleplayer conversion could report "Done! New singleplayer save:" with an empty path and write nothing (GitHub issue #2). Cause: a faction whose player had left the game is stored as `IDLE_HUMAN` (a third state next to `FULL_HUMAN` / `NON_HUMAN`, confirmed in the game's code) and the converter only knew the other two; the failure was then swallowed because the exception carried no message. `IDLE_HUMAN` is now handled, and any conversion error is reported with its type instead of being shown as success.
- The converter identified the human turn group by the on-disk array type instead of by its content. The array type only reflects how large the faction ids are, so saves with faction ids ≥ 256 in the human group could be converted incorrectly. Turn groups and `HUMAN_FACTIONS` are now written with the same size-dependent encoding the game uses.
- Negative 32-bit integers stored in the save's compact 3-byte form (values between −32 769 and −8 388 608, e.g. a faction treasury deep in debt) were decoded and re-encoded with the wrong sign convention. The game uses two's complement; the editor used sign-magnitude. Unmodified values were never affected (the editor copies untouched bytes verbatim), only the display and edits of such values. Verified against the game's own serializer code and a byte-exact round trip of 20 M values from real saves.

## v1.2.3 — 2026-10-04

**Fixed**
- Multiplayer → Singleplayer conversion left the other players' factions "waiting for a human" at end of turn or in diplomacy. The save stores the human/AI flag for a faction twice (in `CAMPAIGN_PLAYER_SETUP` and directly on the `FACTION` record) and only the first one was switched — both are now switched. If a save converted with v1.2.x gets stuck, simply convert the original multiplayer save again. Thanks to **LuxInTenebr1s** for the root cause and fix, and to **HueTheCoder** for the vanilla repro (GitHub issue #1).

**Other**
- The exe now carries Windows version information (Properties → Details)
- License: pull requests are explicitly welcome; contributors are credited

## v1.2.2 — 2026-07-25

- Fixed remaining Czech strings in the English UI (sidebar label, RAW tree node, toolbar name)
- The binary now matches the published source code exactly

## v1.2.1 — 2026-07-24

- Theme names in Settings are localised
- Fixed version comparison in the update checker (patch releases are now announced correctly)
- Full source code published in the repository (source-available license) with build instructions

## v1.2 — 2026-07-24

*Includes everything planned for v1.1 — testing finished so quickly that both versions shipped together.*

**New**
- **Multiplayer → Singleplayer conversion** (Tools page) — continue any co-op campaign solo: pick the save, choose which player to continue as, and get a regular singleplayer save. Works with 2+ player campaigns, older-patch saves, and both host and client copies. No mod required.
- **Readable in-game names** for characters, factions, units and settlements (resolved from your game's localisation packs)
- **5 UI themes** — Obsidian & Amber, Forge, Parchment & Seal, Dark Parchment, Blood Throne — switchable live, plus compact/airy table density
- Welcome screen with recent saves and quick-start steps
- Update notification on startup (silent when offline, no telemetry)
- Army tools: one-click **Heal army**, **Max rank army**, **Remove unit** (lords/heroes protected)
- Converted saves are named after the faction you continue as (editable)

**Fixed**
- Rare *"decompressed size mismatch"* error that prevented ~1–2 % of valid saves from loading
- Save-folder detection no longer nags singleplayer-only players
- Max rank army no longer touches lords and heroes (their level belongs to the character)

## v1.0 — 2026-07-20

First public release: faction treasuries, characters (rank / XP / skill points, including the recruitment pool), units (strength / rank / experience), diplomacy (relations & treaties, experimental vassals), save renaming, mod list with Workshop links, RAW tree editor, English & Czech UI. Verified in game on WH3 8.1.x, singleplayer and multiplayer saves.
