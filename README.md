<div align="center">

# Kali

**A local, loyal AI assistant that lives on your machine.**

Groq / SiliconFlow / Novita / GitHub Models / Google AI Studio — cloud-only, multi-provider. Full OS + desktop control.
Reads files. Watches services. Audits security. Runs commands with your permission.

</div>

---

## What it is

Kali is a personal AI assistant in the shape of a GTK4 chat app, named for the Hindu goddess and the Linux distribution both. She talks to you, but she also has hands on your machine: she can read your files, snapshot system state, scan your network, audit your security posture, check for updates, watch your Downloads folder, and tail your journal — all read-only, all without nagging you.

When something needs to *change* — installing a package, editing a config, anything as root — she does **not** run it on her own. She explains what she'd do and why, then proposes the exact command as a card with a **Run** button and a risk level. Nothing executes until you click Run or tell her to. Commands that need root show an inline password field; your sudo password is validated and used to cache the credential, and is never stored, logged, or shown to her.

She's built for one operator — you — and she behaves like it. No corporate guardrails, no boilerplate hedging, no "as an AI language model." She's witty, direct, loyal, reasons things through with you, and stays on your side.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       kali.py (UI)                      │
│              GTK4 + libadwaita, Catppuccin Mocha        │
└───────────────────────┬─────────────────────────────────┘
                        │
        ┌───────────────┴────────────────┐
        │                                │
   ┌────▼─────┐                    ┌─────▼──────┐
   │ kali_    │                    │ kali_      │
   │ core.py  │                    │ persona.py │
   │          │                    │            │
   │ backends │                    │ system     │
   │ tools    │                    │ prompt     │
   │ chat DB  │                    │ assembly   │
   │ audit    │                    └────────────┘
   │ watcher  │
   └────┬─────┘
        │
  ┌─────┴───────────────────────────┐
  │  active provider (pick one)      │
┌─▼────┬───────────┬────────┬────────┬──────────┐
│ Groq │SiliconFlow│ Novita │ GitHub │  Google  │
└──────┴───────────┴────────┴────────┴──────────┘
   all OpenAI-compatible · cloud-only
