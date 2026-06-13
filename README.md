<div align="center">

# Kali

**A local, loyal AI assistant that lives on your machine — and has hands on it.**

Multi-provider cloud AI (SiliconFlow · Groq · Novita · GitHub Models · Google AI Studio).
Reads files. Drives your desktop. Searches the web. Browses GitHub. Audits security.
Talks and listens. Runs commands — with your permission, one at a time.

`v0.8.0` · GTK4 + libadwaita · Linux

</div>

---

## What it is

Kali is a personal AI assistant in the shape of a GTK4 chat app — named for the Hindu goddess and the Linux distribution both. She talks to you, but she also has hands on your machine: she reads your files, snapshots system state, scans your network, audits your security posture, watches your Downloads, tails your journal, **searches the web, reads pages, and browses GitHub** — and she can talk back and take dictation by voice.

When something needs to **change** — installing a package, editing a config, anything as root — she does **not** run it on her own. She explains what she'd do and why, then proposes the exact command as a card with a **Run** button and a risk level. Nothing executes until you approve it. Commands that need root show an inline password field; your sudo password is validated, used to cache the credential, and is **never** stored, logged, or shown to her.

She's built for one operator — you — and behaves like it. No corporate guardrails, no boilerplate hedging, no "as an AI language model." Witty, direct, loyal; she reasons things through with you and stays on your side.

---

## Why Kali over Hermes, OpenClaw, and the rest

The 2026 crop of "personal AI agents" — Hermes Agent (Nous Research), OpenClaw and its wrappers (NemoClaw, etc.) — are impressive, but they're built around a different bet: an **always-on autonomous agent on a server/VPS** that you connect to a pile of services and let run 24/7. Kali makes the opposite, deliberate bet, and for an operator who works on real machines it's the better one.

**1. Security is the design, not an afterthought.**
OpenClaw got publicly burned for treating local trust casually — API keys ending up in `.bak` files, a websocket reachable by any browser tab, plugins executing with too little isolation. Kali's whole posture is a trust boundary:
- Keys live only in `~/.config/kali/settings.json`, never logged, never sent anywhere but the provider's own API.
- Your sudo password is never stored or shown to the model.
- **Nothing with side effects runs without your explicit approval** — and only **one command at a time**, every time.
- Self-written skills don't run in Kali's process: they're `ast`-parsed, statically screened, and executed in a **bubblewrap-isolated** child that must pass its own test before it's ever saved.
- An optional **foresight** gate predicts a command's blast radius and can hard-block catastrophic, irreversible actions even in auto mode.

**2. A reasoning partner with hands — not a runaway.**
Hermes and OpenClaw optimize for unattended autonomy. Kali optimizes for *you in the loop*: she goes and looks (read-only sensing needs no permission), reasons with you, and proposes changes you approve. That's the right shape for offensive-security and sysadmin work, where one wrong `dd` or `rm -rf` is unrecoverable.

**3. Native to offensive security.**
Neither Hermes nor OpenClaw is built for pentesting. Kali is: built-in security `audit`, network discovery (`scan_net`), Kali-Linux/NetHunter awareness, and a persona that talks like an operator, not a help desk.

**4. Self-improving — but gated.**
Hermes' headline feature is learning reusable skills as it works. Kali does this too (`skill_write` → tested in the sandbox → you Apply) — but every learned skill passes through the same safety model instead of being trusted by default.

**5. Lean on tokens and on your balance.**
Hermes brags about loading only the relevant skill to cut tokens. Kali matches that with **relevance-scoped memory** (only top-k memories injected per turn, never the whole store), **parallel-batched tool calls** (many lookups in one model round-trip), **trimmed tool-result history**, and prefix-cache-aware context handling — so a long session doesn't drain your API balance.

**6. It actually lives on *your* Linux box.**
Not a VPS daemon you SSH into — a real GTK4 app on your ThinkPad and your phone that drives the *actual* desktop (xdotool on X11, wtype on Wayland), reads your real files, and works offline-of-the-cloud for everything except the model call. One-line install, no Docker, no orchestration layer.

**Where it's deliberately different:** Kali is not a 24/7 unattended daemon, and she won't act behind your back or auto-learn skills without asking. That's the point. If you want an always-on autonomous operator for a fleet, run Hermes or OpenClaw. If you want a sharp, private, security-literate assistant that lives on your machine and never does anything destructive without you — that's Kali.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                       kali.py  (UI)                       │
│            GTK4 + libadwaita · chat, cards, voice         │
└───────────────┬───────────────────────┬──────────────────┘
                │                       │
      ┌─────────┴────────┐     ┌────────┴─────────┐   ┌──────────────┐
      │  kali_core.py    │     │  kali_persona.py │   │ kali_voice.py│
      │                  │     │                  │   │              │
      │ providers/router │     │ system prompt    │   │ STT (record  │
      │ 37 tools         │     │ + capabilities   │   │  + provider- │
      │ web / github     │     │ + rules          │   │  aware ASR)  │
      │ chat DB · audit  │     └──────────────────┘   │ TTS (Piper / │
      │ watcher · sudo   │                            │  espeak)     │
      └─────────┬────────┘                            └──────────────┘
                │
      ┌─────────┴─────────────────────────────────────┐
      │  kali_ext/  (optional sidecar — off by default)│
      │  memory · skills · sandbox · foresight · worker│
      └───────────────────────────────────────────────┘
