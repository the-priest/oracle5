# ⟁ KALI — Complete User Manual

*The full reference for Kali, the AI security assistant that lives on your Linux machine.*

**Version 3.2.0** · GTK4 + libadwaita · X11 & Wayland · desktop and NetHunter mobile

---

## How to read this manual

You don't call Kali's tools directly. You **talk to Kali in plain language**, and it decides which tools to use, runs them, reads the results, and continues. Throughout this manual each capability lists the underlying **tool name** in `code font` so you know exactly what's happening under the hood — but in practice you'd just *ask*. "Scan my network," not `scan_net`.

The manual is organised as:

1. **Core concepts** — the handful of ideas that make everything else make sense. Read this first.
2. **Installation & setup**
3. **The capabilities**, grouped and explained one at a time.
4. **The safety model**, in full.
5. **Settings, architecture, troubleshooting, and a quick reference.**

---

# Part 1 — Core concepts

Everything Kali does sits on four ideas. Understand these and the rest is detail.

## 1.1 Sensing vs. acting

Kali's tools fall into two buckets:

- **Sensing (read-only).** Looking at things — system state, files, the web, the screen. These **run freely, with no permission needed**, because they can't change anything. Asking "how much disk do I have?" just gets answered.
- **Acting (state-changing).** Anything that changes your machine or the world — running a command, writing a file, closing a window, deleting something. These are **gated** (see below).

This split is why you can let Kali roam: it can *look* at anything instantly, and only *changing* things involves the gate.

## 1.2 The two speeds

You choose how much Kali asks before it acts. One setting, **Confirm every command**, flips between them:

- **Decisive (default).** When you ask Kali to do something, it **just does it** — runs the command, reads the output, runs the next one — no clicking through routine work. This is what makes it feel like an operator and not a chatbot.
- **Confirm every command (opt-in).** *Every* action with side effects becomes a **card** you approve one at a time. Maximum control, more friction. Toggle it on whenever you want a tighter leash.

Either way, the hard floor below always holds.

## 1.3 Cards

When Kali wants approval (in confirm mode, or always for risky actions), it shows a **card** in the chat:

- **Run cards** — a proposed shell command with a **risk level** and a **Run** button. Nothing executes until you click.
- **Diff cards** — for writing or editing a file (including Kali editing its own source). You see a real before/after **diff**, and nothing touches disk until you click **Apply**.

A card is an approval checkpoint. Clicking Run/Apply *is* your consent.

## 1.4 The hard floor (the one rule that never bends)

This is the most important concept. **A specific class of irreversible actions ALWAYS stops for an explicit confirm — even in decisive auto-run, even if the model was steered by something it read on the web.** That class is:

- Disk / filesystem **wipes**
- Recursive deletes of **root** or your **home**
- **Fork bombs**
- Raw **block-device writes** (e.g. `dd of=/dev/sda`)
- Any command that would **edit Kali's own safety guardrail**

The detector that catches these is **structural**, not a keyword list — it tokenises the command the way a shell does, normalises quoting and `$IFS`, and recurses into `sh -c` / `eval`. So it catches the obfuscated forms a naive filter misses (`rm '-rf' /`, `rm${IFS}-rf${IFS}/`, `cd / && rm -rf *`, `find / -delete`, `bash -c "…"`, `echo … | base64 -d | sh`) — while staying narrow enough that normal work (`nmap`, `nuclei`, `sqlmap`, `rm -rf ~/loot`) never trips it.

**The guarantee is not "Kali asks every time." It's that the one category of mistake you can't undo always keeps a human in the loop, no matter the setting.**

---

# Part 2 — Installation & setup

## 2.1 The one-liner (install *and* update)

```
curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
```

Run it the first time to install. Run the **exact same line** any time later to update. It's idempotent and careful:

- Detects Python 3.10+ (fails fast if missing).
- Installs GTK4 + libadwaita bindings (apt / pacman / dnf, auto-detected).
- Fetches the core modules plus the optional `kali_ext/` sidecar.
- **Parse-checks every incoming file before it overwrites anything** — a broken or truncated download can never replace your working install.
- **Backs up your chat database** before each update and tells you the version it's moving you to.
- Installs optional desktop-control helpers, voice packages, and (optionally) Playwright + Chromium.
- Drops a `kali` launcher in `~/.local/bin/` and a desktop entry in your app grid.

