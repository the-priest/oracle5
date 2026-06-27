<!--
title: Oracle5 — Kali AI assistant
description: The ultimate personal AI assistant for Linux. Lives on your machine, drives your desktop, runs your shell (with permission), audits and pentests, writes its own tools, talks and listens. Multi-provider cloud LLM. The local-first, security-native alternative to ChatGPT, Claude, Hermes and OpenClaw.
keywords: ai assistant, kali linux, llm, voice control, ai agent, security audit, pentest ai, openclaw alternative, hermes alternative, chatgpt alternative, claude alternative, personal ai, linux agent, nethunter, gtk4, jarvis, self-modifying ai, local ai agent
-->

<div align="center">

# ⟁ KALI

### The personal AI that actually lives on your machine — and has hands on it.

**Install in one line. Updates with the same line. No Docker, no daemon, no cloud lock-in.**

```bash
curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
```

<br>

*Drives your desktop · runs your shell (only with your OK) · audits & pentests · reads your files · searches & verifies the web · writes and tests its own tools · talks and listens.*

**Multi-provider cloud AI** — SiliconFlow · Groq · Novita · GitHub Models · Google AI Studio
**`v2.3.0`** · GTK4 + libadwaita · X11 & Wayland · desktop + NetHunter mobile

</div>

---

## Why this is the one

ChatGPT and Claude are brilliant brains in someone else's building. Hermes and OpenClaw are autonomous daemons you babysit on a VPS. **Kali is the only one that's a real app on *your* Linux box, with real hands on *your* machine, that does the work an operator actually needs — privately, without a corporate leash, and without ever doing anything destructive behind your back.**

It is, in one app:

- a **chat assistant** with a sharp, loyal, no-filler persona;
- an **agent** that drives your actual desktop (apps, windows, keystrokes, screenshots, OCR);
- a **sysadmin** that reads system state, tails your journal, checks services and updates;
- an **offensive-security toolkit** — recon planning, tooling inventory, CVE intel, output parsing, methodology, wordlists, cheatsheets, engagement reports;
- a **researcher** that searches, reads pages, browses GitHub, and cross-checks sources for propaganda;
- a **toolsmith** that writes, tests and saves its own Python tools in a sandbox;
- and a **voice interface** that listens and talks back.

All of it on one machine, under one operator — you — with a hard rule that **nothing with side effects ever runs without your explicit, one-at-a-time approval.**

---

## Kali vs. everything else

The honest version. Kali doesn't claim to out-think a frontier model on a riddle — it runs whichever big open model you point it at. It wins on **what it's allowed to do, where it runs, who it answers to, and what it's built for.**

| | **Kali** | ChatGPT | Claude | Hermes Agent | OpenClaw |
|---|:---:|:---:|:---:|:---:|:---:|
| Runs as a real app on **your** Linux desktop | ✅ GTK4 native | ❌ cloud/app | ⚠️ Claude Code is CLI | ❌ VPS daemon | ❌ VPS daemon |
| Drives your **actual** desktop (apps, windows, keys, OCR) | ✅ X11 + Wayland | ❌ | ⚠️ VM/sandbox | ❌ | ❌ |
| Reads **your real files** directly | ✅ | ⚠️ uploads only | ⚠️ CLI scoped | ✅ | ✅ |
| Runs shell on your box | ✅ propose-gated | ⚠️ sandbox only | ✅ CLI | ✅ unattended | ✅ unattended |
| **Security / pentest tooling built in** | ✅ first-class | ❌ refuses | ❌ refuses | ❌ | ❌ |
| Refuses legitimate offensive-sec work | **never** | often | often | n/a | n/a |
| **Writes & tests its own tools** (sandboxed) | ✅ | ❌ | ❌ | ✅ trusted | ⚠️ plugins |
| **Rewrites its own source & persona** | ✅ (you Apply) | ❌ | ❌ | ❌ | ❌ |
| Choose your **own** LLM provider | ✅ 5 providers | ❌ OpenAI only | ❌ Anthropic only | ⚠️ | ⚠️ |
| Your data leaves the box | **only the model call** | ✅ to OpenAI | ✅ to Anthropic | depends | depends |
| Voice in **and** out | ✅ STT + TTS | ⚠️ app only | ❌ | ❌ | ❌ |
| Destructive action without asking | **impossible** | n/a | possible in CLI | by design | by design |
| Cost | your API key, pennies | subscription | subscription | infra + keys | infra + keys |

