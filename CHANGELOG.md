# Changelog

## v3.7.0 — Browser fixed, composer & chat redesign

- **Browser tools actually work now.** Playwright's sync API is thread-bound, but
  every tool call ran on its own thread — so the browser worked once then threw
  thread/greenlet errors on every call after. All browser operations now run on
  one dedicated worker thread, so a session survives across calls. Also added
  more actions so Kali can browse freely: submit (fill + Enter), press a key,
  scroll, back/forward, and list links — alongside goto/read/click/fill/screenshot.
- **Kali's avatar is the clean dragon now** — a solid silver dragon PNG, and the
  green ring is gone from the emblem SVG (it looked like a sticker).
- **Chat bubbles reworked.** Your messages are translucent (the dragon shows
  through); Kali's were invisible (transparent) and are now a solid, clearly
  visible bubble.
- **New chats are clean** — the "Hello, Priest" greeting and the
  audit/downloads/updates suggestion buttons are gone (those live in the
  toolbar); a fresh chat just shows the dragon watermark.
- **One big Send button.** The mic/STT button is removed; Send is now large and
  wears the dragon logo. While Kali is working it pulses with a red glow instead
  of turning into a stop icon — and tapping it still stops her.

---

## v3.6.0 — Providers, on-the-fly model switching, UI overhaul

- **Switch model/provider from the composer.** A new button above the text box
  shows the active provider and model (e.g. "siliconflow · DeepSeek-V4-Flash");
  tap it to pick any model from any provider you hold a key for, grouped by
  provider, applied instantly — no trip to Settings.
- **Providers updated.** Removed GitHub Models and Novita; added **OpenAI**
  (GPT-4o / GPT-4.1 / o-series) and **Anthropic / Claude** (via its
  OpenAI-compatible endpoint). An old config pointing at a removed provider
  falls back to SiliconFlow automatically.
- **Bigger text input** — the compose box is now much taller by default.
- **Header redesign.** Dropped the "personal · loyal · yours" tagline; KALI is
  now a menacing red, letter-spaced title sitting next to the new-chat button.
  The SiliconFlow / Online pills in the top-right are gone — connectivity is now
  a single green (online) / red (offline) dot next to KALI.
- **The saved-chats list looks the part now** — a fire-coloured accent stripe,
  cleaner typography, and a subtle ember-glow animation on the selected chat
  instead of plain text on black.
- **Pick the vision model in Settings.** Display → Images & vision lets you set
  the vision provider + model Kali uses to see images, and toggle inline image
  rendering.
- **Smarter auto-naming.** New chats are titled from the first message with the
  filler stripped ("can you scan my network…" → "Scan my network").
- **Fixed the phone UI occasionally growing past the screen.** An inline image
  was setting its width as a hard minimum at up to 480px; it's now capped to the
  viewport (minus the avatar column) and allowed to shrink, and long code lines
  can no longer force the window wider either.

---

## v3.5.1 — Catastrophic commands are now actually BLOCKED

Critical safety fix. Previously a system-destroying command only triggered a
"Run anyway" confirmation, and the consequence predictor (foresight) was off by
default — so nothing actually stopped `rm -rf /`. That's fixed.

- **Hard block, no override.** A command in the catastrophic class (`rm -rf /`,
  `mkfs`, `dd` onto a disk, fork bomb, recursive delete of root / system /
  data dirs) is now REFUSED outright at the top of the execution path — before
  any dialog, before foresight, before the shell. There is no "Run anyway"
  button and no setting that disables it. Kali, as an AI, will never run a
  system-destroying command.
- **Foresight on by default.** `foresight_enabled` now defaults to **on**, so
  the consequence predictor actually runs and gates risky commands instead of
  sitting inert.
- **Closed detection gaps:** a path glued to the flag cluster (`rm -rf/`,
  `rm -rf/home`) is now caught, and deleting a bare critical data/mount dir
  (`/home`, `/mnt`, `/media`, `/opt` — the directory itself) is now
  catastrophic, while subdirectories under them (`/home/me/loot`) stay allowed.