First install takes ~1–3 minutes; re-runs are seconds.

## 2.2 Manual install

```
git clone https://github.com/the-priest/oracle5.git kali
```
```
cd kali
```
```
./install.sh
```

## 2.3 Install flags

| Flag | Effect |
| --- | --- |
| `--update` | Explicit update (same as the default path) |
| `--uninstall` | Remove Kali (chat history kept) |
| `--remove-oracle` | Remove an old Oracle install (Kali untouched) |
| `--no-systemd` | Skip the background-worker systemd unit |
| `--no-helpers` | Skip optional desktop-control helpers |
| `--no-browser` | Skip Playwright + Chromium |
| `--no-voice` | Skip voice setup |
| `--no-prompt` | Non-interactive (skips the API-key prompt) |

## 2.4 Environment overrides

```
GROQ_API_KEY=gsk_... ./install.sh
```
```
KALI_REPO=user/fork KALI_BRANCH=dev ./install.sh
```

## 2.5 Choosing a provider and getting a key

Kali is **multi-provider** — it brings no model of its own; you point it at a cloud LLM and it does the rest. You only need a key for the provider(s) you want, set in **Settings → Backends**.

| Provider | Where to get a key | Notes |
| --- | --- | --- |
| **SiliconFlow** | cloud.siliconflow.com/account/ak | **Default.** Big open models (DeepSeek, Qwen, Kimi) + SenseVoice speech-to-text |
| Groq | console.groq.com/keys | Fast, generous free tier. Whisper STT. Keys look like `gsk_...` |
| Novita AI | novita.ai/settings/key-management | Cheap GPU inference, many open models |
| GitHub Models | github.com/settings/personal-access-tokens | Free tier. Fine-grained PAT with `models:read` |
| Google AI Studio | aistudio.google.com/apikey | Gemini models, free tier |

The **default provider stack is SiliconFlow/DeepSeek primary with a Groq fallback chain** — if your active provider fails mid-request, Kali can fail over to the next one you've configured. Keys live only in `~/.config/kali/settings.json`, never logged and never sent anywhere but the provider's own API.

## 2.6 First launch

Launch from the app grid (look for **Kali**) or run `kali` in a terminal. On first run, set your provider and key in Settings, then just start talking. Hit the ⟳ next to a provider's model dropdown to fetch its live catalogue once a key is set.

---

# Part 3 — The chat interface

## 3.1 The persona

Kali has a sharp, loyal, no-filler personality. It's built to be a direct operator's partner, not a cheerful assistant. You can tune it per-machine in **Settings → Persona → Custom addendum** (these tweaks survive upgrades; direct edits to the persona file get overwritten on update).

## 3.2 The status banner

While Kali is working, a live banner tells you *what it's doing* in plain terms — "running nmap…", "cross-checking sources…", "building the report…" — so a long operation isn't a silent spinner.

## 3.3 The Thoughts panel

When the model exposes its chain-of-thought, Kali tucks it into a collapsed **💭 Thoughts** expander. It's kept **out of the reply, out of text-to-speech, and out of replayed history** — there if you want to see the reasoning, invisible if you don't.

## 3.4 Chat history

Conversations are stored in a local SQLite database (`~/.local/share/kali/chats.db`). By default Kali is **ephemeral**: it opens a fresh chat each launch, discards empty placeholders, and bins chats idle longer than the retention window — all tunable in Settings. Your DB is backed up before every update.

---

# Part 4 — Offensive security (the bread and butter)

This is Kali's core. **Every tool here is propose-only or read-only** — Kali plans, inventories, parses, enriches, and documents. It writes no exploit code and attacks nothing on its own. Real recon/attack commands run only through the approve-before-run gate, against scope **you** set.

## 4.1 `audit` — local security posture scan

A read-only sweep of *your own* machine's security hygiene: firewall status, SSH hardening, open listening ports, world-writable files, failed login attempts, pending updates, and more — each scored by severity. Nothing is changed; it's a health check. Ask "audit my system's security."

