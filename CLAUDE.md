# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bat
run.bat          :: smart launcher — applies pending update, bootstraps .venv, launches GUI
```

`run.bat` now does three things in order: (1) applies `.update_pending/` if present (with backup + auto-rollback on crash), (2) bootstraps `.venv` if missing, (3) launches `pythonw app.py`. If the app exits with a non-zero code and an `.update_backup/` exists, run.bat restores the previous version.

Or manually (bypasses auto-update apply / rollback):

```bat
.venv\Scripts\python app.py
```

The only runtime dep is `openpyxl` (see `requirements.txt`). Updater uses stdlib only (`urllib.request` for GitHub API + asset download, `hashlib`, `zipfile`, `shutil`). No test suite, linter, or build step.

## Architecture

Python/Tkinter desktop app that batch-copies sticker design files based on an Excel order list. UI strings are Indonesian — preserve that language when editing user-facing text.

- **`version.py`** — single constant `__version__`. Separate file (not embedded in `app.py`) so the updater can replace it cleanly; running process holds old value in memory until restart.
- **`app.py`** — Tkinter GUI (`App(tk.Tk)`). Handles path pickers, mode selection, progress bar, colored log pane, and the auto-update banner. Processing runs in a background `threading.Thread`; `_log` / `_update_progress` / `_update_banner_state` marshal back to the UI thread via `self.after(0, ...)`. Paths, mode, `github_repo`, `github_token` (optional), and `last_known_version` persist to `config.json` (`load_config` / `save_config`). On startup, `_check_post_update_notification` compares `last_known_version` with `__version__` — if different, shows a `messagebox.showinfo` popup with release notes (read from `.update_backup/_manifest.json`).
- **`updater.py`** — auto-update logic using **GitHub Releases**. Zero Tk import, pure callbacks. `UpdateOrchestrator.run()` is the background-thread entry point and **never raises**; all failures are caught and logged to `.update_logs/update.log`. See "Auto-update" section below.
- **`file_processor.py`** — pure logic, no UI imports. Entry point is `process_orders(source_folder, excel_path, output_folder, mode, progress_callback, log_callback)`. It:
  1. **Wipes** `output_folder` contents (deletes files *and* subfolders — the app owns that directory).
  2. Reads the Excel via `read_pesanan` — hardcoded columns **A=Resi, B=SKU, C=Jumlah**, starting at row 2.
  3. Builds a flat filename → path index of `source_folder` (`build_index`, recursive via `os.walk`). Designed for large cloud-mounted folders — do not replace with per-row directory walks.
  4. Matches each order by **case-insensitive substring** of SKU against filenames (`find_design_from_index`). First match wins; order of `os.walk` determines the winner when multiple files contain the SKU.
  5. Copies via one of two strategies depending on `mode`.

### The two modes

Mode is a string `"normal"` or `"a3_round"` passed through from the radio-card UI.

- **`normal`** (`_copy_flat`) — copy N times into `output_folder` root, named `RESI__SKU__001.ext`. `used_names` set guards against collisions (adds `_1`, `_2`, ... suffix).
- **`a3_round`** (`_copy_to_subfolder`) — round `qty` **up** to the A3-sheet capacity of the detected size, then create `output_folder/SKU/` and fill it with `SKU__001.ext`, `SKU__002.ext`, .... Capacities live in `A3_CAPACITY` (`A5: 4`, `A6: 8`). `detect_size` parses SKUs like `001-VN-A6-B` by splitting on `-`/`_` and checking each segment against `A3_CAPACITY`, falling back to a regex. If size can't be detected, it logs a warning and falls back to the raw `qty` — do not silently skip.

When adding a new sheet size, update `A3_CAPACITY` only; `detect_size` and `round_up_to_capacity` pick it up automatically.

### Contract between layers

`log_callback(level, message)` and `progress_callback(current, total)` are the only channels from processor to GUI. Valid log levels are `"success"`, `"error"`, `"warning"`, `"info"` — these are tag names registered on the Tk Text widget, so new levels require a matching `tag_configure` in `app.py`.

`process_orders` returns `{"total", "berhasil", "tidak_ditemukan", "berhasil_list"}`; the GUI reads the first three for the status bar summary.

## Gotchas

- `output_folder` is destructively cleared on every run — never point it at a folder with user data.
- Excel is read with `data_only=True`; formulas without cached values return `None`.
- SKU matching is substring-based, so short SKUs can match unrelated files. If adding stricter matching, keep it case-insensitive.
- `~$pesanan_harian.xlsx` in the repo root is an Excel lock file — ignore it, don't commit edits to it.
- **Never let running Python write to `app.py` / `file_processor.py` / `version.py`.** File replacement is `run.bat`'s job exclusively. The Python updater only stages into `.update_staging/` → atomic-renames to `.update_pending/`. This sidesteps Windows file-lock edge cases.

## Auto-update

Employees get new versions without manual file replacement. **Source of truth: GitHub Releases.** On every app launch, a background thread (3s after UI paint) calls `GET /repos/{github_repo}/releases/latest`, compares `tag_name` against local `__version__`, and if newer: downloads the release asset ZIP → validates → extracts → atomic-renames to `.update_pending/`. A banner shows progress + a 3-second countdown, then the app spawns a detached `run.bat` and exits. The new `run.bat` sees `.update_pending/`, backs up current files, copies new ones, and launches the updated app. If the new version crashes (non-zero exit), `run.bat` auto-rolls back from `.update_backup/`. After a successful update, the new app shows a `messagebox.showinfo` popup ("Update Berhasil") with the release notes, driven by `last_known_version` ≠ `__version__` check in `_check_post_update_notification`.

### Config keys (in `config.json`)

- `github_repo` — **required** for updates to work. Format: `"owner/repo"` (e.g., `"hobjectgroup/sortir-stiker-pack"`). If missing, update check is silently skipped.
- `github_token` — optional. Personal Access Token for private repos. Null/missing = public repo, no auth.
- `last_known_version` — auto-managed by `_check_post_update_notification`. Used to detect "I was just updated" state. Do not edit manually.

### Release asset convention

The GitHub Release must have an asset with name matching pattern `sortir-stiker-pack-*.zip`. `release.py` produces this name automatically. If no such asset exists, updater falls back to the first `.zip` asset; if none, update is skipped.

The ZIP must contain these files **at the root** (no wrapper folder):
```
app.py
file_processor.py
updater.py
version.py
requirements.txt
```

The GitHub Release **body** (markdown) is shown as release notes. Format with bullets:
```
- Tambah fitur X
- Perbaikan bug Y
```
`parse_release_notes` in `updater.py` extracts lines starting with `- `, `* `, or `• `.

### Runtime folders (all in project root, all gitignored)

- `.update_staging/` — transient download/extract workspace. Wiped on every update attempt.
- `.update_pending/` — atomic "ready to apply" marker. Only exists after staging completed successfully. `run.bat` applies this on next launch.
- `.update_backup/` — created by `run.bat` before apply. Contains the files that were just replaced. Also contains `_manifest.json` (copied from `.update_pending/extracted/`) which the new app reads for the post-update popup. Deleted after a successful launch.
- `.update_logs/update.log` — rotating file log (3 backups × 256 KB) for debugging.

### Check cadence

**No throttling** — update check runs every app launch. Rate limit for the GitHub API is 60 req/hour for unauthenticated public repos, 5000/hour with a token — plenty for normal usage. **Ctrl+Shift+U** forces a re-check within the same session (also toggles verbose log mode: up-to-date / offline outcomes are shown in the log pane).

### Silent vs verbose UX

Silent path (up-to-date, GitHub unreachable, repo not configured): no log, no banner. Only the debug file log has details. This keeps zero-noise for employees.

Active update path (new version found): log pane shows version + release notes + progress, banner shows download bar, ready-state countdown, restart. Force mode (Ctrl+Shift+U) logs every outcome.

Post-update path (after restart into new version): popup + log line confirming update.

### Contract

The update system's integration points:
- `version.py::__version__` — read at startup for title bar, updater comparison, and post-update detection
- `app.py::load_config/save_config` — orchestrator persists nothing by itself (no throttle anymore); `last_known_version` is set by `_check_post_update_notification`
- `app.py::_log(level, message)` — updater log callback, reuses existing `success/error/warning/info` tags
- `app.py::_update_banner_state(state, pct)` — 6 states: `hidden / checking / downloading / validating / ready / cancelled`

## Release process (developer)

```
1. Edit app.py / file_processor.py / etc. Test locally with run.bat (or run.vbs).