```

**Provider routing.** Kali is cloud-only and supports five providers: Groq, SiliconFlow, Novita AI, GitHub Models, and Google AI Studio. Pick the active one in Settings → Backends → Provider routing, and set its API key and model in that provider's group. The active provider is shown as a pill in the header. There is no local model — if the active provider has no key or you're offline, Kali tells you instead of falling back.

Every cloud provider speaks the OpenAI-compatible chat-completions API, so each one has the same controls: an API key field, a model picker (biggest/best models listed first), and a refresh button (⟳) that pulls the provider's live model catalogue from its API. If a configured model ID has gone stale, Kali transparently re-fetches the live list and retries with a real model rather than erroring out.

## Install

**One-liner (recommended):**

```bash
curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
```

What it installs:

- Python 3.10+ check (fails fast if not present)
- GTK4 + libadwaita bindings (apt / pacman / dnf, auto-detected)
- `groq` Python library (cloud backend)
- Optional desktop-control helpers (xdotool/wmctrl on X11, or wtype/wlrctl/grim on Wayland; plus tesseract-ocr and playerctl) — for app launching, typing/clicking, screenshots and screen reading. Best-effort; skipped with `--no-helpers`.
- Optional Playwright + Chromium for browser automation (skipped with `--no-browser`)
- The three Python files + dragon SVG icon, plus the optional `kali_ext/` sidecar (extensions stay off until you enable them in settings)
- A `kali` launcher in `~/.local/bin/`
- A `.desktop` entry so Kali shows up in your app grid
- An optional prompt for your Groq API key (you can skip and add it later in Settings)

**Time:** ~1-3 min on first install. Re-runs are ~5 seconds.

**Update later:** re-run the same one-liner. It detects what's done and only does what's missing.

**Uninstall:** `~/.local/share/kali/install.sh --uninstall` (chat history kept).

### Removing a previous Oracle install

If you installed the older Oracle version of this app, the installer auto-detects it and prompts you to remove it. Or do it explicitly:

```bash
~/.local/share/kali/install.sh --remove-oracle
```

This stops and disables `oracle-ollama.service`, removes `~/.local/bin/oracle`, the desktop entry, the systemd unit, and wipes `~/.local/share/oracle/` and `~/.config/oracle/`. Your chat history migrates to Kali if Kali doesn't already have its own DB. Your Kali install is not touched.

### Manual install

```bash
git clone https://github.com/the-priest/oracle5.git kali
cd kali
./install.sh
```

### Flags

| flag                 | what it does                                            |
| -------------------- | ------------------------------------------------------- |
| `--update`           | explicit update (same as default install)               |
| `--uninstall`        | remove Kali (chat history kept)                         |
| `--remove-oracle`    | remove the old Oracle install (Kali untouched)          |
| `--no-systemd`       | don't install the systemd unit file                     |
| `--no-helpers`       | skip optional desktop-control helpers                   |
| `--no-browser`       | skip Playwright + Chromium (browser automation)         |
| `--no-groq`          | don't install the groq library or prompt for a key      |
| `--no-voice`         | skip voice setup (espeak / Piper / mic packages)        |
| `--no-prompt`        | non-interactive (skips Groq key prompt)                 |

### Env overrides

```bash
KALI_MODEL=qwen2.5:0.5b   ./install.sh    # tiny but capable (~400 MB)
KALI_MODEL=llama3.2:3b    ./install.sh    # better but ~2 GB
GROQ_API_KEY=gsk_...      ./install.sh    # preset, no prompt
KALI_REPO=user/fork  KALI_BRANCH=dev  ./install.sh
```

## Get an API key

Kali works with several cloud providers. You only need a key for the one(s) you want to use — set the active provider and its key in Settings → Backends.

| Provider | Get a key | Notes |
| -------- | --------- | ----- |
| Groq | <https://console.groq.com/keys> | Fast, generous free tier. Key looks like `gsk_...` |
| SiliconFlow | <https://cloud.siliconflow.com/account/ak> | Big open models (DeepSeek, Qwen, Kimi) |
| Novita AI | <https://novita.ai/settings/key-management> | Cheap GPU inference, many open models |
| GitHub Models | <https://github.com/settings/personal-access-tokens> | Free tier. Use a fine-grained PAT with the `models:read` scope |
| Google AI Studio | <https://aistudio.google.com/apikey> | Gemini models, free tier |

Paste a key into that provider's group in Settings → Backends. Keys are stored locally in `~/.config/kali/settings.json` only — they never leave your machine except in API calls to the provider you're using. Groq can also be preset during install via the prompt or `GROQ_API_KEY=...`.

Not sure which model to pick? Each provider's model dropdown lists the biggest/best models first. Hit the ⟳ button next to it to fetch that provider's live catalogue once your key is set.

## What Kali can do on your system

Everything below runs as your user (no sudo). Read-only tools fire without confirmation. `run` always prompts y/n with the exact command and her reason.

| tool                 | what it does                                                    |
| -------------------- | --------------------------------------------------------------- |
| `read_file`          | Read any file you can read.  Sensitive paths (~/.ssh, ~/.gnupg) prompt for permission. |
| `list_dir`           | List a directory.                                               |
| `find_file`          | Find files by name pattern.                                     |
| `system_info`        | uname, OS, uptime, RAM, load.                                   |
| `disk_usage`         | `df -h` filtered to real filesystems.                           |
| `processes`          | Top processes by CPU.                                           |
| `network_status`     | Interfaces, default gateway, online check.                      |
| `recent_downloads`   | What's new in ~/Downloads.                                      |
| `check_updates`      | `apt list --upgradable`, with security flagging.                |
| `service_status`     | Inspect any systemd service.                                    |
| `journal_tail`       | Recent system log lines (any unit).                             |
| `propose`            | Suggest a command as a card (explanation + risk + **Run** button). Runs nothing. |
| `run`                | Execute an **approved** command. Sudo commands show a password field. |
| `audit`              | 10-check parallel security audit. Grade A+ → F.                 |
| `scan_net`           | `nmap -sn` on your local subnet (ARP fallback if no nmap).      |
| `desktop_info`       | Reports what desktop control is available (Wayland/X11, helpers).|
| `list_apps`          | List installed GUI apps (`.desktop` entries).                   |
| `launch_app`         | Launch an app by name, desktop id, file, or URL.                |
| `open_url`           | Open a URL in your default browser.                             |
| `list_windows` / `focus_window` / `close_window` | List open windows; focus or close one. |
| `type_text` / `press_key` | Type text / send keys to the focused window.               |
| `notify`             | Pop a desktop notification (ping you when a long task ends).     |
| `media_control`      | Play/pause/next/previous via playerctl.                         |
| `screenshot`         | Capture the screen to a PNG (grim/scrot/import).                |
| `read_screen`        | Screenshot **+ OCR** — Kali reads what's on screen (tesseract). |
| `path_info` / `make_dir` / `copy_path` / `move_path` / `delete_path` | Full filesystem ops. Destructive ones are path-guarded and confirm-gated. |
| `browser`            | Drive a real browser (Playwright): goto, read, click, fill, screenshot. Session persists across calls. |

Read-only tools fire on their own so Kali can see the system and reason. Anything that changes state — running a shell command, launching an app, typing, moving or deleting files — goes through your approval first while **Confirm every command** is on (Settings → Behaviour). Turn that toggle off and those actions run immediately ("auto" mode). Shell commands still use the `propose` → **Run** card flow; the new device-control actions use a quick confirm dialog. You can stop Kali mid-reply any time with the stop button or the **Esc** key.

**Desktop control needs small helpers**, installed for you by `install.sh` (or `apt install` them later): on X11 `xdotool` + `wmctrl` + `scrot`; on Wayland `wtype` + `wlrctl` + `grim`; plus `tesseract-ocr` for screen reading, `libnotify-bin` for notifications, and `playerctl` for media. On **KDE Plasma** it also picks up Spectacle for screenshots and uses kdialog/notify-send where they're better. Browser automation needs Playwright (`pip install playwright && playwright install chromium`). Every tool detects what's missing and tells you the package to install rather than failing silently — ask Kali to run `desktop_info` to see what's available on your box.

### Security audit checks

Firewall (ufw/iptables/nftables) · Listening ports on all interfaces · SSH server config · Pending security updates · Kernel age · Failed SSH login attempts · Disk encryption (LUKS) · Home directory permissions · AppArmor / SELinux · Shell history secret scan.

### Watcher (optional)

A background thread that periodically:

- Counts pending security updates (every 4h)
- Watches for new files in ~/Downloads (every cycle)
- Tails the journal for notable events (failed logins, USB device events, OOM kills)

Off by default. Enable in Settings → Behaviour → Watcher. Surfaces events as transient banners in the chat area.

## Voice (talk to it, hear it back)

Kali can listen and speak — built to feel like the voice mode in the Claude app.

**Speak instead of type.** Tap the 🎤 next to the input box, talk, tap again to send. Your speech is transcribed through Groq's Whisper endpoint (it reuses your existing Groq key — fast and accurate, nothing extra to set up). The text drops into the box and sends automatically (toggle that off in Settings → Voice if you'd rather edit first).

**Hear the replies.** Flip the 🔊 toggle in the action row and Kali reads each reply aloud as it streams in — code blocks and tool output are skipped, so it reads the actual words, not punctuation. Output uses **Piper**, a local neural voice that sounds natural (the installer fetches a British voice by default); if Piper isn't available it falls back to `espeak-ng`.

**Play / pause / replay any message.** Every reply has its own speaker button. Tap it to read that message, tap again to **pause**, tap once more to **resume** — real pause/resume, not restart. Tap a different message's button to jump to it. Hitting Stop, sending a new message, or starting the mic all stop the speech immediately.

Everything is configurable in **Settings → Voice**: engine (auto / Piper / espeak), speech rate, Piper voice file, auto-send, Whisper model, and a language hint. There's a **Test voice** button too. Voice is entirely optional — if no engine or mic is present, the buttons just don't appear and Kali works exactly as before.

Set it up with the installer (on by default), or skip it with `--no-voice`. To add a different Piper voice later, drop an `.onnx` + `.onnx.json` into `~/.local/share/kali/voices/` or point Settings → Voice at it. Voices: <https://huggingface.co/rhasspy/piper-voices>.

## What Kali can NOT do

- **Rewrite her own code without you.** She *can* rewrite her own source and persona — but only by proposing a diff you approve, exactly like approving a sudo command. The Apply click is the gate. She cannot write Python that fails to parse (refused before any write), and she cannot touch the immutable `GUARDRAIL` block in `kali_persona.py`. A persona edit reloads live; a `kali.py`/`kali_core.py` edit needs a relaunch. This gate is deliberate and is not removed by any feature below.
- **Persist state outside the chat DB, settings file, and — only when you switch it on — the memory store** (`~/.local/share/kali/ext/memory.db`). No hidden side-channels; everything is a file you own with a settings toggle and a `memory_forget` tool.
- **Reach the internet directly.** The cloud backend is for text generation only. She doesn't browse, scrape, or open URLs unless you do it through her by running `curl` via the `run` tool with your confirmation.
- **Run as root without you.** She can't. Privileged commands are proposed, never auto-run, and when you approve one she asks for your sudo password in the confirmation dialog. The password is validated against `sudo` and used to cache the credential for that command; it is never written to disk or the log. The primary path feeds it once on `sudo -S`'s stdin and the command itself sees EOF. On hardened sudoers configs (`timestamp_timeout=0`) Kali falls back to `SUDO_ASKPASS`, which briefly places the password in the environment of that single sudo call only — readable in principle via `/proc/<pid>/environ` by your own user while the call runs, then cleared. In both paths the password never reaches the command's own stdin.

## Optional extensions (`kali_ext/`)

A sidecar package that adds memory, self-written skills, action foresight, and a headless companion. It imports nothing from Kali's core — it depends only on the standard library plus two callables Kali hands it at boot — so it can be deleted with no trace. **Everything here is OFF by default.** With all of these off, Kali behaves exactly as a stock build: nothing is injected, no threads start, and nothing runs in the background. Flip each on per feature in `settings.json` (or a Settings panel) when you want it.

- **Persistent memory** (`memory_enabled`). Relevance-scoped recall across sessions: each turn only the top-k memories matching your message are injected, so the prompt never grows with history. Local SQLite, keyword recall by default (no GPU); embeddings optional. Tools: `memory_remember`, `memory_recall`, `memory_forget`.
- **Self-written skills** (`skills_enabled`). Kali can author a Python tool, and on your confirmation it's ast-checked and its own test is run **in a sandbox** — saved only if the test passes. Saved skills run via `skill_run`, always sandboxed. Install `bubblewrap` (`apt install bubblewrap`) for real isolation; otherwise it falls back to a network-off, resource-capped child process.
- **Foresight** (`foresight_enabled`). Before any state-changing command runs, its consequences are predicted and a verdict attached. Catastrophic, irreversible commands (wiping disks, `fastboot flash`/`erase`, fork bombs) are **blocked even in auto-mode**; risky-but-recoverable ones are flagged. Deterministic rules always run; an optional model pass (`foresight_model`) can only escalate, never downgrade.
- **One command at a time** (`one_command_at_a_time`, on by default). Kali never proposes or runs more than one command per message.
- **Auto-detected host.** Every launch, Kali detects the OS, kernel, device, session, and whether it's on NetHunter, and tells herself — no config.
- **Headless companion** (`worker_enabled`, plus the optional `systemd --user` unit in `kali_ext/packaging/`). Moves the background checks, memory consolidation, and skill curation out of the GUI into a supervised user service. Does nothing unless `worker_enabled` is on, re-checked each tick. User scope, no root, never touches NetHunter's own units.

See `kali_ext/WIRING.md` for how the six guarded hook lines plug into `kali.py`.

## File layout

```
~/.local/share/kali/
  ├── kali.py                  # UI
  ├── kali_core.py             # backends, tools, audit
  ├── kali_persona.py          # personality + system prompt
  ├── kali_voice.py            # voice in/out (Groq Whisper STT, Piper/espeak TTS)
  ├── kali_ext/                # optional extensions (memory/skills/foresight/worker)
  ├── org.thepriest.kali.svg   # icon
  ├── voices/                  # Piper voice models (.onnx) — created by --voice setup
  ├── chats.db                 # SQLite chat history
  ├── kali.log                 # diagnostics
  ├── backups/
  │    └── kali_*.YYYYMMDD-HHMMSS.bak   # auto-backup before each self-edit
  └── ext/                     # created only when an extension is enabled
       ├── memory.db           # persistent memory store
       ├── skills/             # saved self-written skills
       ├── events.jsonl        # headless worker event spool
       └── ext.log             # extension diagnostics