- **Tests:** the catastrophic-command suite now covers the glued-slash forms and
  the data-dir cases, with matching allow-cases so real work isn't over-blocked.

---

## v3.5.0 — Kali can see, faster speech

- **Kali can SEE images now.** New `analyze_image` sends a photo or screenshot
  to a vision model and returns what's actually in it — the scene, objects,
  people, and any text in the image. She's no longer limited to text. Needs a
  vision model configured (`vision_model` + that provider's key; defaults to a
  SiliconFlow VL model).
- **Camera + face detection.** A new camera button in the composer captures a
  photo (`capture_photo`, with libcamera/fswebcam/ffmpeg fallbacks) and drops it
  in ready for Kali to look at. `detect_faces` finds/counts faces locally
  (detection only).
- **Speech is much faster and smoother.** The reader used to spawn a new process
  at every period, so it stopped between every sentence and was slow to start.
  It now merges sentences into a few larger utterances (no gap at each period),
  keeps the first chunk short so audio starts quickly, and the default rate is a
  bit snappier (1.15x).
- **A deliberate boundary:** Kali will not identify a person or find their
  social-media accounts from their face. Face *detection* (where faces are) is
  fine; biometric *identification* of strangers is not — it's surveillance, and
  it's out.

---

## v3.4.1 — UI fixes & accessibility

A round of interface fixes and theming polish.

- **Right-click menu lands where you click.** The chat context menu (pin /
  rename / delete) was parented to the row but positioned with listbox
  coordinates, so it popped up in a random spot. It now appears exactly at the
  click, and cleans itself up on close.
- **Operator avatar is now a cross.** Replaced the "L" initial with a steel
  gothic cross (with a red gem).
- **Read-aloud moved under the message.** The play button left the far-right of
  the header for a clearly-labelled "Listen" button beneath each reply, where
  it's easy to reach.
- **Buttons are rounder** (11px), not circular — across the composer, mic, and
  generic buttons.
- **Send / attach restyled to the dragon theme.** Send is a menacing red
  gradient with a glow (it's also the Stop button); the action icons are subtle
  with a green hover. The sidebar-toggle and new-chat buttons are now flat and
  dim so they blend into the header, with a quiet green accent on hover.
- **Attach pictures/images works.** `Gtk.FileDialog` is GTK 4.10+, so on older
  Phosh/NetHunter GTK the attach button silently did nothing — added a
  `FileChooserNative` fallback. Images now embed as viewable inline pictures
  instead of being read as binary garbage.
- **OnePlus 6 over-wide UI fixed.** The sidebar now collapses on narrow screens
  reliably (breakpoint raised to 820px, scale-aware fallback), and the composer
  toolbar scrolls horizontally so a row of buttons can't force the window wider
  than the screen.
- **Theme cleanup.** Removed the last blue accents (focus rings, terminal log
  text, diff headers) so the UI is consistently red / green / black.

---

## v3.4.0 — Dragon makeover (red/green/black)

A visual overhaul of the look.

- **Dragon emblem icon.** A simple low-poly SVG traced from the Kali dragon
  logo (coiled body, spread wings, circle ring) in a blackout style with a green
  accent ring. Used as the app/taskbar icon and the chat avatar.
- **Dragon watermark behind the chat.** The dragon logo now sits faintly behind
  the conversation (`kali-watermark.png`, black made transparent so it blends on
  the dark bg), drawn via a `Gtk.Overlay` so messages render over it. The
  watermark loader handles PNG or SVG.
- **Red / green / black theme.** Swapped the old blue accent for toxic green as
  the primary accent (links, focus, online, the operator label) and red for
  Kali's identity (the Kali label, the emblem glow, alerts). All backgrounds
  stay black.
- **Plumbing:** `install.sh` ships `kali-watermark.png` and places it (and the
  emblem) in the install dir so the watermark works on a fresh install.

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