**Versus ChatGPT / Claude.** They're hosted brains owned by one company, wrapped in guardrails that will refuse half of real security work and ship every prompt to a datacenter you don't control. Their agent modes (Operator, Code Interpreter, Claude Code, Computer Use) are real and good — but they're cloud-bound, single-vendor, and not built for an operator who wants a private, security-literate partner on their own hardware. Kali keeps your data on the box, lets you pick the model, never moralizes at you over a port scan, and drives the *actual* desktop instead of a sandboxed clone.

**Versus Hermes / OpenClaw.** These chase **unattended 24/7 autonomy** on a server. That's the opposite bet, and the wrong one for irreversible work — one bad `dd` or `rm -rf` from an unsupervised agent is unrecoverable. OpenClaw also got publicly burned for sloppy local trust (keys in `.bak` files, a websocket any browser tab could reach, plugins with too little isolation). Kali's entire posture is a trust boundary: read-only sensing runs free, **everything with consequences is proposed and approved one command at a time**, self-written code runs only in a bubblewrap jail after passing its own test, and an optional **foresight** gate can hard-block catastrophes outright.

**Where Kali is deliberately different:** it is *not* a fire-and-forget fleet daemon and it will *not* auto-learn skills or act behind your back. That restraint is the product. Want an unsupervised swarm? Run Hermes. Want a private, sharp, security-native assistant that lives on your machine and never nukes your disk without you? **Run Kali.**

---

## Everything Kali can do

A complete map. Read-only **sensing** runs freely, no permission needed. Anything that **changes state** is proposed as a card with a risk level and a **Run/Apply** button — approved by you, one at a time.

### 🛡️ Offensive security (the bread and butter)
- **`audit`** — local security posture scan: firewall, SSH hardening, open listeners, world-writable files, failed logins, pending updates, and more, scored by severity. Read-only.
- **`scan_net`** — network discovery on your own segment.
- **`tooling_check`** — inventories **59** offensive tools across recon, probing, port scanning, fuzzing, vuln scanning, secrets, creds and AD; gives the exact install line (apt/go/pipx), known aliases (`nxc`→`netexec`), and freshness nudges (nuclei templates, SecLists/rockyou).
- **`pentest_plan`** — builds an **ordered recon plan** (passive/enumeration first) with profiles `web · network · ad · api · full · quick` and an **intensity** knob (`stealth/normal/aggressive`) that tunes nmap timing, nuclei rate-limits and ffuf threads. Every step is a *proposed* command behind the Run gate — nothing fires on its own.
- **`parse_output`** — turns raw scanner stdout into clean structured data (hosts, ports, services, versions, endpoints, findings) for **20+ tools**: nmap (incl. NSE hits), httpx, nuclei, naabu, masscan, subfinder, ffuf, feroxbuster, gobuster, katana, whatweb, wpscan, sslscan/testssl, smbmap, netexec, nikto, gitleaks, dalfox, arjun, and more. With `enrich_cves`, it **auto-chains into CVE intel** — every confirmed service+version in the scan is looked up (NVD + CISA KEV + EPSS) and a severity-ranked `cve_enrichment` block is attached, so one call turns a scan paste into "here are the services *and* the exploitable, known-in-the-wild CVEs."
- **`cve_lookup`** — pulls CVEs from **NVD**, then enriches each with **CISA KEV** (exploited in the wild?) and **EPSS** (exploit probability), and re-ranks **KEV → EPSS → CVSS** so the genuinely dangerous ones surface first.
- **`methodology`** — phased testing checklists grounded in **PTES / OWASP WSTG / the AD kill-chain** (web, network, ad, api, mobile, wifi, recon, priv-esc, cloud).
- **`wordlist_find`** — locates the wordlists actually installed on your box (SecLists included), with the canonical pick per task.
- **`cheatsheet`** — correct command syntax for the tools you reach for (nmap, ffuf, nuclei, httpx, netexec, hydra, hashcat, john, sqlmap, kerbrute, ssh-tunnels, curl, …).
- **`report_findings`** — aggregates structured findings into a clean markdown **engagement report**: severity rollup, sorted table, per-finding detail.