## 4.2 `scan_net` — local network discovery

Discovers hosts on your own network segment. Use it to map what's around you. Like all active commands, the actual scan runs behind the gate.

## 4.3 `tooling_check` — offensive-tool inventory

Inventories **59 offensive-security tools** across recon, probing, port-scanning, fuzzing, vuln-scanning, secrets, credentials, and Active Directory. For anything not installed, it gives the **exact install line** (apt / go / pipx), knows **aliases** (e.g. `nxc` → `netexec`), and nudges you about **freshness** (nuclei templates, SecLists/rockyou). Ask "what offensive tools do I have?" before an engagement so you know what you're working with.

## 4.4 `pentest_plan` — ordered recon plan

Builds a **methodical, ordered** recon plan with **passive/enumeration steps first**. It supports profiles — `web · network · ad · api · full · quick` — and an **intensity knob** (`stealth / normal / aggressive`) that tunes nmap timing, nuclei rate-limits, and ffuf threads accordingly. Every step it produces is a *proposed* command behind the Run gate; nothing fires on its own. Ask "plan a web pentest of example.com, stealthy."

## 4.5 `parse_output` — turn scanner noise into structured data

Paste raw scanner stdout and Kali turns it into clean structured data — hosts, ports, services, versions, endpoints, findings — for **20+ tools**: nmap (including NSE script hits), httpx, nuclei, naabu, masscan, subfinder, ffuf, feroxbuster, gobuster, katana, whatweb, wpscan, sslscan/testssl, smbmap, netexec, nikto, gitleaks, dalfox, arjun, and more. It also **strips ANSI colour codes**, so colourised pastes don't silently drop data.

Its standout trick: with `enrich_cves`, it **auto-chains into CVE intelligence** — every confirmed service+version in the scan is looked up and a severity-ranked CVE block is attached. One call turns a scan paste into "here are the services *and* the exploitable, known-in-the-wild CVEs."

## 4.6 `cve_lookup` — prioritised CVE intelligence

Pulls CVEs from the **NVD**, then enriches each with **CISA KEV** (is it being exploited in the wild?) and **EPSS** (how likely is exploitation?), and **re-ranks the results KEV → EPSS → CVSS** so the genuinely dangerous ones surface first — not just the highest CVSS score. Ask "any known CVEs for OpenSSH 8.2?"

## 4.7 `nuclei_template` — generate or validate Nuclei templates

Nuclei's YAML is easy to get subtly wrong, and a malformed template only fails — cryptically — when you run it. This tool removes that:

- **Build mode:** give a simple spec (name, severity, protocol, path, matchers) and Kali emits a **structurally-valid** template. You supply the specifics; the scaffold guarantees the shape.
- **Validate mode:** hand it any Nuclei YAML and it parses it and reports **exactly what's wrong** (bad severity, missing matchers, malformed id) *before* you run `nuclei -t`.

You still run the scan yourself; this just makes sure the template is correct first.

## 4.8 `reflect_findings` — self-check before you report

A self-reflection pass that critiques a set of findings for false-positive risk *before* they reach a report. It flags findings that have **no evidence**, are **over-rated** (high/critical with nothing backing it), use **hedging language** ("maybe", "possibly"), have **no affected host**, or are **duplicates** — so weak findings get fixed or dropped instead of shipped. Pure heuristics, no extra model call. Run it before `report_findings` on anything non-trivial.

## 4.9 `methodology` — phased testing checklists

Phased, methodical testing checklists grounded in **PTES / OWASP WSTG / the Active Directory kill-chain**, for areas: web, network, ad, api, mobile, wifi, recon, priv-esc, cloud. Knowledge only — proposes no commands. Use it to make sure a test is systematic and nothing gets skipped.

## 4.10 `wordlist_find` — find installed wordlists

Locates the wordlists actually present on *your* box (SecLists included) under the usual paths, and gives the **canonical pick** per task (directory, subdomain, password, api, param, username, lfi…) plus alternatives, with an install hint if nothing matching is there. Read-only.

## 4.11 `cheatsheet` — correct command syntax