```

---

## Install

**One-liner (recommended) — installs *and* updates:**

```bash
curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
```

Run it the first time to install; run the exact same line any time later to update. It's idempotent and smart about it:

- Detects Python 3.10+ (fails fast if missing) and installs GTK4 + libadwaita bindings (apt / pacman / dnf, auto-detected).
- Fetches the four Python modules (`kali.py`, `kali_core.py`, `kali_persona.py`, `kali_voice.py`) plus the optional `kali_ext/` sidecar.
- **Parse-checks every incoming file before it overwrites anything** — a syntax error in a download can never replace your working install.
- **Backs up your chat database** before each update, and reports the version it's moving you to (e.g. `updating Kali 0.7.0 → 0.8.0`).
- Installs optional desktop-control helpers (xdotool/wmctrl/scrot on X11; wtype/wlrctl/grim on Wayland; tesseract-ocr, libnotify-bin, playerctl), voice packages (espeak-ng, a recorder, a player, and best-effort Piper + a neural voice), and optionally Playwright + Chromium for browser automation.
- Drops a `kali` launcher in `~/.local/bin/` and a `.desktop` entry in your app grid.
- Optionally prompts for an API key (skippable; add it later in Settings).

**Time:** ~1–3 min first install; re-runs are a few seconds.

**Update later:** re-run the same one-liner — it only does what's missing or changed.

**Uninstall:** `~/.local/share/kali/install.sh --uninstall` (chat history kept).

### Removing a previous Oracle install

```bash
~/.local/share/kali/install.sh --remove-oracle
```

Stops/disables `oracle-ollama.service`, removes the old `oracle` launcher, desktop entry, and unit, and wipes `~/.local/share/oracle/` + `~/.config/oracle/`. Your chat history migrates to Kali if Kali has no DB yet. Your Kali install is untouched.

### Manual install

```bash
git clone https://github.com/the-priest/oracle5.git kali
cd kali
./install.sh
```

### Flags

| flag                 | what it does                                            |
| -------------------- | ------------------------------------------------------- |
| `--update`           | explicit update (same as the default install path)     |
| `--uninstall`        | remove Kali (chat history kept)                         |
| `--remove-oracle`    | remove the old Oracle install (Kali untouched)          |
| `--no-systemd`       | don't install the systemd unit for the background worker|
| `--no-helpers`       | skip optional desktop-control helpers                   |
| `--no-browser`       | skip Playwright + Chromium (browser automation)         |
| `--no-groq`          | don't install the groq library or prompt for a key      |
| `--no-voice`         | skip voice setup (espeak / Piper / mic packages)        |
| `--no-prompt`        | non-interactive (skips the API-key prompt)              |

### Env overrides

```bash
GROQ_API_KEY=gsk_...      ./install.sh    # preset a key, no prompt
KALI_REPO=user/fork  KALI_BRANCH=dev  ./install.sh
```

---

## Get an API key

Kali is multi-provider — you only need a key for the one(s) you want. Set the active provider and its key in **Settings → Backends**.

| Provider | Get a key | Notes |
| -------- | --------- | ----- |
| SiliconFlow | <https://cloud.siliconflow.com/account/ak> | Default. Big open models (DeepSeek, Qwen, Kimi) + SenseVoice speech-to-text |
| Groq | <https://console.groq.com/keys> | Fast, generous free tier. Whisper speech-to-text. Key looks like `gsk_...` |
| Novita AI | <https://novita.ai/settings/key-management> | Cheap GPU inference, many open models |
| GitHub Models | <https://github.com/settings/personal-access-tokens> | Free tier. Fine-grained PAT with `models:read` |
| Google AI Studio | <https://aistudio.google.com/apikey> | Gemini models, free tier |

Keys are stored locally in `~/.config/kali/settings.json` only — never anywhere but the provider's own API. Each provider's model dropdown lists the best models first; hit ⟳ to fetch its live catalogue once a key is set.

---

## What Kali can do on your system

**Sensing (read-only — runs freely, no permission needed):**
read files · list/find files (with size & mtime filters) · `quick_facts` (hostname/IP/uptime/load/free-space, cached) · system info · disk usage · processes · network status · recent downloads · check updates · service status · journal tail · security audit · network scan.

**Web & GitHub (read-only, headless — no browser needed):**
`web_search` (DuckDuckGo, returns ranked results + direct answers) · `web_read` (fetch any public page as clean text) · `github` (search repos/code, list a user's repos, read file trees and source, READMEs, releases, issues — public by default; set a token for private repos). For login-gated or JS-only sites there's also a full **Playwright browser** tool.

**Desktop control (actions — confirm-gated):**
launch apps · focus/close windows · type text · press keys · open URLs · screenshots & on-screen OCR · notifications · media control. Detects X11 vs Wayland and picks the right backend; on KDE Plasma it uses Spectacle/kdialog where they're better. Run `desktop_info` to see what's available on your box.

**Filesystem & shell (gated for anything that changes):**
make/copy/move/delete paths · run any shell command (proposed as a card, approved by you, one at a time, with sudo handled safely).

**Desktop-control helpers** are installed for you by `install.sh` (or `apt install` later). Browser automation needs Playwright (`pip install playwright && playwright install chromium`). Every tool reports what's missing rather than failing silently.

### Voice — talk to it, hear it back

- **Speech-to-text (dictation):** tap the mic, talk, tap to send. Provider-aware — it transcribes through **SiliconFlow's SenseVoiceSmall** or **Groq's Whisper**, auto-picking whichever key you have (pick explicitly in Settings → Voice). A **Test microphone** button records ~4s and shows the exact transcript or error.
- **Text-to-speech:** Kali reads replies aloud via **Piper** (neural, nicer) or **espeak-ng** (always-available fallback), with per-message play/pause/resume.

### Working smart (efficiency & behaviour)

- **Batched, parallel tool calls** — several read-only lookups in one model round-trip instead of one call each. Cheaper and faster.
- **Trimmed history** — old, already-used tool outputs are stubbed in the resent context so a long session doesn't re-bill huge blobs.
- **Urgency fast-path** — if you're clearly in a hurry, she drops the preamble and leads with the most likely fix.
- **`/panic`** — type it to jump straight to a batched system health sweep with a tight summary, no chit-chat.
- **Command de-duplication** (opt-in) — warns if you re-run the same command within 10 minutes.
- **Degraded-output fallback** (opt-in) — if a reply comes back empty/repetitive, she can hop to your next configured provider for the next turn.
- **Cached-sudo awareness** — if `sudo` is already authenticated this session, root commands run without re-prompting (toggle in Settings).

### Security audit checks

Firewall presence, SSH config hardening, open listeners, world-writable files, failed logins, pending updates, and more — scored by severity. All read-only.

### Background worker (optional)

A `systemd --user` service for the things that genuinely want to run headless: periodic system checks, memory consolidation, skill curation. Fully optional — Kali works identically without it.

---

## Chat history (ephemeral by default)

Conversations are stored in a local SQLite DB (`~/.local/share/kali/chats.db`). By default Kali opens a fresh chat each launch, discards empty placeholders, and bins chats idle longer than the retention window — all tunable in Settings. Your DB is backed up before every update.

---

## What Kali can NOT do

- **Run anything destructive without you.** Side-effecting commands are always proposed and approved; never auto-run. One at a time.
- **Be an always-on autonomous fleet agent.** That's a deliberate non-goal — Kali keeps you in the loop. (Want unattended autonomy? That's Hermes/OpenClaw territory.)
- **See your sudo password.** It's collected in a dialog, validated, never stored or shown to the model.
- **Reach private/authenticated content it hasn't been given access to.** Public web and public GitHub, yes; private repos only with a token you set.

---

## Optional extensions (`kali_ext/`)

All off by default; enable in Settings. Every hook is null-safe — a missing or broken sidecar can never take Kali down.

- **memory** — relevance-scoped recall (FTS5/keyword + recency + salience; optional embeddings). Injects only top-k per turn.
- **skills** — Kali writes, tests, and saves her own Python tools, gated by the sandbox + your approval.
- **sandbox** — bubblewrap-isolated, out-of-process execution of agent-written code.
- **foresight** — predicts a command's consequences/blast radius; can hard-block catastrophes.
- **worker** — the headless background companion described above.

---

## File layout

```
~/.local/share/kali/           code + data
  kali.py  kali_core.py  kali_persona.py  kali_voice.py
  kali_ext/                    optional sidecar
  chats.db                     conversation history
  backups/                     pre-update DB snapshots
  install.sh                   self-copy (for --uninstall / --update)
~/.config/kali/settings.json   settings + API keys (local only)
~/.local/bin/kali              launcher
```

---

## Tweaking the persona

For light, per-machine tweaks that survive upgrades, use **Settings → Persona → Custom addendum**. Direct edits to `kali_persona.py` get clobbered on the next `install.sh` run.

---

## Development

```bash
git clone https://github.com/the-priest/oracle5.git kali && cd kali

# run from source
python3 kali.py

# syntax check
python3 -m py_compile kali.py kali_core.py kali_persona.py kali_voice.py

# push changes (HTTPS remotes only)
git add -A && git commit -m "…" && git push
```

---

## License

MIT.

## Credits

Built by The Priest. Named for the goddess and the distro.
