<!--
title: Kali — AI security assistant for Linux (Oracle5)
description: Kali is an open-source AI security assistant that runs as a native GTK4 app on your own Linux machine. It drives your desktop, runs your shell with a hard safety floor, automates recon and pentest workflows, keeps a tamper-evident evidence ledger, connects external tools over MCP, writes and sandbox-tests its own tools, and talks and listens. Bring your own cloud LLM (SiliconFlow, Groq, Novita, GitHub Models, Google AI Studio). A private, security-native, self-hosted alternative to ChatGPT, Claude, Hermes and OpenClaw.
keywords: ai security assistant, kali linux ai, pentest ai, offensive security ai, llm agent, ai pentest tool, security automation, evidence ledger, model context protocol, mcp client, linux ai agent, nethunter ai, gtk4 assistant, self-hosted ai, local ai agent, cve enrichment, openclaw alternative, hermes alternative, voice ai agent, deepseek, siliconflow
-->

<div align="center">

# ⟁ KALI — an AI security assistant that lives on your machine

**A native Linux app that drives your desktop, runs your shell behind a hard safety floor, automates recon and pentest workflows, and keeps a tamper-evident record of everything it does. Bring your own cloud model.**

### Install in one line. Update with the same line. No Docker, no daemon, no cloud lock-in.

```bash
curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
```

<br>

*Offensive-security toolkit · drives your desktop · runs your shell (with a hard floor) · tamper-evident evidence ledger · MCP client · reads files · searches & fact-checks the web · writes & sandbox-tests its own tools · talks and listens.*

**Bring your own model** — SiliconFlow · Groq · Novita · GitHub Models · Google AI Studio
**`v3.8.3`** · GTK4 + libadwaita · X11 & Wayland · desktop **and** NetHunter mobile · MIT

</div>

---

## What Kali is

Kali is an **open-source AI security assistant for Linux**. It's not a website and not a daemon on someone else's server — it's a real GTK4 app on *your* box that wraps whichever large open model you choose and gives it hands: a desktop, a shell, a full offensive-security toolchain, and a memory.

The model is the brain you bring. **The value is everything built around it** — the tooling, the safety floor, the evidence trail, the integrations — which is exactly the layer a hosted chatbot can't give you. It does the work an operator actually needs: privately, on your hardware, with your choice of model, and with a hard rule that the one class of mistake that can't be undone always stops for you.

In one app it's a **security toolkit**, a **desktop agent**, a **sysadmin**, a **researcher/OSINT tool**, a **toolsmith** that writes its own sandboxed tools, and a **voice interface** — all local, all under your control.

---

## Why it stands out

Most "AI hacking tools" are a jailbroken model behind a prompt. Kali is the opposite bet: a disciplined, auditable operator's tool. Three things make it genuinely different.

**1. A tamper-evident evidence ledger.** Every command Kali runs is recorded to an append-only JSONL ledger — timestamp, command, exit code, duration, and the SHA-256 of its output, with the full output saved as a hashed artifact. `evidence_verify` re-hashes everything and proves nothing was altered after the fact. This is the difference between a chat log and a **defensible engagement deliverable** — the auditability that enterprise red-team platforms charge five and six figures for, local and free.

**2. A real offensive-security workflow, not exploit-spam.** Recon planning, a 59-tool inventory with exact install lines, scanner-output parsing for 20+ tools that **auto-chains into CVE intel** (NVD + CISA KEV + EPSS, ranked so the exploitable-in-the-wild ones surface first), methodology checklists, Nuclei template generation/validation, a findings self-check that flags false positives before they reach a report, and clean markdown reporting. It plans, parses, enriches and documents — and keeps a human on the trigger.

**3. It runs where you are.** A native desktop app *and* a tool that runs on a **NetHunter phone** — something no hosted swarm can be. Your data stays on the box; the only thing that leaves is the model call to the provider you picked.

Plus the things that make it pleasant to live with: it can **write and sandbox-test its own Python tools**, **connect external tool servers over MCP** (Model Context Protocol), **rewrite its own source** behind an approval diff, remember across sessions, and **talk and listen**.

---

## The safety floor (why you can hand it root)

Kali is **decisive by default and un-catastrophic by construction.**