2. python release.py 1.2.0 --notes "Bulletpoint 1" "Bulletpoint 2"
   → bumps version.py to 1.2.0
   → builds dist/sortir-stiker-pack-1.2.0.zip

3. Publish to GitHub Release — two options:

   Option A: via `gh` CLI (fastest; requires `gh auth login` once):
     gh release create v1.2.0 dist/sortir-stiker-pack-1.2.0.zip \
       --title "Release v1.2.0" \
       --notes "- Bulletpoint 1
- Bulletpoint 2"

   Option B: via GitHub web UI:
     - Go to https://github.com/<owner>/<repo>/releases/new
     - Tag: v1.2.0
     - Attach the ZIP from dist/
     - Paste release notes (use `- ` bullets)
     - Publish release

   Option C: single-command, `release.py` auto-publishes via gh:
     python release.py 1.2.0 --notes "..." --publish

4. Verify — on a second workstation (or same one, after reverting version.py to old):
     - Launch app, press Ctrl+Shift+U
     - Banner → download → countdown → restart
     - Popup "Update Berhasil" appears
     - Title bar now shows v1.2.0
```

For local build verification WITHOUT publishing, use `--dry-run`: outputs to `_test_updates/` and does NOT modify `version.py`. ZIP is built but not uploaded. (End-to-end flow testing requires a real GitHub repo; dry-run just verifies the build step.)

## Recovery (manual rollback)

If auto-rollback fails or the update leaves the app unusable:

1. Go to `https://github.com/<owner>/<repo>/releases`
2. Find the previous good release, download the ZIP
3. Extract into project folder, overwriting `app.py`, `file_processor.py`, `updater.py`, `version.py`, `requirements.txt`
4. Delete any `.update_pending/` and `.update_backup/` folders
5. Run `run.bat` (or `run.vbs`)

## Security note

Anyone with **write access to the GitHub repo** can publish a release that auto-installs on all clients. There is no code signing — treat the repo permissions as your trust boundary. Using a private repo + restricted collaborator list is the simplest mitigation. Transport integrity is provided by HTTPS to `api.github.com` and `github.com`. The SHA-256 helper in `updater.py` is unused for GitHub releases (HTTPS is trusted end-to-end); kept for possible future use.
