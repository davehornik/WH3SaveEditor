# WH3 Save Editor

A savegame editor for **Total War: WARHAMMER III** — supports both **singleplayer** (`.save`) and **multiplayer** (`.save_multiplayer`) campaign saves.

## Features

- Opens, edits and re-saves WH3 campaign saves (ESF `0xABCB` format with LZMA-compressed campaign data)
- **Overview** — rename your save, see campaign, game version, mod list with Steam Workshop links, and edit player treasuries in one click
- **Factions** — all factions with editable treasury
- **Characters** — lords & heroes including the recruitment pool: rank, XP and unspent skill points (all editable), with role detection (army / hero / caravan / garrison / recruit pool)
- **Units** — every unit of every army: strength, max size, rank, experience (editable), grouped and filterable by army
- **Diplomacy** — relations between any two factions: war / peace / alliances via a color-coded picker, treaties (non-aggression pact, trade rights, military access) and experimental vassal/master editing
- **RAW data** — full lazy tree of the entire save (28M+ nodes) for advanced edits
- English & Czech UI, quick-open list of your recent saves, guided first-run setup
- Verified in game: money, XP, ranks, skill points, unit strength and save renaming all survive loading and re-saving

## Download & first run

1. Download `WH3SaveEditor.exe` from the [latest release](https://github.com/davehornik/WH3SaveEditor/releases/latest)
2. Run it — pick your language; the app finds your save folders automatically
3. Edit, hit *Save as…*, load it in the game. **Always keep a backup of your original save.**

## ⚠ Windows SmartScreen / antivirus warning

This app is **not code-signed** (certificates cost money), so Windows SmartScreen may show *"Windows protected your PC"* — click **More info → Run anyway**. Some antiviruses occasionally flag PyInstaller-packed executables as false positives — the original SaveParser had the same issue.

**Don't want to trust a random .exe?** Totally fair — message me and I'll send you the full source code so you can review it and build it yourself (plain Python + PySide6, single PyInstaller command).

## Compatibility

- Total War: WARHAMMER III, tested on patch 8.1.x (Immortal Empires), singleplayer and multiplayer saves
- Older WH1/WH2 saves (ESF `0xABCA`) should parse as well, but are untested

## Credits & inspiration

- **[SaveParser](https://sourceforge.net/projects/saveparser/)** by [RoninX](https://sourceforge.net/u/roninx2807/profile/) — the original savegame editor for older Total War titles that inspired this tool (WH3 was never supported there)
- **[EditSF fork by xADDBx](https://github.com/xADDBx/EditSF)** — first public editor supporting the WH3 `ABCB` codec
- **[RPFM](https://github.com/Frodo45127/rpfm)** by Frodo45127 — reference implementation of the ESF format
- Thanks to the Total War modding community for keeping the format knowledge alive

## Legal

Unofficial fan tool, not endorsed by SEGA, Creative Assembly or Games Workshop. *Total War: WARHAMMER* is their property. Use at your own risk — always back up your saves.