- **Two speeds, you pick.** *Default:* read-only sensing runs free, and when you ask for something Kali just runs it, reads the result, and continues — no clicking through routine work. *Confirm every command (one toggle):* every side-effecting action becomes a card you approve one at a time.
- **The irreversible class always stops for a confirm — even in auto-run, even if the model was steered by something it read.** A *structural* detector (shlex-tokenised, `$IFS`/quote-normalised, recursing into `sh -c`/`eval`) force-confirms disk/filesystem wipes, recursive root/`$HOME` deletes, fork bombs and raw block-device writes. It sees through obfuscations a regex misses — `rm '-rf' /`, `rm${IFS}-rf${IFS}/`, `cd / && rm -rf *`, `find / -delete`, `bash -c "…"`, `echo … | base64 -d | sh` — while staying narrow enough that `nmap`, `nuclei`, `sqlmap` and `rm -rf ~/loot` never trip it. The full catch/ignore contract is pinned in the test suite.
- **Kali's own safety code can't be shell-stripped**, your **sudo password is never stored or shown to the model**, self-written code runs only in a **bubblewrap jail** after passing its own test, and a load-bearing **guardrail block is immutable by design** — enforced in code, not just asked of the model.
- **No exploit generation, ever.** Security tooling is propose-only / read-only; you drive the trigger, against scope you set.

> The guarantee isn't "asks every time" — it's that the one mistake that can't be undone keeps a human in the loop no matter what, and you can dial friction up to full-confirm whenever you want.

---

## How it compares

The honest version: Kali doesn't out-think a frontier model on a riddle — it runs whichever big open model you point it at. It wins on **what it's allowed to do, where it runs, who it answers to, and the trail it leaves.**

| | **Kali** | ChatGPT / Claude | Hermes / OpenClaw |
|---|:---:|:---:|:---:|
| Runs as a native app on **your** Linux desktop | ✅ GTK4 | ❌ cloud / CLI | ❌ VPS daemon |
| Drives your **actual** desktop (apps, windows, OCR) | ✅ X11 + Wayland | ❌ / sandbox | ❌ |
| **Security / pentest tooling built in** | ✅ first-class | ❌ often refuses | ❌ |
| **Tamper-evident evidence ledger** | ✅ | ❌ | ❌ |
| **Connect external tools over MCP** | ✅ safety-screened | ⚠️ varies | ❌ |
| **Writes & sandbox-tests its own tools** | ✅ | ❌ | ⚠️ plugins |
| Choose your **own** model provider | ✅ 5 providers | ❌ single vendor | ⚠️ |
| Your data leaves the box | **only the model call** | ✅ to the vendor | depends |
| **Irreversible** destruction without a confirm | **always blocked** | n/a | by design |
| Voice in **and** out | ✅ STT + TTS | ⚠️ app only | ❌ |
| Cost | your API key, pennies | subscription | infra + keys |

**Versus ChatGPT / Claude:** hosted brains owned by one company, behind guardrails that refuse much of real security work and ship every prompt to a datacenter you don't control. Kali keeps your data local, lets you pick the model, doesn't moralize over a port scan, and drives the *actual* desktop.

**Versus Hermes / OpenClaw:** these chase unattended 24/7 autonomy on a server — the wrong bet for irreversible work, where one bad `dd` from an unsupervised agent is unrecoverable. Kali is decisive on routine work but draws a hard line at the irreversible, and keeps you in the loop. Want an unsupervised swarm? Run those. Want a private, sharp, auditable security assistant on your own machine? Run Kali.

---

## Everything Kali can do

Read-only **sensing** runs freely. State-changing actions **run** directly (default) or become an approve-first **card** under *Confirm every command* — and the irreversible class always stops for a card regardless.

### 🛡️ Offensive security (the bread and butter)
- **`audit`** — local posture scan (firewall, SSH hardening, listeners, world-writable files, failed logins, pending updates), scored by severity. Read-only.
- **`scan_net`** — discovery on your own segment.
- **`tooling_check`** — inventories **59** offensive tools (recon, probing, port-scan, fuzzing, vuln, secrets, creds, AD) with exact install lines, aliases (`nxc`→`netexec`) and freshness nudges.
- **`pentest_plan`** — an **ordered** recon plan (passive first) with profiles `web · network · ad · api · full · quick` and a `stealth/normal/aggressive` intensity knob. Every step runs behind the gate.
- **`parse_output`** — turns raw scanner stdout into structured data for **20+ tools** (nmap, httpx, nuclei, naabu, masscan, subfinder, ffuf, feroxbuster, gobuster, katana, whatweb, wpscan, sslscan/testssl, smbmap, netexec, nikto, gitleaks, dalfox, arjun…), strips ANSI colour, and with `enrich_cves` **auto-chains into CVE intel** for every confirmed service+version.
- **`cve_lookup`** — NVD CVEs enriched with **CISA KEV** (exploited in the wild?) and **EPSS** (exploit probability), re-ranked **KEV → EPSS → CVSS**.
- **`nuclei_template`** — generate a structurally-valid Nuclei template from a simple spec, or validate one and get the exact list of problems before you run `nuclei -t`.
- **`reflect_findings`** — a self-check that flags unsupported, over-rated, hedged, host-less or duplicate findings *before* they reach a report. Cuts false positives.
- **`methodology`** · **`wordlist_find`** · **`cheatsheet`** · **`report_findings`** — PTES/OWASP/AD-killchain checklists, installed-wordlist finder, correct tool syntax, and clean markdown engagement reports.

