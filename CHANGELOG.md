# Changelog

## v3.4.0 — Menacing makeover (red/green/black + fire penguin)

A visual overhaul of the look.

- **New menacing fire-penguin emblem.** Replaced the muted traced penguin with
  an angular black penguin with glowing red eyes, a green plasma rim, a sharp
  beak, and red flames (with green plasma licks) rising around it. Used as the
  app/taskbar icon and the chat avatar.
- **Penguin watermark behind the chat.** A large, faint version of the penguin
  now sits behind the conversation (a transparent `kali-watermark.svg`, drawn
  via a `Gtk.Overlay` so messages render over it). Non-interactive and low
  opacity, so it sets the mood without fighting the text.
- **Red / green / black theme.** Swapped the old blue accent for toxic green as
  the primary accent (links, focus, online, the operator label) and red for
  Kali's identity — the Kali label, the emblem glow, alerts/destructive — tying
  the UI to the penguin's red eyes. All backgrounds stay black.
- **Plumbing:** `install.sh` now ships `kali-watermark.svg` and places it (and
  the emblem) in the install dir so the watermark works on a fresh install.

---

## v3.3.1 — Reliable image search + sharper self-awareness

Fixes a real-world failure where showing a picture fell apart, and tightens how
well Kali knows its own abilities.

- **`image_search` rebuilt on reliable APIs.** The old version scraped
  DuckDuckGo's anti-bot image endpoint, which returned invalid JSON in practice
  ("Expecting value: line 1 column 1"). It now tries three keyless sources in
  order and stops at the first that works: **Openverse** (a real CC image API),
  then **Wikimedia Commons** (the MediaWiki API), then DuckDuckGo as a
  last-resort scrape. The first two are real JSON APIs returning direct image
  URLs, so it no longer depends on one fragile endpoint. All-sources-fail
  degrades gracefully instead of erroring.
- **No more flailing to show a picture.** The persona now spells out the
  one-step path (call `image_search` once with a plain subject → embed a
  returned URL as `![desc](url)`) and explicitly tells Kali *not* to hand-scrape
  stock-photo sites or guess Wikimedia file names — the behaviour that burned
  the tool-step budget before.
- **Self-awareness fix.** The capability summary was stale and even claimed Kali
  "cannot reach the internet" — contradicting its own web tools. Rewrote it into
  a complete, accurate map (web, images, OSINT, GitHub, evidence ledger, MCP,
  pentest tools, memory, skills, voice) so Kali stops having to test itself to
  discover what it can do.
- **Tool-step budget 12 → 20.** A legitimate multi-stage task (a full self-test
  sweep, a long pentest plan) was hitting the 12-round cap. Raised to 20; the
  graceful "lock tools and answer" behaviour at the limit is unchanged.
- **Tests:** 60 (was 59) — adds image-source fallback (Openverse-empty →
  Wikimedia → graceful-empty). *(The live API fetches are verified on a real
  machine, not in the offline suite.)*

---

## v3.3.0 — Kali can show pictures in chat

Kali can now **display images inline** in the conversation, not just link them.

- **Inline image rendering.** Any image the model puts in a reply as markdown —
  `![description](url)` — is fetched and rendered as a real picture in the chat
  (http/https/file/local-path). Download and decode happen off the UI thread,
  the bytes are size-capped (~12 MB), the picture is scaled to fit the bubble,
  and any failure degrades to a small caption with the link, so a dead URL can
  never break the chat. New `ImageWidget` + image-block detection in the
  renderer.
- **`image_search` tool.** Searches the web for images (DuckDuckGo, no API key)
  and returns direct image URLs for the model to embed. Ask "show me X."
- **OSINT profile photos.** `osint_username` now extracts each found profile's
  `og:image`/`twitter:image`, so a found account can be shown with its avatar.
- **Privacy toggle.** `chat_render_images` (default on) — turn it off and image
  markdown is shown as a tappable link instead, so the chat never reaches out to
  an image host. For OPSEC-conscious use.
- **Tests:** 59 (was 55) — adds `og:image` extraction (incl. protocol-relative
  and relative→absolute URLs) and image-search input handling. *(The live
  DuckDuckGo image fetch is verified on a real machine, not in the offline
  suite.)*

