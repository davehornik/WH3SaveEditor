# Building WH3 Save Editor from source

The app is plain Python — no compilation step is needed to *run* it, and one
command packages it into the same standalone `WH3SaveEditor.exe` that is
published in releases.

## Requirements

- **Windows 10/11** (the tool targets Windows save paths; the core would run
  elsewhere but is untested)
- **Python 3.10+** — https://www.python.org/downloads/ (check *"Add python to PATH"*)

## 1. Get the source

```
git clone https://github.com/davehornik/WH3SaveEditor.git
cd WH3SaveEditor
```

## 2. Install dependencies

```
pip install -r requirements.txt
```

That installs exactly two runtime dependencies:

| Package     | Purpose                                          |
|-------------|--------------------------------------------------|
| `PySide6`   | Qt 6 GUI framework                               |
| `zstandard` | reading localisation packs from the game's data  |

## 3. Run from source

```
cd src
python gui.py
```

That's it — this is exactly how the app is developed and tested.

## 4. (Optional) Build the standalone .exe

```
pip install pyinstaller
cd src
python gen_version_info.py
pyinstaller --noconfirm --clean --onefile --windowed --name WH3SaveEditor ^
  --version-file version_info.txt ^
  --add-data "lang;lang" --add-data "fonts;fonts" --add-data "icon.ico;." ^
  --hidden-import convert_mp_sp --hidden-import zstandard ^
  --icon icon.ico gui.py
```

(`gen_version_info.py` generates the Windows version resource — file
description, version, copyright — from `APP_VERSION` in `gui.py`.)

The result is `src\dist\WH3SaveEditor.exe` (~48 MB — PyInstaller one-file bundles
the Python runtime and Qt).

> **Note on antivirus false positives:** PyInstaller's one-file bootloader
> unpacks itself to a temp directory at runtime, which some AV engines flag
> heuristically. Building the exe yourself from this source produces a
> functionally identical binary (byte-for-byte reproducibility is not
> guaranteed — PyInstaller embeds timestamps).

## Source map

| File               | Purpose                                                        |
|--------------------|----------------------------------------------------------------|
| `src/esf.py`           | ESF save-format parser + writer (lazy tree, copy-on-write)     |
| `src/gui.py`           | PySide6 application (all pages, dialogs, update check)         |
| `src/themes.py`        | UI themes (QSS templates + color tokens)                       |
| `src/tables.py`        | extraction of factions/characters/units/diplomacy from the tree|
| `src/convert_mp_sp.py` | multiplayer → singleplayer save conversion                     |
| `src/locdb.py`         | readable names from the game's localisation packs              |
| `src/i18n.py`          | UI translations (`src/lang/*.json`)                                |
| `src/test_*.py`        | test suite (round-trip, deep-walk, encodings, GUI models)      |

The app performs **one** network request: an optional version check against
`api.github.com/repos/davehornik/WH3SaveEditor/releases/latest` on startup
(see `UpdateCheck` in `gui.py`), which fails silently when offline. There is
no telemetry. All file writes are limited to files explicitly chosen by the
user, plus `settings.ini` and `loc_cache.json` next to the executable.
