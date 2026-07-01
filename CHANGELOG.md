# Changelog

## v4.2.0 — benchmarking: prove it with a number

You can't out-benchmark the field on vibes. This release adds the instrument
that turns "it's the best" into a measurable, reproducible score.

- **Benchmark harness (new `kali_ext/bench.py`).** Four tools that score a run
  objectively: `benchmark_targets` (the known vuln set of standard practice
  targets — Juice Shop, DVWA, WebGoat — i.e. what a perfect score looks like);
  `benchmark_score` (match a run's findings against that ground truth →
  precision, recall, F1, per-class coverage; missed classes are the real gaps,
  extras are possible false positives); `benchmark_report` (a clean markdown
  scorecard); and `benchmark_compare` (rank several runs by F1 — Kali vs another
  tool, or version vs version, so "beats the best" is a sortable column). Scores
  by canonical vuln class via CWE and keyword matching, and honors an explicit
  class a finding already carries.
- **Coverage.** New suite `tests/test_bench.py` (26) covering the scoring math,
  classification, report and comparison. The installer now verifies **14**
  `kali_ext` modules.

---

## v4.1.1 — engagement state + operator loop

Kali stops forgetting. This release adds the campaign-level brain that turns it
from a tool that runs one-off commands into an operator that runs a whole job —
plus scope enforcement and a scanner invocation builder.

- **Engagement state (new `kali_ext/engage.py`).** Nine tools, all local and
  propose/read-only: an authorised-**scope** allowlist with a `scope_check`
  that FAILS CLOSED (unset scope / unparseable target / no match ⇒ out of
  scope); an **asset graph** (`asset_record`, `engagement_graph`) that models
  hosts, services, findings and footholds; a **loot** store (`loot_record`,
  `loot_list`) with secrets redacted in all output; `loot_reuse` for
  in-scope-only lateral-movement suggestions; and **`graph_ingest`**, which
  turns parsed scan output straight into graph state so the picture maintains
  itself from what was actually run.
- **Scope enforcement on active work.** `sqlmap_plan` (below) refuses to build
  a command for a target that isn't in the recorded authorised scope, and the
  operator loop checks scope before anything active is proposed.
- **`sqlmap_plan` — scanner invocation builder.** Constructs the correct,
  parameterised sqlmap command (detect → enumerate → dump) for the operator to
  approve and run through the gate. Injection-safe quoting; level/risk clamps;
  it proposes, it never executes; and it deliberately does **not** build
  SQLi-to-RCE (`--os-shell`/`--os-pwn`) — that trigger stays operator-driven.
- **Coverage.** New suites `tests/test_engage.py` (25) and `tests/test_sqlmap.py`
  (21). The installer now fetches and verifies **13** `kali_ext` modules.

---

## v4.1.0 — code auditing, exploitation write-ups, silver theme

The offensive workflow was strong on *live hosts*; this release adds the other
half — auditing **code, dependencies and secrets** — plus the report section
that documents how access was obtained, and a visual refresh.

- **Code &amp; dependency audit (new `kali_ext/codescan.py`).** Five propose-only /
  read-only tools that drive the standard scanners and make sense of them:
  `code_tooling_check` (SAST/SCA/secrets/IaC inventory), `code_scan_plan`
  (auto-detects languages/lockfiles/IaC and builds an ordered, proposed scan
  plan — runs nothing), `parse_scan` (normalises Semgrep / Bandit / gitleaks /
  trufflehog / OSV-Scanner / Trivy / pip-audit / npm audit / retire.js / Nuclei
  JSON into one schema), `triage_findings` (**cross-scanner dedup** — two tools
  agreeing on a CVE+package or `file:line` collapse to one corroborated finding;
  one severity scale; flags the low-confidence ones), and `remediation_hint`
  (standard non-exploit fix pointers by CWE class).
- **`attack_writeup` — the exploitation narrative.** Turns the tamper-evident
  evidence ledger into the reproducible "how access was obtained" report
  section: the step sequence is backed by the actual hash-verified commands that
  ran, and secrets are auto-redacted. Documents an authorised, already-executed
  path; writes no exploit code.
- **Silver theme.** Kali's chat bubble and name label move from red to a
  metallic silver that matches her icon.
- **Coverage.** New offline suites (`tests/test_codescan.py`, plus write-up and
  headroom checks) — the code-audit parsers, cross-tool triage, secret
  redaction, and the context-compression savings are all pinned by tests. The
  installer now fetches and verifies **12** `kali_ext` modules.

---

## v4.0.0