---

## v3.2.0 — Evidence ledger, MCP client, smarter recall, Nuclei + self-reflection

Four capability additions (no local-model support, by request).

### Evidence ledger (new `kali_ledger.py`)
Every command Kali runs is now recorded to an append-only, tamper-evident JSONL
ledger: timestamp, engagement, step number, command, reason, exit code,
duration, and the SHA-256 of stdout/stderr. Full output is saved to a side
artifact whose hash is recorded, so `evidence_verify` can re-hash and prove
nothing was altered after the fact. New tools: `evidence_engagement` (name/switch
the case), `evidence_report` (summary + integrity + a readable markdown ledger),
`evidence_verify` (tamper check). Fail-safe: a ledger error can never break a
command. This is what turns a chat transcript into a defensible deliverable.

### MCP client (new `kali_ext/mcp.py`)
Kali can now connect to external **Model Context Protocol** servers (the
ecosystem of security MCP servers — nmap/sqlmap/ffuf/nuclei/ZAP wrappers, etc.)
over stdio JSON-RPC. Discovered tools are exposed to the model namespaced
`mcp__<server>__<tool>` and listed via `mcp_tools`. **Security:** OFF by default
(`mcp_enabled`) and inert until servers are configured; every tool call's
arguments are screened by `kali_safety` (a catastrophic command in an argument
is refused before it leaves the process), and every call is logged to the
evidence ledger. Configure with `mcp_servers` = list of
`{name, command, args, env, cwd}`. *(Protocol verified against a mock server;
test real servers like pentestMCP / cyproxio on your box.)*

### Smarter memory recall (`kali_ext/memory.py`)
Keyword recall now connects security-domain paraphrases without embeddings:
"SQL injection" finds a memory stored as "SQLi", and the reverse — plus XSS,
RCE, LFI, SSRF, privesc, recon, and ~20 more synonym groups, in both directions.
Unrelated queries still miss, and a query with no synonym trigger gains no extra
tokens (no added noise). Fixes the one functional gap in recall.

### Nuclei templates + self-reflection (`kali_ext/pentest.py`)
- `nuclei_template` — generate a structurally-correct Nuclei YAML template from
  a simple spec (the model supplies specifics, the scaffold guarantees the
  shape), or validate an existing template and get the exact list of problems.
  Removes the "malformed template fails cryptically at `nuclei -t` time" trap.
- `reflect_findings` — a self-reflection pass that critiques findings before
  they're reported: flags no-evidence, over-rated, hedged, host-less, or
  duplicate findings so weak ones get fixed or dropped. Pure heuristics, cuts
  false positives.

### Tests
Suite now **55** (was 46): evidence ledger incl. tamper detection, Nuclei
build/validate, findings reflection, and the MCP argument safety screen.

### Plumbing
`install.sh` fetches `kali_ledger.py` and `kali_ext/mcp.py`. Version 3.1.0 → 3.2.0.

---

## v3.1.0 — Structural safety floor + honest docs

### Tool correctness (runtime bugs found by executing the logic)
- **Tool calls with a stray duplicate word now parse instead of leaking into
  the chat — fixed in two layers.** Some models emit `<tool tool name="run">…`
  (a doubled "tool") or `<tool run>`. *(1) Execution:* the tag regex only
  accepted `key="value"` attribute pairs, so a bare word made the whole tag
  fail to match — it never ran AND never got stripped, so raw `<tool …>` text
  printed in chat and the command silently did nothing. The parser now
  tolerates stray bare words (`name=`/`json=` still extracted normally). *(2)
  Display safety net:* `strip_tool_calls` now has a last-resort scrub so that
  *any* residual tool-shaped text — even a shape too malformed to parse — is
  removed from what's shown to the operator. The execution path can't run a tag
  it couldn't parse, but the worst case is now "silently hidden", never "typed
  into the conversation". Pinned by `TestToolTagParsing` (incl. a no-leak test
  over malformed shapes).
- **`parse_output` now strips ANSI colour codes first.** Many recon tools
  (httpx, nuclei, ffuf, feroxbuster, naabu, gobuster…) colourise by default, so
  a paste straight from the terminal arrived full of `\x1b[…m` codes. The
  line-based parsers match on line structure, and an escape code glued to a
  line start silently broke the match — **dropping ports and findings with no
  error**. Now stripped once at the entry point so every parser is robust.
  Pinned by a new regression test (`test_ansi_colorized_paste_still_parses`).