The correct flags and invocation patterns for the tools you actually reach for — nmap, ffuf, nuclei, httpx, netexec, hydra, hashcat, john, sqlmap, smbmap, kerbrute, ssh-tunnels, curl, and more. Documentation only: no exploit code, runs nothing. Ask "what's the ffuf syntax for directory brute-forcing?"

## 4.12 `report_findings` — clean engagement report

Aggregates your structured findings into a polished markdown **engagement report**: a severity rollup, a sorted findings table, and a per-finding detail section (title, severity, host, description, evidence, remediation). Read-only — it formats text, runs nothing.

---

# Part 5 — Evidence ledger

This is what separates a chat log from a **defensible engagement deliverable**. Every command Kali runs is **automatically recorded** — you don't log anything by hand.

## 5.1 How it works

Each executed command appends one line to a tamper-evident JSONL ledger capturing: timestamp, engagement, step number, the command, the reason, working directory, user, exit code, duration, and the **SHA-256 hash of stdout and stderr**. The full output is saved to a side artifact file whose hash is recorded. Because the hash is stored, the ledger can later **prove the captured output wasn't altered after the fact**. It's fail-safe: a ledger error can never break a command.

## 5.2 `evidence_engagement` — name the case

Sets (or switches) the **engagement** that future commands are filed under. Do this at the **start** of a job — "start an engagement called acme-q2" — so the whole run is grouped into one named case.

## 5.3 `evidence_report` — the proof

Returns a **summary** (how many commands, how many succeeded), an **integrity check**, and a **readable markdown ledger** of everything run so far. This is the artifact you'd hand a client or attach to a report. Ask "show me the evidence report."

## 5.4 `evidence_verify` — tamper check

Re-hashes every captured artifact and confirms it still matches the ledger. If an output file was edited after capture, its hash no longer matches and it's flagged. This is the integrity guarantee made explicit.

---

# Part 6 — External tools via MCP

Kali can connect to external **Model Context Protocol (MCP)** servers — the growing ecosystem of security MCP servers that wrap tools like nmap, sqlmap, ffuf, nuclei, and ZAP. Wiring one in gives Kali all of that server's tools without you writing a wrapper per tool.

## 6.1 The key facts

- **Off by default.** MCP is inert until you both enable it (`mcp_enabled`) **and** configure at least one server (`mcp_servers`). If you ignore it, nothing changes.
- **Tools are namespaced.** A discovered tool appears as `mcp__<server>__<tool>` so it can never be confused with Kali's built-in tools. `mcp_tools` lists everything wired up.
- **You don't write a server.** You point Kali at an existing one. A server entry is a config object: `{name, command, args, env, cwd}`. For example, a Docker-packaged server is just `{"name": "pentest", "command": "docker", "args": ["run", "-i", "the-image"]}`.

## 6.2 The safety wrapper (why this is safe)

MCP is a documented remote-code-execution surface, so Kali treats every MCP server as **untrusted**:

- **Every tool call's arguments are screened by the same safety floor** that guards `run`. If an argument resolves to a catastrophic command (a disk wipe, a recursive root delete — however obfuscated), the call is **refused before it ever leaves the process**.
- **Every MCP call is logged to the evidence ledger**, exactly like a local command.

## 6.3 Using it

Once enabled and configured, just ask Kali to use the tool ("run an nmap scan via the pentest server"). To see what's available, ask it to list MCP tools (`mcp_tools`).

---

# Part 7 — OSINT & research

## 7.1 `osint_username` — handle check across public sites

Checks a username across public profile sites. **Important caveat Kali itself observes:** a hit means a *public page exists* at that handle — **not** that it's the same person. Always confirm identity separately.

## 7.2 `osint_lookup` / `social_read` — public readers

Platform-aware readers for public pages and public APIs. **Public only** — no login, no gated scraping. Use them to read what's openly available about a target.

## 7.3 `web_search` — ranked web search

Searches the web (DuckDuckGo), returning ranked results plus direct answers. The everyday "look this up."

## 7.4 `web_read` — fetch a page as clean text

Fetches any public page and returns it as clean, readable text — **headless**, no browser needed. Use it to have Kali actually read an article, advisory, or doc rather than guess at it.