Milestone release. Everything from the 3.8.x line — provider trim to Groq +
SiliconFlow, the honesty hardening (machine facts read, never guessed), the
de-paused voice, the redesigned composer, Brave browsing with ad/consent
handling, the self-test bug sweep, and the kali_ext update hardening — rolled up
into 4.0.

This release:
- **Composer is one unit.** The text field and the Send button now fill to the
  same height and sit level inside a single rounded bubble, so they read as one
  control instead of a field with a button floating beside it.

---

## v3.8.4 — Brave browsing + bulletproof updates

- **The browser drives Brave when it's installed.** Brave is Chromium underneath,
  so Playwright runs it directly — and its Shields block ads and trackers, so
  pages load clean. Falls back to bundled Chromium if Brave isn't present.
- **Cookie/consent walls no longer stop browsing.** After a page loads, Kali
  auto-clicks the common "Accept all / I agree" buttons and strips leftover
  consent/cookie modals, and the most common consent-management, ad and tracker
  hosts are blocked at the network layer so their banners never load. This
  applies whether or not Brave is installed.
- **Installer can fetch Brave** with `WITH_BRAVE=1` (otherwise it just detects an
  existing Brave and tells you it'll be used).
- **Updates now verify the whole sidecar arrived.** Re-running the installer
  already replaces every file and the full kali_ext, but the remote fetch could
  silently drop a module; it now checks all 11 modules landed, retries any that
  didn't, and refuses to install a partial sidecar over a working one.

---

## v3.8.3 — Self-test bug sweep (6 fixes)

Fixes from a full on-device self-test (62 tool calls, ThinkPad X395):

- **skill_run no longer loses the skill name** (was "no skill named ''", blocked
  ALL skill execution). The tool-call parser was unwrapping skill_run's legit
  `args` field and throwing away `name`. Now it only unwraps a sole-key
  `{arguments:{...}}` envelope, and never for skill_run.
- **Browser self-heals after a closed session** (was TargetClosedError forever
  on reuse). The worker now detects a dead page/context/browser and rebuilds it,
  retrying the operation once instead of hammering the corpse.
- **screenshot with save_path won't claim false success.** It was returning
  ok:true on the tool's exit code without checking a file appeared. Every
  capture path now verifies the file exists and is non-empty, and says so
  honestly if nothing was written.
- **memory_remember accepts the fields the model actually uses.** It only read
  `text`; calls with `value`/`content`/`fact` or a `key`+`value` pair were
  dropped as "empty". Now all are accepted (key+value become "key: value"), and
  recall/forget take the same aliases. (The em-dash was never the problem.)
- **web_verify corroboration recognises agreement, not just matching prose.**
  Sources describing the same CVE in different words scored ~0.18 despite
  agreeing. It now also compares high-signal anchors (CVE IDs, versions, scores,
  acronyms) and takes the stronger signal — the regreSSHion case now scores ~0.9.
- **analyze_image** error message now names the real path (Settings -> Display ->
  Images & vision) and the providers that have vision (SiliconFlow Qwen2.5-VL,
  Groq Llama vision). It was a config gap, not a code bug.

---

## v3.8.2 — Harder honesty: check before claiming

- **She can't state machine facts from the air anymore.** The immutable
  guardrail now mandates: never assert a checkable fact without checking it
  first, and anything about your hardware or system state — RAM, disk, CPU, OS,
  what's installed, what's running — is READ with a read-only tool, never
  recalled or guessed. The "how much RAM do I have" case is called out by name:
  she runs system_info and reports the real figure. Because the guardrail is
  load-bearing and verified preserved on self-edits, she can't quietly drop this.
- **system_info is now complete** — it returns real RAM, CPU model, core count,
  OS, hostname, uptime and load, all read live, so one free call covers the
  specs people actually ask about.
- Verification section gains a dedicated machine/local-facts block, and
  reinforces that confirmed-by-tool, inferred, and unknown are never blurred,
  with anything unverified labelled out loud.

---

## v3.8.1 — Voice de-paused, UI cleanup, identity fixed

- **Voice no longer drags with long pauses.** Three fixes: newlines and blank
  lines (and code blocks) now collapse to a single flowing line instead of
  becoming dead air; Piper's between-sentence silence is detected and set to ~0
  so there's no long stop after every period (espeak gets `-g 0`); and replies
  are spoken as fewer, larger utterances so there are fewer gaps. Tunable via a
  new tts_sentence_pause setting (default 0).
- **She knows what she is.** Kali no longer roleplays being your operating
  system — she's the assistant (JARVIS / your Skynet) running as an app ON your
  machine, with real hands on it through her tools, loyal to you.
- **Header slimmed.** Removed the model + agent line from the top (the model
  shows in the composer switcher, agent state shows as the green toggle), and
  the title bar is thinner.
- **Composer input is a bubble now** so it reads as a field instead of bleeding
  into the bottom edge; it highlights green while focused.
- **Kali's message bubbles are translucent red** — see-through, contrasting your
  translucent green.
- **Log button moved** in next to the other toolbar buttons.
- **Removed the chat search box.**

---

## v3.8.0 — Two providers, extensions panel, MCP toggle, risk-based confirm

- **Providers trimmed to Groq + SiliconFlow.** OpenAI, Anthropic and Google
  removed; an old config pointing at any of them falls back to SiliconFlow.
- **Extensions panel in Settings → Generation.** Toggles for Memory, Skills and
  Foresight (all ON by default now), plus an MCP switch you can flip on/off at
  runtime, a field to add MCP servers, and a live status line. MCP still defaults
  OFF — it runs external subprocesses (an RCE surface).
- **Risk-based confirmation.** Safe commands run without interruption; risky ones
  (foresight "caution"/"block" — broad deletes, service stops, firewall flushes,
  force-push) now STOP for your explicit OK instead of being silently auto-run or
  flatly refused; truly catastrophic commands remain hard-blocked with no override.
  Net effect: Kali keeps going until something genuinely needs your call.
- **More autonomy headroom** — tool-chain budget raised 20 → 50.
- **Model switcher**: bigger text, ordered most-expensive → cheapest.
- **Brighter dragon** everywhere (app icon + avatar). Send button now blends into
  the background so only the silver dragon logo pops; it glows while working.
- **Fixed the sidecar packaging.** The release now ships the COMPLETE kali_ext/
  (all modules + package init), so memory/skills/foresight/pentest/MCP actually
  load on device — previously some modules were missing from the zip and silently
  no-op'd. The curl|bash installer already pulled the full set from GitHub.

---

## v3.7.2 — Claude works the right way, browser fallback, real icon

- **Anthropic / Claude now uses the NATIVE Messages API** (`/v1/messages`)
  instead of the OpenAI-compat shim that kept rejecting every model as
  "not_found". This is how Anthropic is actually meant to be called: the system
  prompt goes top-level, messages are converted to Anthropic's format (user-first,
  alternating roles), `max_tokens` is sent, auth is `x-api-key` + `anthropic-version`,
  and the reply is parsed from Anthropic's own event stream. If a model id isn't on
  your account it fetches your real model list and self-heals.