- **`tool_read_file` no longer mislabels text as binary.** Reading a capped
  prefix could slice a multi-byte UTF-8 character at the boundary, making an
  ordinary text file raise `UnicodeDecodeError` and come back as
  "binary (hex preview)". Binary is now detected by NUL byte; text is decoded
  leniently so a clipped trailing char becomes one replacement character.
- **`skill_write` validation tightened.** The "must define `run(args)`" check
  used `ast.walk`, so a *nested* or method `run` passed validation even though
  the sandbox runner calls a top-level `run`. Now requires a top-level def.

### Security (the headline)
- **New `kali_safety.py` module** — the hard, setting-independent auto-run floor
  (`is_catastrophic_command`, `command_tampers_self`) now lives here and is
  **structural** instead of a raw-string regex. It shlex-tokenises each
  sub-command, normalises `$IFS`, and recurses into `sh -c` / `eval` payloads,
  so it survives the obfuscations the old regex let straight through:
  - `rm '-rf' /` (quoted flag)
  - `rm${IFS}-rf${IFS}/` (`$IFS` instead of spaces)
  - `cd / && rm -rf *` (root target supplied by a prior sub-command)
  - `find / -delete` / `find / -exec rm …` (no `rm` token)
  - `bash -c "rm -rf /"` (the real command is a `-c` payload)
  - `echo … | base64 -d | sh` (opaque decode-then-execute)
  It is a **strict superset** of the old detector — nothing it used to catch is
  now missed — and stays narrow: `nmap`, `nuclei`, `sqlmap`, and own-directory
  file ops (`rm -rf ~/loot`, `rm -rf ./build`) do not trip it.
- **Self-tamper detection hardened** — writes to Kali's own source via `sh -c`/
  `eval` and `$IFS` are now caught; the `cp`/`mv` check is direction-aware, so
  `cp kali_core.py backup.py` (reading) no longer false-positives while
  `cp evil.py kali_core.py` (overwriting) still force-confirms.
- **Fails safe** — a bug in the detector forces the confirm rather than waving a
  possibly-destructive command through.

### Honesty / docs
- **Rewrote the README safety model** to describe what the code actually does:
  decisive auto-run by default, a hard evasion-resistant floor that always
  force-confirms the irreversible class (disk/FS wipe, recursive root/`$HOME`
  delete, fork bomb, guardrail-stripping), and **Confirm every command** as the
  opt-in for a card on everything. Dropped the overclaims ("impossible",
  "approved one command at a time, every time", "never auto-run").

### Tests
- **New `TestSafetyFloor`** class pins the full catch/ignore contract for both
  detectors (canonical destroyers, every evasion above, and a broad set of safe
  pentest/file commands). Suite now **36 tests** (was 31), all green.
- **Moved `test_kali.py` → `tests/test_kali.py`** to match the file's own
  docstring and `sys.path` logic, so the documented `python3 tests/test_kali.py`
  actually works.

### Presentation / consistency
- `install.sh` `REQUIRED_FILES` now fetches **`kali_safety.py`** (core imports it
  at load — without this a fresh install/update would crash).
- Fixed the stale `kali_core.py` comment that called Groq "the established
  default" — the default is SiliconFlow/DeepSeek-V4-Flash (and tests lock it).
- Architecture diagram and module lists updated to five core modules; the tool
  count in the diagram is now the accurate **49 agent tools**.
- Clarified the `kali_ext/` import invariant in `WIRING.md`: the hook modules
  core calls into import nothing from core; the standalone `worker.py` entry
  point may, since it runs off the core→ext path.
- Version bumped **3.0.0 → 3.1.0** consistently across `kali.py`, the README, and
  the test docstring.

### Not changed (deliberately)
- Provider stack stays locked: SiliconFlow/DeepSeek-V4-Flash primary, Groq
  fallback chain.
- The two large files (`kali.py`, `kali_core.py`) were **not** split — that
  refactor needs a GTK4 display to verify signal wiring and shouldn't be done
  blind.
