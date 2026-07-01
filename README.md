<!--
title: Kali — the AI security operator that runs on your own machine (Oracle5)
description: Kali is an open-source AI security operator that runs as a native GTK4 desktop app on your own Linux box. You bring a large language model (SiliconFlow, Groq); Kali gives it hands — a full offensive-security toolchain, code & dependency auditing, a tamper-evident evidence ledger, real web browsing through Brave, external tools over MCP, a memory, and a voice — all behind a hard structural safety floor and under your control. A private, security-native, self-hosted alternative to cloud AI assistants.
keywords: ai security operator, kali linux ai, ai pentest tool, offensive security ai, llm security agent, self-hosted ai, local ai agent, evidence ledger, sast sca ai, cve enrichment, kev epss, model context protocol, mcp client, nethunter ai, gtk4 app, deepseek, siliconflow, brave automation, red team assistant
-->

<div align="center">

```
        ⟁   ⟁   ⟁
     ██╗  ██╗ █████╗ ██╗     ██╗
     ██║ ██╔╝██╔══██╗██║     ██║
     █████╔╝ ███████║██║     ██║
     ██╔═██╗ ██╔══██║██║     ██║
     ██║  ██╗██║  ██║███████╗██║
     ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝
    t h e   d r a g o n   o n   y o u r   m a c h i n e
```

# ⟁ KALI

### An AI security operator that lives on **your** machine — not someone else's cloud.

*You bring the model. Kali brings the hands, the toolchain, the discipline, and the paper trail.*

<br>