- **Browser has a headless fallback.** When Playwright's chromium can't launch
  (common on ARM / NetHunter), read-only browsing — goto, read, links, url, title —
  now works over plain HTTP so Kali can still look things up. Clicking and typing
  still need a working chromium and say so clearly.
- **Real app icon.** The launcher icon is now your actual dragon (the rough
  low-poly traced one is gone), embedded so there's no icon-cache conflict.

---

## v3.7.2 — Anthropic self-heals, browser browses without chromium

- **Claude: stop guessing model IDs.** The real fix for the 404s — Anthropic's
  /models endpoint needs the native `x-api-key` header (not Bearer), so the live
  model lookup was silently failing and the app fell back to guessed IDs that
  your account doesn't expose. It now sends `x-api-key`, fetches the actual
  models your key can use, and tries those first. If a picked model 404s it
  recovers automatically instead of dead-ending.
- **Browser works even when chromium won't launch.** On ARM / headless NetHunter,
  Playwright's chromium often can't start. The browser now falls back to a
  headless HTTP mode for read-only actions — goto, read, and links all work
  without a GUI browser (verified end-to-end). Clicking and typing still need a
  real chromium (clear message tells you so), but Kali no longer just fails when
  the window can't open.

---

## v3.7.1 — Anthropic / Claude fixed

- **Claude works now.** Three causes of the HTTP 404: the request was missing
  Anthropic's required `anthropic-version` header (now sent), the model chain
  used `-latest` aliases that the OpenAI-compatible endpoint doesn't resolve
  (now dated model IDs), and a bug in the fallback made a bad model id dead-end
  instead of trying the rest of the chain (now it walks the chain and self-heals
  via the live model list).
- **Claude line-up:** Sonnet 3.5 (safe default), Claude 4 Sonnet, Claude 4 Opus
  (most capable), Claude 3.5 Haiku, and Claude 3 Haiku (cheapest — close to
  DeepSeek pricing). A stale `-latest` selection auto-migrates to a valid model.
- Clearer provider error messages that point at the key / model switcher.

---

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