## 7.5 `web_verify` — the anti-propaganda engine

This is Kali's most distinctive research tool. Instead of trusting one source, it **gathers several independent sources**, scores each for credibility (primary / reputable / community / state-media / satire), checks whether they **actually corroborate** each other, and returns a **confidence label** — separating confirmed / inferred / unknown and **flagging state media and satire** instead of laundering them into fact. Use it for any claim where being wrong matters. Ask "verify whether X actually happened."

## 7.6 `github` — read GitHub

Searches repos and code, lists a user's repos, and reads file trees, source, READMEs, releases, and issues. Public by default; private repos with a token you provide.

## 7.7 `browser` — full browser automation

Full **Playwright + Chromium** automation for sites that need a real browser — login-gated pages or JS-only apps that `web_read` can't handle. Heavier than `web_read`, so it's used when a page genuinely requires it.

---

# Part 8 — System sensing (read-only, runs freely)

All of these just *look* at your machine — no permission needed, nothing changes.

- **`quick_facts`** — a fast, cached snapshot: hostname, IP, uptime, load, free space.
- **`system_info`** — fuller system details (OS, kernel, hardware).
- **`disk_usage`** — what's using your storage.
- **`processes`** — running processes.
- **`network_status`** — interfaces, connections, routing.
- **`service_status`** — the state of system services.
- **`journal_tail`** — the tail of your systemd journal (recent logs).
- **`recent_downloads`** — what landed in your Downloads recently.
- **`check_updates`** — pending package updates.
- **`path_info`** — details about a given file or directory path.
- **`desktop_info`** — what desktop-control backends are available on your box (which display server, which helper tools).

Ask things like "how's my system doing?" or "what's eating my disk?" and Kali batches several of these in one go.

---

# Part 9 — Desktop control (confirm-gated)

Kali can drive your **actual** desktop. It auto-detects **X11 vs Wayland** and picks the right backend (xdotool/wmctrl/scrot on X11; wtype/wlrctl/grim on Wayland; prefers Spectacle/kdialog on KDE Plasma). These are *acting* tools, so they run directly in decisive mode or as cards under Confirm-every-command.

- **`launch_app`** — open an application.
- **`list_apps`** — list installed/available apps.
- **`list_windows`** — list open windows.
- **`focus_window`** — bring a window to the front.
- **`close_window`** — close a window.
- **`type_text`** — type text into the focused window.
- **`press_key`** — send a keystroke / shortcut.
- **`open_url`** — open a URL in your browser.
- **`screenshot`** — capture the screen.
- **`read_screen`** — **OCR** the screen — read text that's visible on-screen (useful when there's no API for what you're looking at).
- **`media_control`** — play/pause/skip media.
- **`notify`** — pop a desktop notification.

Ask "open Firefox and go to my router's admin page" and Kali chains `launch_app` / `open_url`.

---

# Part 10 — Files & shell

Reading is free; anything that changes the filesystem is gated (and the irreversible class is always force-confirmed).

## 10.1 Reading (read-only)

- **`read_file`** — read a file's contents. Detects binary vs text properly (by NUL byte), so it won't mangle a truncated text file.
- **`list_dir`** — list a directory.
- **`find_file`** — find files, with **size and modification-time filters**.

## 10.2 Changing (gated)

- **`make_dir`** — create a directory.
- **`copy_path`** — copy a file or directory.
- **`move_path`** — move/rename.
- **`delete_path`** — delete (the catastrophic forms — recursive root/home — are force-confirmed).

## 10.3 `run` — any shell command

The big one. Kali can run **any shell command**. In decisive mode it executes directly, reads the output, and continues; under **Confirm every command** it becomes an approve-first card; and the **catastrophic class is always force-confirmed** regardless. **Sudo is handled safely** — your password is collected in a dialog, validated, used to cache the credential for the session, and **never stored, logged, or shown to the model**.

## 10.4 `write_file` — write any file (diff card)

Create or overwrite any file — a document, report, script, or config — via a **diff card** you Apply. You see the change as a real diff before a byte hits disk. Multi-line content is parsed robustly, so a long file won't get silently corrupted in transit.

