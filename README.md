<div align="center">

# Kali

**A local, loyal AI assistant that lives on your machine.**

Groq / SiliconFlow / Novita / GitHub Models / Google AI Studio cloud, or Ollama local. Full OS access.
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
  ┌─────┴──────┐
  │            │
┌─▼──┐    ┌────▼────┐
│Groq│    │  Ollama │
│API │    │ (local) │
└────┘    └─────────┘
```

**Provider routing.** Kali can use any of several cloud providers — Groq, SiliconFlow, Novita AI, GitHub Models, and Google AI Studio — and falls back to local Ollama when the chosen provider is offline, unconfigured, or erroring. Pick the active provider in Settings → Backends → Provider routing, and set a per-provider API key and model in that provider's group. Toggle "Prefer cloud over local" off to always use Ollama. The active provider is shown as a pill in the header.

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
- Ollama + a small fallback model (`llama3.2:1b` by default, ~1.3 GB)
- The three Python files + dragon SVG icon
- A `kali` launcher in `~/.local/bin/`
- A `.desktop` entry so Kali shows up in your app grid
- A systemd `--user` unit so Ollama starts at login
- An optional prompt for your Groq API key (you can skip and add it later in Settings)

**Time:** ~3-8 min on first install (model download is the bottleneck). Re-runs are ~5 seconds.

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
| `--refresh-ollama`   | re-run Ollama's installer to update it                  |
| `--no-systemd`       | don't install the systemd unit file                     |
| `--no-ollama`        | skip Ollama entirely (Groq-only setup)                  |
| `--no-model`         | don't pull a local model                                |
| `--no-groq`          | don't install the groq library or prompt for a key      |
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

Read-only tools fire on their own so Kali can see the system and reason. Anything that changes state goes through `propose` → your approval → `run`. Clicking **Run** is your approval; you only get a second prompt when a command needs your sudo password. You can stop Kali mid-reply any time with the stop button (the send button turns into it) or the **Esc** key.

### Security audit checks

Firewall (ufw/iptables/nftables) · Listening ports on all interfaces · SSH server config · Pending security updates · Kernel age · Failed SSH login attempts · Disk encryption (LUKS) · Home directory permissions · AppArmor / SELinux · Shell history secret scan.

### Watcher (optional)

A background thread that periodically:

- Counts pending security updates (every 4h)
- Watches for new files in ~/Downloads (every cycle)
- Tails the journal for notable events (failed logins, USB device events, OOM kills)

Off by default. Enable in Settings → Behaviour → Watcher. Surfaces events as transient banners in the chat area.

## What Kali can NOT do

- **Modify her own code.** Hardcoded off. She can read her own source if you ask, but she can't write to it. This is deliberate.
- **Persist state outside the chat DB and settings file.** No hidden side-channels.
- **Reach the internet directly.** The Groq backend is for text generation only. She doesn't browse, scrape, or open URLs unless you do it through her by running `curl` via the `run` tool with your confirmation.
- **Run as root without you.** She can't. Privileged commands are proposed, never auto-run, and when you approve one she asks for your sudo password in the confirmation dialog. The password is validated against `sudo` and used to cache the credential for that command; it is never written to disk or the log. The primary path feeds it once on `sudo -S`'s stdin and the command itself sees EOF. On hardened sudoers configs (`timestamp_timeout=0`) Kali falls back to `SUDO_ASKPASS`, which briefly places the password in the environment of that single sudo call only — readable in principle via `/proc/<pid>/environ` by your own user while the call runs, then cleared. In both paths the password never reaches the command's own stdin.

## File layout

```
~/.local/share/kali/
  ├── kali.py                  # UI
  ├── kali_core.py             # backends, tools, audit
  ├── kali_persona.py          # personality + system prompt
  ├── org.thepriest.kali.svg   # icon
  ├── chats.db                 # SQLite chat history
  ├── kali.log                 # diagnostics
  └── backups/
       └── chats-YYYYMMDD.db   # auto-backup before each install

~/.config/kali/
  └── settings.json            # all settings, including Groq key

~/.local/bin/kali              # launcher
~/.local/share/applications/org.thepriest.kali.desktop
~/.local/share/icons/hicolor/scalable/apps/org.thepriest.kali.svg
~/.config/systemd/user/kali-ollama.service
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