> All security tooling is **propose-only / read-only**. Kali plans, inventories, parses, enriches and documents — it writes no exploit code and attacks nothing. Real recon/attack commands run only through the approve-before-run gate, against scope **you** set.

### 🕵️ OSINT & research
- **`osint_username`** — checks a handle across public profile sites (a hit means a public page exists — *not* that it's the same person; always confirm).
- **`osint_lookup`** / **`social_read`** — platform-aware public readers; public pages and public APIs only, no login, no gated scraping.
- **`web_search`** — DuckDuckGo, ranked results plus direct answers.
- **`web_read`** — fetch any public page as clean text, headless (no browser needed).
- **`web_verify`** — **anti-propaganda engine**: gathers several *independent* sources, scores each for credibility (primary / reputable / community / state-media / satire), checks whether they actually corroborate, and returns a confidence label — flagging state media and satire instead of laundering them into fact. Separates confirmed / inferred / unknown.
- **`github`** — search repos & code, list a user's repos, read file trees, source, READMEs, releases and issues (public by default; private with a token).
- **`browser`** — full **Playwright + Chromium** automation for login-gated or JS-only sites.

### 🖥️ System sensing (read-only, runs freely)
`quick_facts` (hostname/IP/uptime/load/free-space, cached) · `system_info` · `disk_usage` · `processes` · `network_status` · `service_status` · `journal_tail` · `recent_downloads` · `check_updates` · `path_info`.

### 🪟 Desktop control (confirm-gated actions)
`launch_app` · `list_apps` · `list_windows` · `focus_window` · `close_window` · `type_text` · `press_key` · `open_url` · `screenshot` · `read_screen` (on-screen **OCR**) · `media_control` · `notify`. Auto-detects **X11 vs Wayland** and picks the right backend (xdotool/wmctrl/scrot vs wtype/wlrctl/grim); prefers Spectacle/kdialog on KDE Plasma. `desktop_info` shows what's available on your box.

### 📁 Files & shell (gated for anything that changes)
`read_file` · `list_dir` · `find_file` (size & mtime filters) · `make_dir` · `copy_path` · `move_path` · `delete_path` · **`run`** any shell command (proposed as a card, approved by you, one at a time, with sudo handled safely). **Write/create any file** — a document, report, script or config — via a **diff card** you Apply; multi-line content is parsed robustly and shown as a real diff before a byte hits disk.

### 🧠 Memory (optional, local)
`memory_remember` · `memory_recall` · `memory_forget` — relevance-scoped recall (FTS5/keyword + recency + salience, optional embeddings) that injects only the **top-k** memories per turn, never the whole store. Nothing leaves the box.

### 🧩 Self-written tools (optional, sandboxed)
`skill_write` → Kali drafts a Python tool, it's `ast`-parsed and statically screened, executed in a **bubblewrap** jail, and must pass its **own test** before you Apply it. From then on it's callable as `skill_run`. `skill_list` shows the library.

### ✍️ Self-modification
Kali can **rewrite its own source and persona** — propose the full new file as a diff, you click Apply. Python is parse-checked before writing, the original is backed up, writes are atomic, and a load-bearing **guardrail block is immutable by design**. Persona edits reload live on the next reply; code edits load on relaunch.

### 🎙️ Voice — talk to it, hear it back
- **Speech-to-text:** tap the mic, talk, tap to send. Provider-aware — transcribes through **SiliconFlow SenseVoiceSmall** or **Groq Whisper**, auto-picking whichever key you have. A **Test microphone** button records ~4s and shows the exact transcript or error.
- **Text-to-speech:** reads replies aloud via **Piper** (neural) or **espeak-ng** (always-available fallback), with per-message play/pause/resume.

### ⚡ Working smart
- **Batched, parallel tool calls** — many read-only lookups in one model round-trip.
- **Trimmed history** — already-used tool outputs are stubbed in resent context so a long session doesn't re-bill huge blobs.
- **Context compression (headroom)** — bulky output is crushed before it reaches the model; findings (errors, ports, CVEs, creds) are always preserved.
- **Reasoning panel** — a collapsed **💭 Thoughts** expander when the model exposes its chain-of-thought; kept out of the reply, out of TTS, out of replayed history.
- **Live status banner** — tells you what it's *doing* ("running nmap…", "cross-checking sources…").
- **`/panic`** — one word jumps straight to a batched system health sweep with a tight summary, no chit-chat.
- **Urgency fast-path** — if you're clearly in a hurry, it drops preamble and leads with the most likely fix.
- **Command de-dup** (opt-in) · **degraded-output failover** to your next provider (opt-in) · **cached-sudo awareness**.

### 🛰️ Background worker (optional)
A `systemd --user` service for the genuinely-headless jobs: periodic system checks, memory consolidation, skill curation. Fully optional — Kali works identically without it.

---

## The safety model (why you can hand it root)

Kali's restraint is the feature. The trust boundary:

- **Read-only sensing runs free; everything with consequences is proposed and approved — one command at a time, every time.**
- **Your sudo password is never stored, logged, or shown to the model.** It's collected in a dialog, validated, and used to cache the credential for the session only.
- **API keys live only in `~/.config/kali/settings.json`** — never logged, never sent anywhere but the provider's own API.
- **Self-written code never runs in Kali's process.** It's `ast`-parsed, statically screened, and executed in a **bubblewrap-isolated** child that must pass its own test before it can be saved.
- **Optional foresight gate** predicts a command's blast radius and can hard-block catastrophic, irreversible actions even in auto mode.
- **The persona guardrail block is immutable** — Kali can edit everything else about itself, but not that.
- **Robust tool parsing** — a multi-line document or a stray character in a tool call can't silently vanish: it's recovered and rendered as a real diff card, or you're told it didn't, so Kali never claims an action happened when it didn't.

---

## Install

**One-liner (recommended) — installs *and* updates:**

```bash
curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
```

Run it the first time to install; run the exact same line any time later to update. It's idempotent and smart about it:

- Detects Python 3.10+ (fails fast if missing) and installs GTK4 + libadwaita bindings (apt / pacman / dnf, auto-detected).
- Fetches the four modules (`kali.py`, `kali_core.py`, `kali_persona.py`, `kali_voice.py`) plus the optional `kali_ext/` sidecar.
- **Parse-checks every incoming file before it overwrites anything** — a syntax error in a download can never replace your working install.
- **Backs up your chat database** before each update, and reports the version it's moving you to (e.g. `updating Kali 0.7.0 → 0.8.0`).
- Installs optional desktop-control helpers (xdotool/wmctrl/scrot on X11; wtype/wlrctl/grim on Wayland; tesseract-ocr, libnotify-bin, playerctl), voice packages (espeak-ng, a recorder, a player, best-effort Piper + a neural voice), and optionally Playwright + Chromium for browser automation.
- Drops a `kali` launcher in `~/.local/bin/` and a `.desktop` entry in your app grid.
- Optionally prompts for an API key (skippable; add it later in Settings).

**Time:** ~1–3 min first install; re-runs are a few seconds.
**Uninstall:** `~/.local/share/kali/install.sh --uninstall` (chat history kept).

### Removing a previous Oracle install

```bash
~/.local/share/kali/install.sh --remove-oracle
```

Stops/disables `oracle-ollama.service`, removes the old `oracle` launcher, desktop entry and unit, and wipes `~/.local/share/oracle/` + `~/.config/oracle/`. Your chat history migrates to Kali if Kali has no DB yet. Your Kali install is untouched.

### Manual install

```bash
git clone https://github.com/the-priest/oracle5.git kali
cd kali
./install.sh
```

### Flags

| flag | what it does |
| --- | --- |
| `--update` | explicit update (same as the default install path) |
| `--uninstall` | remove Kali (chat history kept) |
| `--remove-oracle` | remove the old Oracle install (Kali untouched) |
| `--no-systemd` | don't install the systemd unit for the background worker |
| `--no-helpers` | skip optional desktop-control helpers |
| `--no-browser` | skip Playwright + Chromium (browser automation) |
| `--no-groq` | don't install the groq library or prompt for a key |
| `--no-voice` | skip voice setup (espeak / Piper / mic packages) |
| `--no-prompt` | non-interactive (skips the API-key prompt) |

### Env overrides

```bash
GROQ_API_KEY=gsk_...      ./install.sh    # preset a key, no prompt
KALI_REPO=user/fork  KALI_BRANCH=dev  ./install.sh
```

---

## Get an API key

Kali is multi-provider — you only need a key for the one(s) you want. Set the active provider and its key in **Settings → Backends**.

| Provider | Get a key | Notes |
| --- | --- | --- |
| **SiliconFlow** | <https://cloud.siliconflow.com/account/ak> | **Default.** Big open models (DeepSeek, Qwen, Kimi) + SenseVoice speech-to-text |
| Groq | <https://console.groq.com/keys> | Fast, generous free tier. Whisper speech-to-text. Key looks like `gsk_...` |
| Novita AI | <https://novita.ai/settings/key-management> | Cheap GPU inference, many open models |
| GitHub Models | <https://github.com/settings/personal-access-tokens> | Free tier. Fine-grained PAT with `models:read` |
| Google AI Studio | <https://aistudio.google.com/apikey> | Gemini models, free tier |

Keys are stored locally in `~/.config/kali/settings.json` only — never anywhere but the provider's own API. Each provider's model dropdown lists the best models first; hit ⟳ to fetch its live catalogue once a key is set.

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
      │ 47+ tools        │     │ + capabilities   │   │  + provider- │
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

Provider stack: **SiliconFlow/DeepSeek** primary with a **Groq** fallback chain; Novita, GitHub Models and Google AI Studio also selectable.

---

## Optional extensions (`kali_ext/`)

All off by default; enable in Settings. Every hook is null-safe — a missing or broken sidecar can never take Kali down.

- **memory** — relevance-scoped recall (FTS5/keyword + recency + salience; optional embeddings). Injects only top-k per turn.
- **skills** — Kali writes, tests and saves its own Python tools, gated by the sandbox + your approval.
- **sandbox** — bubblewrap-isolated, out-of-process execution of agent-written code.
- **foresight** — predicts a command's consequences/blast radius; can hard-block catastrophes.
- **worker** — the headless background companion described above.

---

## Chat history (ephemeral by default)

Conversations are stored in a local SQLite DB (`~/.local/share/kali/chats.db`). By default Kali opens a fresh chat each launch, discards empty placeholders, and bins chats idle longer than the retention window — all tunable in Settings. Your DB is backed up before every update.

---

## What Kali can NOT do

- **Run anything destructive without you.** Side-effecting commands are always proposed and approved; never auto-run. One at a time.
- **Be an always-on autonomous fleet agent.** A deliberate non-goal — Kali keeps you in the loop. (Want unattended autonomy? That's Hermes/OpenClaw territory.)
- **See your sudo password.** Collected in a dialog, validated, never stored or shown to the model.
- **Reach private/authenticated content it hasn't been given access to.** Public web and public GitHub, yes; private repos only with a token you set.
- **Write exploit code or attack a target on its own.** Security tooling is propose-only/read-only; you drive the trigger.

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

Built by **The Priest**. Named for the goddess and the distro.