---

# Part 11 — Memory (optional, local)

Off by default; enable in Settings. When on, Kali remembers things across sessions — **locally, nothing leaves the box**.

- **`memory_remember`** — store a fact, with a kind and a salience.
- **`memory_recall`** — retrieve relevant memories. Recall is **relevance-scoped**: it scores by keyword match + recency + salience (optionally embeddings) and injects only the **top-k** memories per turn, never the whole store. It also connects **security paraphrases** — a search for "SQL injection" finds a memory stored as "SQLi", and vice versa, across a couple dozen synonym groups (XSS, RCE, LFI, SSRF, privesc, recon, and more).
- **`memory_forget`** — drop a memory by query or id.

Ask "remember that the client's scope is 10.0.0.0/24" and later "what was the scope again?"

---

# Part 12 — Self-written tools (skills, optional, sandboxed)

Off by default. When on, Kali can **write its own Python tools** — and it can't hurt you doing it, because of the sandbox.

- **`skill_write`** — Kali drafts a Python tool. Before anything runs, it's **`ast`-parsed and statically screened**, then executed in a **bubblewrap jail** (read-only system, no access to your home, network off), and it **must pass its own test**. Only then do you get a card to **Apply** it. The save goes through Kali's own confirm dialog.
- **`skill_run`** — run a saved skill.
- **`skill_list`** — show the skill library.

So a self-written tool runs in isolation and proves itself before it's ever trusted. Ask "write me a skill that parses this custom log format."

---

# Part 13 — Self-modification

Kali can **rewrite its own source and persona**. It proposes the full new file as a **diff**; you click **Apply**. Safeguards:

- Python is **parse-checked** before writing — a syntax error can't replace a working file.
- The **original is backed up**.
- Writes are **atomic**.
- A load-bearing **guardrail block is immutable by design** — Kali can edit everything else about itself, but the write path **refuses any edit that drops or alters that block** (enforced in code, not merely asked of the model).

Persona edits reload live on the next reply; code edits load on relaunch. (Note: direct edits to `kali_persona.py` get overwritten on the next `install.sh` run — use the Settings persona addendum for changes that should survive updates.)

---

# Part 14 — Voice

## 14.1 Speech-to-text (talk to it)

Tap the mic, talk, tap to send. It's **provider-aware** — it transcribes through **SiliconFlow SenseVoiceSmall** or **Groq Whisper**, auto-picking whichever key you have. A **Test microphone** button records ~4 seconds and shows you the exact transcript (or the error), so you can confirm your mic works before relying on it.

## 14.2 Text-to-speech (hear it back)

Kali reads replies aloud via **Piper** (neural, nicer voice) or **espeak-ng** (always-available fallback), with **per-message play / pause / resume** controls. The Thoughts panel is never spoken.

---

# Part 15 — Quality-of-life features

Things that make Kali efficient and pleasant, mostly automatic:

- **Batched, parallel tool calls** — many read-only lookups in a single model round-trip, so "how's my system?" runs ten sensors at once instead of one at a time.
- **Trimmed history** — already-used tool outputs are stubbed in the resent context, so a long session doesn't re-bill huge output blobs every turn.
- **Context compression (headroom)** — bulky output is crushed before it reaches the model, but **findings are always preserved** (errors, ports, CVEs, creds never get compressed away).
- **`/panic`** — type it and Kali jumps straight to a batched system-health sweep with a tight summary, no chit-chat.
- **Urgency fast-path** — if you're clearly in a hurry, Kali drops the preamble and leads with the most likely fix.
- **Command de-dup** (opt-in) — avoids re-running an identical command it just ran.
- **Degraded-output failover** (opt-in) — if a provider starts returning garbage, Kali fails over to your next configured provider.
- **Cached-sudo awareness** — if sudo already has a valid cached credential this session, Kali won't re-prompt for the password (when that option is on).

---

# Part 16 — The background worker (optional)

A `systemd --user` service for genuinely-headless jobs: periodic system checks, memory consolidation, and skill curation. It's **fully optional** — Kali works identically without it, and you can skip it at install with `--no-systemd`. Use it only if you want Kali doing light housekeeping in the background.