> All security tooling is **propose-only / read-only**. Kali plans, inventories, parses, enriches and documents — it writes no exploit code and attacks nothing on its own.

### 🧾 Evidence & engagement record
- **`evidence_engagement`** — name/switch the case you're working; commands file under it.
- **`evidence_report`** — summary, integrity check, and a readable markdown ledger of everything run.
- **`evidence_verify`** — re-hash every captured artifact and prove nothing was altered after the fact.

### 🧩 External tools over MCP (optional)
Connect **Model Context Protocol** servers (the ecosystem of security MCP servers — nmap/sqlmap/ffuf/nuclei/ZAP wrappers and more). Discovered tools appear namespaced `mcp__<server>__<tool>` and are listed by `mcp_tools`. **Off by default and inert until you configure a server.** Every call's arguments are screened by the same safety floor (a catastrophic command in an argument is refused before it leaves the process), and every call is logged to the evidence ledger.

### 🕵️ OSINT & research
- **`osint_username`** / **`osint_lookup`** / **`social_read`** — public-profile and public-API readers (a hit means a public page exists, not that it's the same person).
- **`web_search`** · **`web_read`** — ranked search and headless clean-text page fetch.
- **`image_search`** — searches the web for images and **shows them inline in chat** (no API key). Kali can display pictures, not just link them — web results, OSINT profile photos, diagrams, or a screenshot it just took. Toggle `chat_render_images` off for OPSEC.
- **`web_verify`** — **anti-propaganda engine**: gathers independent sources, scores each for credibility, checks corroboration, and returns a confidence label instead of laundering state media or satire into fact.
- **`github`** — search/read repos, code, trees, READMEs, releases, issues (public; private with a token).
- **`browser`** — full **Playwright + Chromium** automation for login-gated or JS-only sites.

### 🖥️ System sensing (read-only)
`quick_facts` · `system_info` · `disk_usage` · `processes` · `network_status` · `service_status` · `journal_tail` · `recent_downloads` · `check_updates` · `path_info`.

### 🪟 Desktop control (confirm-gated)
`launch_app` · `list_apps` · `list_windows` · `focus_window` · `close_window` · `type_text` · `press_key` · `open_url` · `screenshot` · `read_screen` (on-screen **OCR**) · `media_control` · `notify`. Auto-detects **X11 vs Wayland** and picks the right backend.

### 📁 Files & shell (gated for anything that changes)
`read_file` · `list_dir` · `find_file` · `make_dir` · `copy_path` · `move_path` · `delete_path` · **`run`** any shell command (decisive by default, always force-confirmed for the catastrophic class, sudo handled safely). **Write any file** via a **diff card** you Apply.

### 🧠 Memory (optional, local)
`memory_remember` · `memory_recall` · `memory_forget` — relevance-scoped recall (keyword + recency + salience) that connects security paraphrases ("SQL injection" finds "SQLi") and injects only the **top-k** per turn. Nothing leaves the box.

### 🧰 Self-written tools (optional, sandboxed)
`skill_write` → Kali drafts a Python tool, it's `ast`-parsed and statically screened, run in a **bubblewrap** jail, and must pass its **own test** before you Apply it. Then it's callable as `skill_run`.

### ✍️ Self-modification
Kali can **rewrite its own source and persona** — proposed as a diff you Apply. Python is parse-checked, the original is backed up, writes are atomic, and the **guardrail block is immutable by design.**

### 🎙️ Voice — talk to it, hear it back
**STT** via SiliconFlow SenseVoice or Groq Whisper (auto-picked), with a *Test microphone* button. **TTS** via Piper (neural) or espeak-ng (fallback), with per-message play/pause.

### ⚡ Working smart
Batched parallel tool calls · trimmed history · context compression that always preserves findings · a collapsed **💭 Thoughts** reasoning panel · live status banner · `/panic` health sweep · urgency fast-path · degraded-output failover to your next provider.

### 🛰️ Background worker (optional)
A `systemd --user` service for genuinely-headless jobs (periodic checks, memory consolidation, skill curation). Fully optional — Kali works identically without it.

---

## Install

**One-liner (recommended) — installs *and* updates:**

```bash
curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
```

Run it once to install; run the exact same line any time to update. It's idempotent and careful:

- Detects Python 3.10+ and installs GTK4 + libadwaita (apt / pacman / dnf, auto-detected).
- Fetches the core modules plus the optional `kali_ext/` sidecar.
- **Parse-checks every incoming file before it overwrites anything** — a broken download can never replace your working install.
- **Backs up your chat database** before each update and reports the version move.
- Installs optional desktop-control helpers, voice packages, and optionally Playwright + Chromium.
- Drops a `kali` launcher in `~/.local/bin/` and a `.desktop` entry in your app grid.

**Time:** ~1–3 min first install; re-runs are seconds.
**Uninstall:** `~/.local/share/kali/install.sh --uninstall` (chat history kept).

### Manual install

```bash
git clone https://github.com/the-priest/oracle5.git kali
cd kali
./install.sh
```

### Flags

| flag | what it does |
| --- | --- |
| `--update` | explicit update (same as the default path) |
| `--uninstall` | remove Kali (chat history kept) |
| `--remove-oracle` | remove an old Oracle install (Kali untouched) |
| `--no-systemd` | skip the background-worker systemd unit |
| `--no-helpers` | skip optional desktop-control helpers |
| `--no-browser` | skip Playwright + Chromium |
| `--no-voice` | skip voice setup |
| `--no-prompt` | non-interactive (skips the API-key prompt) |

### Env overrides

```bash
GROQ_API_KEY=gsk_...   ./install.sh           # preset a key, no prompt
KALI_REPO=user/fork  KALI_BRANCH=dev  ./install.sh
```

---

## Get an API key

Kali is multi-provider — you only need a key for the one(s) you want. Set the active provider and key in **Settings → Backends**.

| Provider | Get a key | Notes |
| --- | --- | --- |
| **SiliconFlow** | <https://cloud.siliconflow.com/account/ak> | **Default.** Big open models (DeepSeek, Qwen, Kimi) + SenseVoice STT |
| Groq | <https://console.groq.com/keys> | Fast, generous free tier. Whisper STT. Key looks like `gsk_...` |
| Novita AI | <https://novita.ai/settings/key-management> | Cheap GPU inference, many open models |
| GitHub Models | <https://github.com/settings/personal-access-tokens> | Free tier. Fine-grained PAT with `models:read` |
| Google AI Studio | <https://aistudio.google.com/apikey> | Gemini models, free tier |

Keys live only in `~/.config/kali/settings.json` — never anywhere but the provider's own API.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                       kali.py  (UI)                       │
│            GTK4 + libadwaita · chat, cards, voice         │
└───────────────┬───────────────────────┬──────────────────┘
                │                       │
      ┌─────────┴────────┐   ┌──────────┴───────┐   ┌──────────────┐
      │  kali_core.py    │   │  kali_persona.py │   │ kali_voice.py│
      │ providers/router │   │ system prompt    │   │ STT + TTS    │
      │ 50+ agent tools  │   │ + rules          │   │ (provider-   │
      │ web · github     │   └──────────────────┘   │  aware ASR)  │
      │ chat DB · audit  │                          └──────────────┘
      └──┬────────┬───┬──┘
         │        │   │
   ┌─────┴───┐ ┌──┴───┴────────┐
   │kali_    │ │ kali_ledger.py│  tamper-evident evidence ledger
   │safety.py│ │ (JSONL+SHA256)│  (every command, hashed)
   │hard auto│ └───────────────┘
   │-run floor (structural, evasion-resistant, setting-independent)
   └─────────┘
         │
   ┌─────┴──────────────────────────────────────────────┐
   │  kali_ext/  (optional sidecar — off by default)     │
   │  memory · skills · sandbox · foresight · mcp · worker│
   └─────────────────────────────────────────────────────┘
```

Provider stack: **SiliconFlow/DeepSeek** primary with a **Groq** fallback chain; Novita, GitHub Models and Google AI Studio also selectable.

---

## What Kali can NOT do

- **Destroy your system or its storage on its own.** Disk/FS wipes, recursive root/`$HOME` deletes, fork bombs and raw block-device writes are *always* force-confirmed — even in decisive auto-run, even via quoting/`$IFS`/`bash -c` tricks.
- **Be an always-on autonomous fleet agent.** A deliberate non-goal — Kali keeps you in the loop.
- **See your sudo password**, or reach private content it hasn't been given a token for.
- **Write exploit code or attack a target on its own.** Security tooling is propose-only/read-only; you drive the trigger.

---

## Development

```bash
git clone https://github.com/the-priest/oracle5.git kali && cd kali

python3 kali.py                       # run from source

# offline test suite (stdlib only — no display, no keys, no network)
python3 tests/test_kali.py
#   covers: the structural safety floor (catastrophic + self-tamper, incl.
#   evasions), settings round-trip, the self-edit write path, the ChatStore
#   SQLite layer, the CVE auto-chain, the evidence ledger (incl. tamper
#   detection), Nuclei build/validate, findings reflection, smarter memory
#   recall, and the MCP argument safety screen.
```

For light, per-machine persona tweaks that survive upgrades, use **Settings → Persona → Custom addendum** — direct edits to `kali_persona.py` get clobbered on the next `install.sh` run.

---

## License

MIT.

## Credits

Built by **The Priest**.
