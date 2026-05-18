# Oracle

A local AI assistant for Kali NetHunter Pro, Linux desktops, and anything else that runs GTK4 + Python.

No cloud.  No telemetry.  No remote logging.  Lives on your hardware, serves you on it.

---

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
```

That command does the **whole** setup, end to end:

1. Installs Python GTK4 + libadwaita bindings (apt / pacman / dnf)
2. Installs [Ollama](https://ollama.com) if missing, refreshes if present
3. Starts `ollama serve` (via systemd `--user`, or detached if no systemd)
4. Pulls `tinyllama:1.1b` (~640 MB — runs on a OnePlus 6 with headroom)
5. Installs Oracle's code, app launcher, and `.desktop` entry
6. Writes the app's settings so the first launch opens straight into a working chat
7. Smoke-tests the model

When it's done: open your app grid, click **Oracle**, and start talking.

Want a different model?  Override before running:

```bash
ORACLE_MODEL=llama3.2:1b   curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
```

Other small options:

| Model | Size | Notes |
|---|---|---|
| `tinyllama:1.1b` | ~640 MB | default — smallest viable |
| `qwen2.5:0.5b` | ~400 MB | even smaller, surprisingly capable |
| `llama3.2:1b` | ~1.3 GB | noticeably smarter at agent-mode tool calls |
| `phi3:mini` | ~2.3 GB | best 1-bracket reasoning |
| `llama3.1:8b` | ~4.7 GB | desktop-class |

Re-running the same command later just updates everything in place.  Your chats are backed up to `~/.local/share/oracle/backups/` before any code change.

---

## What it does

**Talks.**  Persistent chat history in SQLite.  Sidebar list, search, pin, rename, delete.  Always opens to a fresh chat on launch; old chats are one tap away.  Streaming tokens.  Markdown rendering with proper code blocks (copy button on each).

**Acts.**  Flip the gear toggle in the input bar for **agent mode**.  In agent mode the assistant has tools:

| Tool | What it does | Confirmation? |
|---|---|---|
| `read_file` | reads any file you can read | only for sensitive paths (`~/.ssh`, `/etc/shadow`, etc.) |
| `list_dir` | lists a directory | no |
| `system_info` | uname, RAM, uptime, IPs | no |
| `run` | runs a shell command | **always asks y/n with the command shown** |
| `audit` | full read-only security audit, graded report | no |
| `scan_net` | nmap `-sn` host discovery on your local subnet | no |

The assistant emits tool calls as XML in its reply:

```xml
<tool name="run">{"command": "ss -tlnp", "reason": "see what's listening"}</tool>
```

The app catches them, executes, feeds results back, the conversation continues.

**Audits.**  Same checks as the standalone `ares` tool (read-only, parallel), distilled to the 10 most useful: firewall state, public listening ports, SSH config, pending security updates, kernel age, failed SSH logins, disk encryption, home-dir permissions, AppArmor/SELinux, shell-history secrets.  Graded A+ → F.

**Scans.**  Local subnet discovery via `nmap -sn` if installed, falls back to ARP table.

**Offline by design.**  The assistant has no internet access.  The online indicator is for future tool additions you might wire in.

---

## Manual install (clone first)

```bash
git clone https://github.com/the-priest/oracle5.git
cd oracle5
chmod +x install.sh
./install.sh                  # install or update
./install.sh --update         # explicit update (same code path)
./install.sh --uninstall      # remove (chat history kept)
./install.sh --no-systemd     # skip the systemd unit
./install.sh --no-ollama      # skip ollama install/refresh
./install.sh --no-model       # skip model pull
```

The installer is **idempotent** — re-run any time to update.  It:

- detects existing install → updates files in place, restarts the ollama systemd unit if it was running
- detects existing chat DB → backs it up before touching anything
- bails if Python < 3.10
- installs GTK4/libadwaita if missing
- starts `ollama serve` and waits for it to be healthy before pulling
- verifies the new Python files parse cleanly **before** overwriting working code
- writes `~/.config/oracle/settings.json` with the model pre-selected, so first launch just works

---

## Where things live

| What | Where |
|---|---|
| Code | `~/.local/share/oracle/` |
| Chat database | `~/.local/share/oracle/chats.db` |
| DB backups (auto, each install) | `~/.local/share/oracle/backups/` |
| Settings | `~/.config/oracle/settings.json` |
| Log | `~/.local/share/oracle/oracle.log` |
| systemd unit | `~/.config/systemd/user/oracle-ollama.service` |
| Desktop entry | `~/.local/share/applications/oracle.desktop` |
| Launcher | `~/.local/bin/oracle` |

---

## Personality

The assistant's character lives in `oracle_persona.py` — short, editable.  Two parts you'll probably touch:

- `OPERATOR_PROFILE` — what it knows about you
- `PERSONA_CORE` — tone, style, what it refuses to do

Anything you put in **Settings → System prompt** is appended at runtime, so you can tune per-install without editing the file.

---

## Mobile (Phosh / OnePlus 6)

Split view is adaptive — collapses to single pane on narrow screens.  Use the sidebar-toggle icon in the header to swap between chat list and active chat.

Default model `tinyllama:1.1b` (~640 MB) was chosen specifically to run on 6 GB phones with the GUI loaded.  If you want a noticeably smarter 1B-class model and have spare RAM, set `ORACLE_MODEL=llama3.2:1b` before running the installer.

If `ollama serve` is eating battery in the background:

```bash
systemctl --user disable oracle-ollama.service
systemctl --user stop    oracle-ollama.service
```

Oracle will then start it on demand when you launch the app (controlled by **Settings → Auto-start ollama serve**).

---

## Behaviour notes

**Small models (1–3B) are flaky at emitting tool-call XML.**  A 1B model will sometimes describe what `read_file` would do instead of actually emitting `<tool name="read_file">`.  Workarounds:

1. Use the dedicated buttons in the input bar (audit / scan / sysinfo / attach) — those run the tool directly and inject the result into context, then the model just summarises.
2. Bump to a 7B+ model for proper agent behaviour, if your hardware allows.

**Commands always confirm.**  The "Confirm every command" setting being off just narrows it to risky-looking commands — it never disables confirmation entirely.  You always see the exact command and a y/n prompt before anything runs.

**Sensitive paths** (`~/.ssh`, `/etc/shadow`, `~/.gnupg`, `~/.aws`, etc.) trigger an extra confirmation before reads, even in agent mode.  The list lives in `oracle_core.py:SENSITIVE_PATHS` — edit to taste.

---

## Customising

Things designed to be edited:

- **`oracle_persona.py`** — persona, tool contract, capabilities list
- **`oracle_core.py:SENSITIVE_PATHS`** — what triggers extra confirms
- **`oracle_core.py:AUDIT_CHECKS`** — add/remove security checks
- **`oracle.py:CSS`** — Catppuccin Mocha palette, swap any color
- **Settings → System prompt** — per-install addendum, no code edit needed

---

## License

MIT.  Do whatever.