---

# Part 17 — The safety model (in full)

Kali is built to be **decisive by default and un-catastrophic by construction**. The complete trust boundary:

1. **Two speeds, you pick.** Read-only sensing runs free. In the default decisive mode, requested actions run and Kali keeps going; under **Confirm every command**, every side-effecting action is a card. Either way, the floor below holds.

2. **The irreversible class always stops for a confirm** — even in auto-run, even if the model was steered. The structural detector (shlex-tokenised, `$IFS`/quote-normalised, recursing into `sh -c`/`eval`) force-confirms disk/FS wipes, recursive root/`$HOME` deletes, fork bombs, and raw block-device writes. It sees through quoting, `$IFS`, `cd /` then `rm -rf *`, `find / -delete`, `bash -c`, and base64-pipe-to-shell tricks, and is a strict superset of any simpler backstop. It stays narrow: ordinary offensive work and `rm -rf ~/loot` don't trip it. The exact catch/ignore contract is pinned in the test suite.

3. **Kali's own safety code can't be shell-stripped.** A raw `>`, `sed -i`, `tee`, or `dd of=` aimed at `kali*.py` is force-confirmed too, so the immutable guardrail can't be edited out from under the guarded path.

4. **Your sudo password is never stored, logged, or shown to the model.** Collected in a dialog, validated, cached for the session only.

5. **API keys live only in `~/.config/kali/settings.json`** — never logged, never sent anywhere but the provider's own API.

6. **Self-written code never runs in Kali's process.** It's `ast`-parsed, statically screened, and executed in a **bubblewrap-isolated** child (read-only system, no home, network off) that must pass its own test before it can be saved.

7. **Optional foresight gate** predicts a command's blast radius and can **hard-block** catastrophic, irreversible actions even in auto mode.

8. **The persona guardrail block is immutable** — enforced in code, not just asked of the model.

9. **Robust tool parsing** — a multi-line document or a stray character in a tool call can't silently vanish or get mistaken for chat text: it's recovered and rendered as a real diff/run card, or you're told it wasn't — so Kali never claims an action happened when it didn't, and never "types" a tool call into the conversation instead of running it.

**The honest framing:** the default is not a babysat, approve-everything daemon — it runs routine commands for you, which is the point. What it guarantees is narrower and more important than "asks every time": the one class of mistake that can't be undone keeps a human in the loop no matter what, and you can dial friction up to full-confirm whenever you want.

---

# Part 18 — What Kali can NOT do

By design:

- **Destroy your system or its storage on its own.** The catastrophic class is always force-confirmed.
- **Be an always-on autonomous fleet agent.** A deliberate non-goal — Kali keeps you in the loop. (Want an unsupervised swarm? That's a different kind of tool.)
- **See your sudo password.**
- **Reach private/authenticated content it hasn't been given access to.** Public web and public GitHub, yes; private only with a token you set.
- **Write exploit code or attack a target on its own.** Security tooling is propose-only/read-only; you drive the trigger.

---

# Part 19 — Settings reference (the important ones)

Settings live in **Settings** in the app (stored at `~/.config/kali/settings.json`). The ones worth knowing:

- **Active provider + keys** (Backends) — which model Kali uses, and the fallback chain.
- **Confirm every command** — the master friction switch (decisive ↔ approve-everything).
- **Auto-sudo when cached** — skip the password prompt when sudo already has a cached credential.
- **Memory** (off by default) — enable cross-session recall.
- **Skills** (off by default) — enable self-written, sandbox-tested tools.
- **Foresight** (off by default) — the consequence-prediction gate.
- **MCP** (off by default) — `mcp_enabled` plus `mcp_servers` to connect external tool servers.
- **Worker** (off by default) — the headless background companion.
- **Voice** — STT/TTS providers, models, mic test, TTS engine and rate.
- **Headroom** (context compression) — on by default.
- **Chat retention** — how long idle chats are kept before roll-off.
- **Persona → Custom addendum** — per-machine personality tweaks that survive upgrades.

---

# Part 20 — Architecture & file layout

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
   │safety.py│ │ (JSONL+SHA256)│
   │hard floor (structural, evasion-resistant, setting-independent)
   └─────────┘
         │
   ┌─────┴──────────────────────────────────────────────┐
   │  kali_ext/  (optional sidecar — off by default)     │
   │  memory · skills · sandbox · foresight · mcp · worker│
   └─────────────────────────────────────────────────────┘
```

**On disk:**

```
~/.local/share/kali/           code + data
  kali.py  kali_core.py  kali_safety.py  kali_ledger.py
  kali_persona.py  kali_voice.py
  kali_ext/                    optional sidecar
  chats.db                     conversation history
  backups/                     pre-update DB snapshots
  install.sh                   self-copy (for --uninstall / --update)
~/.config/kali/settings.json   settings + API keys (local only)
~/.config/kali/evidence/       the evidence ledger + hashed artifacts
~/.local/bin/kali              launcher
```

**Provider stack:** SiliconFlow/DeepSeek primary with a Groq fallback chain; Novita, GitHub Models, and Google AI Studio also selectable.

**Sidecar safety:** every sidecar hook is null-safe — a missing or broken sidecar can never take Kali down. The whole `kali_ext/` tree is off by default.

---

# Part 21 — Troubleshooting & FAQ

**Kali won't start / GTK errors.** Re-run the installer — it installs the GTK4 + libadwaita bindings and is safe to run again. Confirm Python 3.10+.

**The model isn't responding / errors out.** Check your provider key in Settings → Backends, and that the selected model is available (hit ⟳ to refresh the catalogue). If one provider is flaky, configure a second so failover has somewhere to go.

**A command I expected to just run popped a confirm dialog.** It hit the catastrophic-class floor (disk/FS destruction, recursive root/home delete, raw device write, or a self-edit). That's by design and can't be disabled — confirm it if you meant it.

**Voice transcription does nothing.** Use the **Test microphone** button in Settings → Voice; it records ~4s and shows the transcript or the exact error. Check you have a key for a provider with speech support (SiliconFlow or Groq).

**My persona edits disappeared after an update.** Direct edits to `kali_persona.py` get overwritten by `install.sh`. Put lasting tweaks in **Settings → Persona → Custom addendum** instead.

**Do I need to set up an MCP server?** No. MCP is off by default and entirely optional. Everything else works without it. Only enable it if you want to plug in external tool servers, and even then "setup" is one config entry, not building a server.

**Where's my evidence?** In `~/.config/kali/evidence/` — one JSONL file per engagement plus hashed artifact files. Ask Kali for an `evidence_report` for a readable view.

**Is my data leaving the machine?** Only the model call goes to your chosen provider. Memory, skills, evidence, chat history, and keys all stay local.

---

# Part 22 — Quick reference

**Install / update:** `curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash`

**Offensive security:** `audit` · `scan_net` · `tooling_check` · `pentest_plan` · `parse_output` (+`enrich_cves`) · `cve_lookup` · `nuclei_template` · `reflect_findings` · `methodology` · `wordlist_find` · `cheatsheet` · `report_findings`

**Evidence:** `evidence_engagement` · `evidence_report` · `evidence_verify`

**MCP:** `mcp_tools` · `mcp__<server>__<tool>`

**OSINT / research:** `osint_username` · `osint_lookup` · `social_read` · `web_search` · `web_read` · `web_verify` · `github` · `browser`

**System sensing:** `quick_facts` · `system_info` · `disk_usage` · `processes` · `network_status` · `service_status` · `journal_tail` · `recent_downloads` · `check_updates` · `path_info` · `desktop_info`

**Desktop control:** `launch_app` · `list_apps` · `list_windows` · `focus_window` · `close_window` · `type_text` · `press_key` · `open_url` · `screenshot` · `read_screen` · `media_control` · `notify`

**Files / shell:** `read_file` · `list_dir` · `find_file` · `make_dir` · `copy_path` · `move_path` · `delete_path` · `run` · `write_file`

**Memory:** `memory_remember` · `memory_recall` · `memory_forget`

**Skills:** `skill_write` · `skill_run` · `skill_list`

**Magic word:** `/panic` — instant batched health sweep.

---

*Built by The Priest. Named for the goddess and the distro.*