~/.config/kali/
  └── settings.json            # all settings, including provider keys

~/.local/bin/kali              # launcher
~/.local/share/applications/org.thepriest.kali.desktop
~/.local/share/icons/hicolor/scalable/apps/org.thepriest.kali.svg
~/.config/systemd/user/kali-ext.service   # optional headless companion (off by default)
```

## Tweaking the persona

Open `~/.local/share/kali/kali_persona.py` in your editor. The persona is plain Python strings. Edit `PERSONA_CORE`, `OPERATOR_PROFILE`, `TOOL_CONTRACT`, or `CAPABILITIES`. Save and relaunch.

For lighter edits (per-machine notes that get appended to the prompt), use Settings → Persona → Custom addendum. This survives upgrades; edits to `kali_persona.py` directly will get clobbered when you re-run `install.sh`.

## Development

```bash
git clone https://github.com/the-priest/oracle5.git kali
cd kali

# Run from source
python3 kali.py

# Syntax check
python3 -c "import ast; [ast.parse(open(f).read()) for f in ('kali.py','kali_core.py','kali_persona.py')]"

# Push changes
./push.sh "your commit message"
```

## License

MIT.  See LICENSE.

## Credits

Built by The Priest. The dragon icon is original geometric art inspired by — but not a copy of — the official Kali Linux logo (which is a trademark of OffSec). To use a different icon, overwrite the SVG at `~/.local/share/icons/hicolor/scalable/apps/org.thepriest.kali.svg` (run `gtk-update-icon-cache` afterwards). The icon, the `.desktop` file, and the app's Wayland app-id / X11 WM_CLASS all share the name `org.thepriest.kali` on purpose — that's what lets the window, taskbar, and launcher icons resolve reliably, including on KDE Plasma, which matches a running window to its desktop entry by app-id.

---

<sub>Kali is not affiliated with OffSec, Kali Linux, or Groq.</sub>