![version](https://img.shields.io/badge/version-4.2.0-c4cad4?style=for-the-badge&labelColor=0d0f12)
![license](https://img.shields.io/badge/license-MIT-2ee65f?style=for-the-badge&labelColor=0d0f12)
![platform](https://img.shields.io/badge/Linux-X11%20%7C%20Wayland-9aa4b2?style=for-the-badge&logo=linux&logoColor=white&labelColor=0d0f12)
![python](https://img.shields.io/badge/python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white&labelColor=0d0f12)

![toolkit](https://img.shields.io/badge/GTK4-libadwaita-4a86cf?style=for-the-badge&labelColor=0d0f12)
![mobile](https://img.shields.io/badge/runs%20on-NetHunter-c4cad4?style=for-the-badge&labelColor=0d0f12)
![ledger](https://img.shields.io/badge/evidence-tamper--evident-2ee65f?style=for-the-badge&labelColor=0d0f12)
![lock-in](https://img.shields.io/badge/cloud%20lock--in-none-9aa4b2?style=for-the-badge&labelColor=0d0f12)

</div>

<br>

---

<div align="center">

## ⚡ Install — and update — in one line

</div>

```bash
curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
```

No Docker. No daemon. No account. No cloud. Paste it once to install; paste the **exact same line** any time to update. It auto-detects your distro, installs what it needs, parse-checks every file before it touches your disk, backs up your chat history, and drops a launcher in your app grid. About a minute from `curl` to a dragon on your desktop.

<br>

---

## What Kali is

Kali is a **native Linux desktop application** that turns a large language model into a working **security operator** — one that runs entirely on your own hardware and answers only to you.

A language model on its own is just a brain in a jar. It can *talk* about a port scan, but it can't run one. It can't see your desktop, touch your files, remember yesterday's engagement, or prove what it did. **Kali is the body around that brain.** You supply the model through an API key you own; Kali supplies everything that turns "a clever chatbot" into "an operator who can actually do the work — and hand you a receipt for every move."

That distinction is the whole point:

- **It is not a website.** Nothing runs on someone else's server. The app runs on your box; the only thing that ever leaves is a single API call to the model provider *you* picked.
- **It is not a jailbroken chatbot.** It doesn't beg a hosted model to ignore its rules. It's a purpose-built operator's tool with real engineering around it — a structural safety floor, a cryptographic evidence trail, a full toolchain.
- **It is yours.** Open source, MIT-licensed. Your data, your keys, your machine, your rules. Choose the model. Fork the code. Own the whole thing.

Where a hosted assistant refuses half of real security work and ships every prompt to a datacenter you don't control, Kali keeps your work local, doesn't moralize over a scan you're authorized to run, and leaves a tamper-evident record you can put in front of a client.

> **In one sentence:** every "AI hacking tool" is a chatbot behind a prompt. Kali is the opposite — a disciplined, auditable operator's tool that runs on your hardware, draws a hard line at the one mistake you can't undo, and never forgets what it touched.

<br>

---

## What you can use it for

Kali isn't a single-trick tool. It's one app that covers a security operator's whole day. Here's what that looks like in practice.

### 🎯 Run a penetration test, end to end
Point Kali at an authorized target and walk the full engagement without leaving the window. It inventories your installed tooling, builds an **ordered recon plan** (passive first, then active), proposes each command for you to approve, parses the raw output into clean findings, and **auto-ranks the CVEs by what's actually being exploited in the wild** (NVD + CISA KEV + EPSS). When you get in, it writes the **reproducible "how we got in" report section straight from the evidence ledger** — backed by the real hashed commands that ran, not a freeform retelling. It can **benchmark itself** against known-vulnerable practice targets (Juice Shop, DVWA, WebGoat) and score the run — precision, recall, coverage — so its performance is a reproducible number you can put next to any other tool's. It maintains a live **engagement graph** (hosts, services, footholds) that populates itself from the scans it runs, enforces your authorised **scope** before touching a target, and records everything to a tamper-evident trail you can hand to the client as proof of work.

### 🔍 Audit your own code and dependencies
Give it a repo. It detects the languages, lockfiles and IaC, then drives the industry-standard scanners — **Semgrep, Bandit, gitleaks, OSV-Scanner, Trivy, pip-audit, `npm audit`** — and does the part those tools *don't*: it **normalizes ten scanners into one finding list and triages across them**, so two tools flagging the same issue collapse into one *corroborated* finding, the weak ones get flagged for review, and you get a clean, prioritized list with concrete fixes instead of ten different JSON dumps.

### 🛡️ Harden a machine
Ask for a posture check and it runs a read-only local audit — firewall, SSH hardening, open listeners, world-writable files, failed logins, pending updates — scored by severity, with the reasoning shown. No guessing: facts about your system are read live with a tool, never invented.

### 🕵️ Investigate a footprint
Check your own exposure or research a handle across public profile sites and public APIs, fetch and clean web pages, and fact-check claims through an **anti-propaganda engine** that scores sources for credibility and corroboration instead of laundering state media or satire into "fact."

### 🖥️ Use it as a hands-on desktop agent
It drives your **actual desktop** — launches apps, manages windows, types, presses keys, reads what's on screen with OCR — and runs your **shell** behind a hard safety floor. It's a sysadmin and a pair of hands, not just a chat box.

### 📱 Take it into the field
The same tool runs on a **Kali NetHunter phone** — a real operator's assistant in your pocket, something no hosted swarm can ever be.

### 🧩 Bend it to your workflow
It **writes and sandbox-tests its own Python tools** when you need a capability it doesn't have, **connects external tool servers over MCP**, **remembers across sessions**, and **talks and listens** so you can work hands-free.

<br>

---

## How it works

Three pieces, and understanding them is understanding Kali.

**1 — You bring the brain.** Kali is model-agnostic. You point it at a large open model through a provider you choose (SiliconFlow with DeepSeek by default, Groq as a fast fallback) using your own API key. The intelligence is rented by the call, for pennies; nothing is baked in or locked down.

**2 — Kali is the body.** Around that model sits the part that actually matters and that a hosted chatbot can never give you: a full offensive-security toolchain, code and dependency auditing, real web browsing, desktop and shell control, a local memory, a voice, and external-tool integration. This is where the value lives.

**3 — Two things keep it honest.** A **structural safety floor** guarantees the one irreversible class of mistake always stops for a human, no matter how the model was steered. A **tamper-evident evidence ledger** records every command and hashes its output, so you can prove exactly what happened. Decisive on routine work, un-catastrophic by construction, auditable end to end.

<br>

---

## Everything Kali can do

Read-only **sensing** runs freely. Anything that changes your system either runs directly (default) or becomes an approve-first card (*Confirm every command* mode) — and the irreversible class always stops for a card regardless. The lists below are grouped by what you'd actually reach for.

<details>
<summary><b>🛡️ Offensive security</b> — recon, scanning, CVE intel, exploitation write-ups</summary>

<br>

- **`audit`** — local posture scan (firewall, SSH, listeners, world-writable files, failed logins, updates), scored by severity. Read-only.
- **`scan_net`** — discovery on your own segment.
- **`tooling_check`** — inventories **59** offensive tools (recon, probing, port-scan, fuzzing, vuln, secrets, creds, AD) with exact install lines, command aliases, and freshness nudges.
- **`pentest_plan`** — an **ordered** recon plan (passive first) with profiles `web · network · ad · api · full · quick` and a `stealth / normal / aggressive` intensity knob. Every step runs behind the approval gate.
- **`parse_output`** — turns raw scanner output into structured findings for **20+ tools** (nmap, httpx, nuclei, naabu, masscan, subfinder, ffuf, feroxbuster, gobuster, katana, whatweb, wpscan, sslscan/testssl, smbmap, netexec, nikto, gitleaks, dalfox, arjun…), strips ANSI, and **auto-chains into CVE intel** for every confirmed service+version.
- **`cve_lookup`** — NVD CVEs enriched with **CISA KEV** (exploited in the wild?) and **EPSS** (exploit probability), re-ranked **KEV → EPSS → CVSS**.
- **`nuclei_template`** — generate a structurally-valid Nuclei template from a simple spec, or validate one and get the exact list of problems before you run it.
- **`reflect_findings`** — a false-positive self-check that flags unsupported, over-rated, hedged, host-less or duplicate findings *before* they reach a report.
- **`attack_writeup`** — the **exploitation narrative**: a reproducible account of how access was obtained, pulled straight from the evidence ledger so the steps are backed by real hashed commands; secrets auto-redacted. Documents an authorized, already-executed path — it writes no exploit code.
- **`methodology` · `wordlist_find` · `cheatsheet` · `report_findings`** — PTES / OWASP / AD-killchain checklists, installed-wordlist finder, correct tool syntax, and clean markdown engagement reports.

*All offensive tooling is propose-only / read-only. Kali plans, inventories, parses, enriches, and documents — it writes no exploit code and attacks nothing on its own.*

</details>

<details>
<summary><b>🔍 Code &amp; dependency audit</b> — SAST, SCA, secrets, cross-tool triage</summary>

<br>

The static half of the job — finding vulnerabilities in source, dependencies, secrets and IaC. Safe on your own code; it drives standard installed scanners and makes sense of them.

- **`code_tooling_check`** — inventories the code-security stack (SAST / SCA / secrets / IaC / container / web-DAST) with install lines for the gaps.
- **`code_scan_plan`** — auto-detects languages, lockfiles and IaC in a path and builds an **ordered, proposed** scan plan (Semgrep, Bandit, OSV-Scanner, gitleaks, pip-audit, `npm audit`…) with JSON flags set. Runs nothing — every step goes through the approval gate.
- **`parse_scan`** — normalizes raw JSON from **Semgrep, Bandit, gitleaks, trufflehog, OSV-Scanner, Trivy, pip-audit, npm audit, retire.js, Nuclei** into one unified finding schema.
- **`triage_findings`** — the differentiator: **dedups across scanners** (two tools on the same CVE+package or `file:line:rule` collapse into one *corroborated* finding recording which agreed), maps every severity dialect onto one scale, sorts worst-first, and flags the low-confidence ones for manual review.
- **`remediation_hint`** — a short, standard, **non-exploit** fix pointer per finding (upgrade to the fixed version, or the CWE-class fix).

</details>

<details>
<summary><b>🧾 Evidence &amp; engagement record</b> — the tamper-evident paper trail</summary>

<br>

Every command Kali runs is recorded automatically to an append-only JSONL ledger — timestamp, command, exit code, duration, and the **SHA-256** of its output, with full output saved as a hashed artifact.

- **`evidence_engagement`** — name/switch the case you're working; commands file under it.
- **`evidence_report`** — summary, integrity check, and a readable markdown ledger of everything run.
- **`evidence_verify`** — re-hash every captured artifact and prove nothing was altered after the fact.

*This is the difference between a chat log and a defensible engagement deliverable.*

</details>

<details>
<summary><b>🌐 Web, search &amp; OSINT</b> — real browsing, fact-checking, footprinting</summary>

<br>

- **`browser`** — full **Playwright** automation that drives **Brave** when installed: Shields kill ads and trackers, cookie/consent walls are auto-dismissed, and the worst hosts are blocked at the network layer, so pages actually load and read. Falls back to bundled Chromium, and to headless HTTP for read-only fetches. goto, read, click, fill, submit, scroll, links, screenshot — and it self-heals a dead session instead of getting stuck.
- **`web_search` · `web_read`** — ranked search and headless clean-text page fetch.
- **`web_verify`** — anti-propaganda engine: gathers independent sources, scores each for credibility, checks corroboration (including high-signal anchors like CVE IDs and versions), and returns a confidence label instead of laundering state media or satire into fact.
- **`osint_username` · `osint_lookup` · `social_read`** — public-profile and public-API readers (a hit means a public page exists, not that it's the same person).
- **`image_search`** — searches the web for images and **shows them inline in chat** (no API key). Toggle off for OPSEC.
- **`github`** — search/read repos, code, trees, READMEs, releases, issues (public; private with a token).

</details>

<details>
<summary><b>🖥️ Desktop &amp; system control</b> — hands on your actual machine</summary>

<br>

**System sensing (read-only, read live — never guessed):** `quick_facts` · `system_info` (real RAM/CPU/OS) · `disk_usage` · `processes` · `network_status` · `service_status` · `journal_tail` · `recent_downloads` · `check_updates` · `path_info`.

**Desktop control (confirm-gated):** `launch_app` · `list_apps` · `list_windows` · `focus_window` · `close_window` · `type_text` · `press_key` · `open_url` · `screenshot` · `read_screen` (on-screen **OCR**) · `media_control` · `notify`. Auto-detects **X11 vs Wayland** and picks the right backend.

**Files &amp; shell (gated for anything that changes):** `read_file` · `list_dir` · `find_file` · `make_dir` · `copy_path` · `move_path` · `delete_path` · **`run`** any shell command (decisive by default, always force-confirmed for the catastrophic class, sudo handled safely). **Write any file** via a diff card you Apply.

</details>

<details>
<summary><b>🧠 Memory, self-written tools &amp; self-modification</b> — it grows with you</summary>

<br>

- **Memory (optional, local):** `memory_remember` · `memory_recall` · `memory_forget` — relevance-scoped recall that connects security paraphrases ("SQL injection" finds "SQLi") and injects only the top-k per turn. Nothing leaves the box.
- **Self-written tools (optional, sandboxed):** `skill_write` → Kali drafts a Python tool, it's `ast`-parsed and statically screened, run in a **bubblewrap** jail, and must pass its **own test** before you Apply it. Then it's callable as `skill_run`.
- **Self-modification:** Kali can rewrite its own source and persona — proposed as a diff you Apply. Python is parse-checked, the original is backed up, writes are atomic, and the **guardrail block is immutable by design**.

</details>

<details>
<summary><b>🎙️ Voice &amp; ⚡ working smart</b> — talk to it, and it runs lean</summary>

<br>

- **Voice:** STT via SiliconFlow SenseVoice or Groq Whisper (auto-picked), with a *Test microphone* button. TTS via Piper (neural) or espeak-ng, tuned for natural pacing with no dead air, and per-message play/pause.
- **Working smart:** batched parallel tool calls · trimmed history · context compression that always preserves findings while cutting token cost · a collapsed **💭 Thoughts** reasoning panel · live status banner · `/panic` health sweep · degraded-output failover to your next provider.
- **Background worker (optional):** a `systemd --user` service for genuinely-headless jobs (periodic checks, memory consolidation). Fully optional — Kali works identically without it.

</details>

<br>

---

## The safety model — why you can hand it root

Kali is **decisive by default and un-catastrophic by construction.**

- **Two speeds, you pick.** *Default:* read-only sensing runs free, and when you ask for something Kali does it, reads the result, and continues — no clicking through routine work. *Confirm every command (one toggle):* every side-effecting action becomes a card you approve one at a time.
- **The irreversible class always stops for a confirm** — even in auto-run, even if the model was steered by something it read on a webpage. A **structural** detector (shlex-tokenized, `$IFS`/quote-normalized, recursing into `sh -c` / `eval`) force-confirms disk/filesystem wipes, recursive root/`$HOME` deletes, fork bombs, and raw block-device writes. It sees through tricks a regex misses — `rm '-rf' /`, `rm${IFS}-rf${IFS}/`, `cd / && rm -rf *`, `find / -delete`, `echo … | base64 -d | sh` — while staying narrow enough that `nmap`, `nuclei`, `sqlmap` and `rm -rf ~/loot` never trip it. The full catch/ignore contract is **pinned in the test suite.**
- **Kali's own safety code can't be shell-stripped**, your **sudo password is never stored or shown to the model**, and self-written code runs only in a **bubblewrap jail** after passing its own test.
- **It can't lie about your machine.** Hardware and system facts are read live with a tool, never guessed.
- **No exploit generation, ever.** Security tooling is propose-only / read-only; you drive the trigger, against scope you set.

> The guarantee isn't "asks every time" — it's that the one mistake that can't be undone keeps a human in the loop no matter what, and you can dial friction to full-confirm whenever you want.

<br>

---

## Install &amp; update

```bash
curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
```

Run it once to install; run the **exact same line** any time to update. The installer is idempotent and genuinely careful — it treats your machine the way you'd want it treated:

- 🐍 Detects **Python 3.10+** and installs **GTK4 + libadwaita** (apt / pacman / dnf, auto-detected).
- 📦 Fetches the core modules **plus** the optional `kali_ext/` sidecar — and **verifies every one of the 14 sidecar modules arrived**, retrying any that didn't, refusing to install a half-broken update over a working one.
- 🛟 **Parse-checks every incoming file before it overwrites anything** — a corrupted download can't replace your working install.
- 💾 **Backs up your chat database** before each update and reports the version move.
- 🧩 Installs optional desktop helpers, voice packages, and optionally Playwright + Chromium.
- 🦁 **`WITH_BRAVE=1`** installs Brave for ad/tracker-free browsing.
- 🚀 Drops a `kali` launcher in `~/.local/bin/` and a `.desktop` entry in your app grid.

**Manual install:** `git clone https://github.com/the-priest/oracle5.git kali && cd kali && ./install.sh`
**Uninstall:** `~/.local/share/kali/install.sh --uninstall` (chat history kept).

<details>
<summary>Flags &amp; environment overrides</summary>

<br>

| flag | what it does |
| --- | --- |
| `--update` | explicit update (same as the default path) |
| `--uninstall` | remove Kali (chat history kept) |
| `--no-systemd` | skip the background-worker systemd unit |
| `--no-helpers` | skip optional desktop-control helpers |
| `--no-browser` | skip Playwright + Chromium |
| `--no-voice` | skip voice setup |
| `--no-prompt` | non-interactive (skips the API-key prompt) |

```bash
GROQ_API_KEY=gsk_...  ./install.sh      # preset a key, no prompt
WITH_BRAVE=1          ./install.sh      # also install Brave
WITH_MCP=1            ./install.sh      # configure a safe starter MCP server
KALI_REPO=user/fork  KALI_BRANCH=dev  ./install.sh
```

</details>

<br>

---

## Get an API key

Kali is multi-provider — you only need a key for the one(s) you want. Set the active provider and key in **Settings → Backends**.

| Provider | Get a key | Notes |
| --- | --- | --- |
| **SiliconFlow** | <https://cloud.siliconflow.com/account/ak> | **Default.** Big open models (DeepSeek, Qwen, Kimi) + SenseVoice STT |
| **Groq** | <https://console.groq.com/keys> | Blistering speed, generous free tier. Whisper STT. Keys look like `gsk_...` |

Keys live only in `~/.config/kali/settings.json` — they never go anywhere but the provider's own API.

<br>

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
      │ 75+ agent tools  │   │ + immutable      │   │ (provider-   │
      │ web · github     │   │   guardrail      │   │  aware ASR)  │
      │ brave · chat DB  │   └──────────────────┘   └──────────────┘
      └──┬────────┬───┬──┘
         │        │   │
   ┌─────┴───┐ ┌──┴───┴────────┐
   │kali_    │ │ kali_ledger.py│  tamper-evident evidence ledger
   │safety.py│ │ (JSONL+SHA256)│  (every command, hashed)
   │hard auto│ └───────────────┘
   │-run floor (structural, evasion-resistant, setting-independent)
   └─────────┘
         │
   ┌─────┴───────────────────────────────────────────────────────┐
   │  kali_ext/  (optional sidecar — off by default, 14 modules)  │
   │  memory · skills · sandbox · foresight · mcp · verify ·       │
   │  worker · headroom · pentest · codescan · engage · bench                      │
   └─────────────────────────────────────────────────────────────┘
```

Provider stack: **SiliconFlow / DeepSeek** primary with a **Groq** fallback. The router reads your active provider and model live, and fails over to your next backend on a degraded response.

<details>
<summary>Development &amp; test suites</summary>

<br>

```bash
git clone https://github.com/the-priest/oracle5.git kali && cd kali
python3 kali.py                    # run from source

# offline test suites (stdlib only — no display, no keys, no network)
python3 tests/test_kali.py         # core: safety floor, settings, self-edit, ChatStore, ledger, CVE chain, Nuclei, reflection, memory, MCP screen
python3 tests/test_codescan.py     # code audit: every scanner parser, cross-tool triage/dedup, secret redaction
python3 tests/test_writeup.py      # exploitation narrative: ledger-grounded steps, secret redaction, honesty on thin input
python3 tests/test_headroom.py     # token savings: protocol safety, signal preservation, compression ratio, fail-safe
```

For per-machine persona tweaks that survive upgrades, use **Settings → Persona → Custom addendum** — direct edits to `kali_persona.py` are replaced on the next `install.sh` run.

</details>

<br>

---

## What Kali will *not* do

- **Destroy your system or its storage on its own.** Disk/FS wipes, recursive root/`$HOME` deletes, fork bombs and raw block-device writes are *always* force-confirmed — even in decisive auto-run, even via quoting / `$IFS` / `bash -c` tricks.
- **Be an always-on autonomous fleet agent.** A deliberate non-goal — Kali keeps you in the loop for the irreversible.
- **See your sudo password**, or reach private content it hasn't been given a token for.
- **Invent facts about your machine.** Hardware and system state are read with a tool, not guessed.
- **Write exploit code or attack a target on its own.** Security tooling is propose-only / read-only; you drive the trigger, against scope you set.

<br>

---

<div align="center">

## License

**MIT.** Take it, fork it, ship it.

## Credits

Forged by **The Priest** ⟁

*A dragon that lives on your machine, answers only to you, and never forgets where the bodies are buried.*

</div>
