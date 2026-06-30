#!/usr/bin/env python3
"""
kali — personal AI assistant.  GTK4 + libadwaita UI.

Run:    python3 kali.py
Or, after install:  kali
"""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import (Gtk, Adw, GLib, Gdk, Gio, Pango, GObject,  # noqa
                          GdkPixbuf)

import sys
import os
import re
import json
import threading
import urllib.request
import datetime
from typing import List, Dict, Any, Optional, Callable

from kali_core import (
    GroqBackend, OpenAICompatBackend, BackendRouter,
    ChatStore, Chat,
    load_settings, save_settings, log,
    tool_read_file, tool_list_dir, tool_run_command, tool_system_info,
    tool_write_file, make_edit_diff,
    tool_check_updates, tool_recent_downloads, tool_service_status,
    tool_journal_tail, tool_disk_usage, tool_processes,
    tool_network_status, tool_find_file,
    run_security_audit, format_audit_for_chat,
    run_network_scan, format_scan_for_chat,
    tool_desktop_info, tool_list_apps, tool_launch_app,
    tool_list_windows, tool_focus_window, tool_close_window,
    tool_notify, tool_type_text, tool_press_key,
    tool_media_control, tool_screenshot, tool_read_screen,
    tool_make_dir, tool_copy_path, tool_move_path, tool_delete_path,
    tool_path_info, tool_open_url, tool_browser,
    tool_web_search, tool_web_read, tool_github,
    tool_image_search,
    tool_analyze_image, tool_capture_photo, tool_detect_faces,
    tool_web_verify, tool_tooling_check, tool_pentest_plan, tool_cve_lookup,
    tool_parse_output, tool_methodology, tool_wordlist_find,
    tool_cheatsheet, tool_report_findings,
    tool_nuclei_template, tool_reflect_findings,
    tool_osint_username, tool_osint_lookup, tool_social_read,
    quick_facts as tool_quick_facts,
    sudo_cached, detect_urgency, looks_degraded,
    note_command, recent_duplicate,
    parse_tool_calls, strip_tool_calls,
    extract_think_blocks, strip_think_blocks,
    is_online, is_sensitive_path, command_needs_sudo, is_catastrophic_command,
    command_tampers_self, Watcher,
    PROVIDERS, PROVIDERS_BY_KEY,
    get_ledger,
)
from kali_persona import (
    build_system_prompt, assemble_messages, title_from_first_message,
)

# Voice (speech in / speech out) is optional.  If kali_voice is missing or
# fails to import, the app runs exactly as before — every voice hook below
# guards on `self.stt` / `self.tts` being present.
try:
    import kali_voice
    kali_voice.set_logger(log)
    _VOICE_OK = True
except Exception as _ve:  # noqa
    kali_voice = None
    _VOICE_OK = False

APP_ID  = "org.thepriest.kali"
APP_NAME = "Kali"
VERSION = "3.8.1"

# ── Tool-chain efficiency knobs ──
# How many model round-trips a single user turn may chain through.  With
# read-only tools now batched (many lookups per round-trip), this budget
# stretches much further than it looks.  On hitting it Kali doesn't dead-
# end — it takes one final, tool-free turn to answer with what it gathered.
# The y/n confirmation gate and the catastrophic-command hard block still
# fire independently, so a high budget never means an unsupervised risky run.
MAX_TOOL_CHAIN = 50
# Parallel workers when several read-only tools fire in one turn.
TOOL_BATCH_MAX_WORKERS = 6
# Keep this many most-recent tool_result blocks at full length in the
# history resent to the model; older ones get trimmed to a stub (they've
# already been consumed) so a long research chat doesn't re-bill huge
# outputs every turn.
HISTORY_KEEP_FULL_TOOL_RESULTS = 2
HISTORY_TRIM_HEAD_CHARS = 600


# ═════════════════════════════════════════════════════════════════════
# THEME — Catppuccin Mocha, generously sized, cozy
# ═════════════════════════════════════════════════════════════════════

# Note: GTK CSS doesn't support CSS variables across rules.  We inline
# the palette by hand and use `font-size` numbers that are large enough
# to read on a phone screen without squinting.

CSS = b"""
/* =====================================================================
   KALI THEME - modelled on the official Kali Linux desktop palette:
   near-black surfaces, the Kali dragon-blue accent (#15a838 / #2ee65f),
   red for danger, monospace for headers and machine output.  Built to
   read like a first-party Kali tool, not a pastel toy.
   GTK CSS has no variables across rules, so the palette is inlined.

   Palette:
     bg base    #0d0f12   surfaces  #14171c / #1b1f26   line  #262b33
     text       #d6dbe2   dim       #7d8794
     accent     #15a838   accent-hi #2ee65f   accent-dim rgba(46, 230, 95,.15)
     ok/green   #2ecc71   warn      #f0a500   danger #e5484d
   ===================================================================== */

/* ===== Adwaita named-color overrides =====
   libadwaita widgets (SwitchRow, SpinRow, ComboRow, AlertDialog buttons,
   focus rings, selections, links) pull these named colours.  Without
   overriding them every built-in control renders in GTK's stock blue or
   the user's Plasma accent - which is exactly what made the UI look
   inconsistent.  Retint them ALL to the Kali palette in one place. */

@define-color accent_color              #2ee65f;
@define-color accent_bg_color           #15a838;
@define-color accent_fg_color           #ffffff;

@define-color destructive_color         #e5484d;
@define-color destructive_bg_color      #e5484d;
@define-color destructive_fg_color      #ffffff;

@define-color success_color             #2ecc71;
@define-color success_bg_color          #2ecc71;
@define-color success_fg_color          #0d0f12;
@define-color warning_color             #f0a500;
@define-color warning_bg_color          #f0a500;
@define-color warning_fg_color          #0d0f12;
@define-color error_color               #e5484d;
@define-color error_bg_color            #e5484d;
@define-color error_fg_color            #ffffff;

@define-color window_bg_color           #0d0f12;
@define-color window_fg_color           #d6dbe2;
@define-color view_bg_color             #14171c;
@define-color view_fg_color             #d6dbe2;
@define-color headerbar_bg_color        #14171c;
@define-color headerbar_fg_color        #d6dbe2;
@define-color headerbar_border_color    #262b33;
@define-color popover_bg_color          #14171c;
@define-color popover_fg_color          #d6dbe2;
@define-color dialog_bg_color           #14171c;
@define-color dialog_fg_color           #d6dbe2;
@define-color card_bg_color             #1b1f26;
@define-color card_fg_color             #d6dbe2;
@define-color sidebar_bg_color          #0a0c0f;
@define-color sidebar_fg_color          #d6dbe2;

@define-color borders                   #262b33;

/* ===== Base ===== */

window, .background {
    background-color: #0d0f12;
    color: #d6dbe2;
    font-family: 'Inter', 'Cantarell', 'SF Pro Text', sans-serif;
}

headerbar {
    background-color: #14171c;
    color: #d6dbe2;
    border-bottom: 1px solid #262b33;
    min-height: 56px;
    padding: 4px 8px;
}

.sidebar {
    background-color: #0a0c0f;
    border-right: 1px solid #262b33;
}

/* ===== App branding ===== */

.app-title {
    font-size: 26px;
    font-weight: 900;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    color: #ff3a47;
    letter-spacing: 4px;
    text-shadow: 0 0 12px rgba(255, 58, 71, 0.45);
}
/* Connectivity dot beside KALI: green online, red offline */
.online-dot {
    font-size: 13px;
    margin-top: 2px;
}
.online-dot.online {
    color: #2ee65f;
    text-shadow: 0 0 7px rgba(46, 230, 95, 0.7);
}
.online-dot.offline {
    color: #ff3a47;
    text-shadow: 0 0 7px rgba(255, 58, 71, 0.7);
}
.app-subtitle {
    font-size: 16px;
    color: #7d8794;
    font-family: 'JetBrains Mono', monospace;
    margin-top: 2px;
}

.chat-title {
    font-size: 16px;
    font-weight: 600;
    color: #d6dbe2;
}
/* Composer input as a rounded bubble so it reads as a contained field
   instead of bleeding into the bottom edge. */
.input-frame {
    background-color: #14181d;
    border: 1px solid #232a32;
    border-radius: 20px;
    padding: 4px 8px;
    margin-bottom: 8px;
}
.input-frame:focus-within {
    border-color: #2ee65f;
    background-color: #161b21;
}
.chat-subtitle {
    font-size: 16px;
    color: #7d8794;
}

/* ===== Sidebar chat list ===== */

.chat-row {
    background-color: transparent;
    border-radius: 11px;
    padding: 15px 16px 15px 18px;
    margin: 5px 8px;
    min-height: 64px;
    border-left: 3px solid transparent;
    transition: background-color 160ms ease, border-color 160ms ease;
}
.chat-row:hover {
    background-color: #14171c;
    border-left-color: rgba(46, 230, 95, 0.55);
}
.chat-row.selected, .chat-row:selected {
    background: linear-gradient(90deg, rgba(255, 58, 71, 0.16),
                rgba(46, 230, 95, 0.05) 55%, rgba(13, 15, 18, 0) 90%);
    border-left: 3px solid #ff3a47;
    box-shadow: inset 0 0 0 1px rgba(255, 58, 71, 0.10);
    animation: emberglow 2.6s ease-in-out infinite;
}
@keyframes emberglow {
    0%   { border-left-color: #ff3a47; box-shadow: inset 0 0 0 1px rgba(255,58,71,0.10), -2px 0 10px rgba(255,58,71,0.20); }
    50%  { border-left-color: #ff8a2f; box-shadow: inset 0 0 0 1px rgba(255,138,47,0.14), -2px 0 14px rgba(255,138,47,0.30); }
    100% { border-left-color: #ff3a47; box-shadow: inset 0 0 0 1px rgba(255,58,71,0.10), -2px 0 10px rgba(255,58,71,0.20); }
}
.chat-row .title-line {
    color: #e8ebef;
    font-weight: 600;
    font-size: 15px;
}
.chat-row .meta-line {
    color: #6d7680;
    font-size: 11.5px;
    letter-spacing: 0.3px;
    margin-top: 3px;
}
.chat-row .pin-icon {
    font-size: 12px;
}

/* ===== Empty states ===== */

.empty-state {
    color: #5a626d;
    padding: 60px 32px;
}
.empty-state-title {
    font-size: 34px;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    color: #d6dbe2;
    margin-bottom: 18px;
}
.empty-state-body {
    font-size: 22px;
    color: #7d8794;
    line-height: 1.55;
}

/* ===== Message bubbles ===== */

.msg-row {
    padding: 4px 0;
}

/* User: right-aligned bubble */
.msg-user {
    background-color: rgba(46, 230, 95, 0.08);
    color: #eef2f6;
    border-radius: 12px 12px 4px 12px;
    padding: 18px 22px;
    margin: 8px 12px 8px 60px;
    font-size: 30px;
    line-height: 1.45;
    border: 1px solid rgba(46, 230, 95, 0.22);
}

/* Assistant: left-aligned, translucent RED bubble (contrast to user green) */
.msg-assistant {
    background-color: rgba(255, 58, 71, 0.09);
    color: #f1eaea;
    padding: 16px 20px;
    margin: 8px 60px 8px 12px;
    font-size: 30px;
    line-height: 1.55;
    border-radius: 12px 12px 12px 4px;
    border: 1px solid rgba(255, 58, 71, 0.26);
}

/* Compact tool indicator (replaces visible JSON dump) */
.msg-tool-indicator {
    padding: 6px 16px 6px 70px;
    margin: 2px 12px;
}
.tool-indicator-label {
    color: #7d8794;
    font-size: 17px;
    font-family: 'JetBrains Mono', monospace;
    opacity: 0.85;
}

/* Model reasoning ("thoughts") - collapsed by default, click to open */
.thoughts-expander {
    margin: 2px 0 4px 0;
    font-size: 15px;
    color: #8a93a0;
}
.thoughts-expander > title {
    color: #8a93a0;
    opacity: 0.9;
}
.thoughts-text {
    color: #9aa4b2;
    font-family: 'JetBrains Mono', monospace;
    font-size: 15px;
    background: rgba(125,135,148,0.08);
    border-left: 2px solid rgba(125,135,148,0.35);
    padding: 8px 10px;
    border-radius: 4px;
}

.msg-system-notice {
    color: #7d8794;
    font-style: italic;
    font-size: 18px;
    padding: 8px 16px;
    margin: 4px 16px;
}

/* Avatar dots */
.avatar {
    border-radius: 6px;
    min-width: 52px;
    min-height: 52px;
    background-color: #1b1f26;
    font-weight: bold;
    font-size: 22px;
    color: #d6dbe2;
}
.avatar-user {
    background-color: #262b33;
    color: #d6dbe2;
}
.avatar-kali {
    background: linear-gradient(135deg, #8b0010, #ff2d3a);
    color: #0d0f12;
    border: 1px solid #ff5566;
    box-shadow: 0 0 10px rgba(255, 45, 58, 0.55);
}

.role-label {
    color: #7d8794;
    font-weight: 700;
    font-size: 17px;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    margin: 0 0 5px 0;
}
.role-label.user { color: #2ee65f; }
.role-label.kali { color: #ff3a47; }

/* ===== Code blocks ===== */

.code-block {
    background-color: #0a0c0f;
    border: 1px solid #262b33;
    border-radius: 6px;
    padding: 0;
    margin: 8px 4px;
}
.image-block {
    margin: 8px 4px;
}
.chat-image {
    border: 1px solid #262b33;
    border-radius: 8px;
    background-color: #0a0c0f;
}
.image-caption {
    color: #7d8794;
    font-size: 11px;
    margin: 2px 2px;
}
.code-block-header {
    background-color: #14171c;
    color: #7d8794;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
    padding: 6px 12px;
    border-bottom: 1px solid #262b33;
    border-radius: 6px 6px 0 0;
}
.code-block textview {
    background-color: transparent;
    color: #d6ffdf;
    font-family: 'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', monospace;
    font-size: 22px;
    padding: 16px 18px;
}

/* ===== Status pills ===== */

.status-pill {
    background-color: #1b1f26;
    color: #7d8794;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 16px;
    font-weight: bold;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.5px;
}
.status-pill.online   { background-color: #2ecc71; color: #0d0f12; }
.status-pill.offline  { background-color: #262b33; color: #d6dbe2; }
.status-pill.error    { background-color: #e5484d; color: #ffffff; }
.status-pill.groq     { background: linear-gradient(135deg, #15a838, #2ee65f);
                        color: #ffffff; }

/* ===== Settings ===== */

.settings-section-title {
    color: #2ee65f;
    font-weight: bold;
    font-size: 17px;
    font-family: 'JetBrains Mono', monospace;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 16px 4px 6px 4px;
}

/* ===== Confirm dialog ===== */

.confirm-cmd {
    background-color: #0a0c0f;
    color: #2ee65f;
    font-family: 'JetBrains Mono', monospace;
    font-size: 20px;
    padding: 16px;
    border-radius: 6px;
    border: 1px solid #262b33;
    margin: 10px 0;
}

/* ===== Scrollbar -- wider for touch ===== */

scrollbar slider {
    background-color: #2f3640;
    border-radius: 8px;
    min-width: 16px;
    min-height: 50px;
}
scrollbar slider:hover { background-color: #3d4651; }
scrollbar slider:active { background-color: #15a838; }

/* ===== Entry ===== */

entry {
    background-color: #1b1f26;
    color: #d6dbe2;
    border-radius: 6px;
    padding: 12px 16px;
    border: 1px solid #262b33;
    font-size: 20px;
}
entry:focus-within { outline: 2px solid #15a838; border-color: #15a838; }

passwordentry {
    background-color: #1b1f26;
    color: #d6dbe2;
    border-radius: 6px;
    padding: 12px 16px;
    border: 1px solid #262b33;
    font-size: 20px;
}

/* ===== Quick-action chips in empty state ===== */

.quick-chip {
    background-color: #1b1f26;
    color: #d6dbe2;
    border: 1px solid #262b33;
    border-radius: 6px;
    padding: 14px 24px;
    font-size: 19px;
    min-height: 40px;
}
.quick-chip:hover {
    background-color: #1f2530;
    color: #2ee65f;
    border-color: #15a838;
}

/* ===== Terminal log panel ===== */

.terminal-panel {
    background-color: #07080a;
    border-top: 2px solid #262b33;
}

.terminal-panel-header {
    background-color: #0a0c0f;
    border-bottom: 1px solid #262b33;
    padding: 6px 12px;
    min-height: 40px;
}

.terminal-panel-title {
    color: #2ee65f;
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    font-weight: bold;
    letter-spacing: 1px;
}

.terminal-log-view {
    background-color: transparent;
    color: #8fc99a;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 14px;
    padding: 8px 12px;
}

.terminal-toggle-btn {
    background-color: #14171c;
    color: #7d8794;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    min-height: 32px;
}
.terminal-toggle-btn:hover {
    background-color: #1b1f26;
    color: #2ee65f;
}
.terminal-toggle-btn.active {
    background-color: #0a0c0f;
    color: #2ee65f;
    border: 1px solid #15a838;
}

/* ===== Banner for watcher events ===== */

.watcher-banner {
    background-color: #0a0c0f;
    border-left: 4px solid #f0a500;
    border-radius: 6px;
    padding: 14px 18px;
    margin: 8px 16px;
    color: #f0a500;
    font-size: 17px;
}

.working-row {
    background-color: rgba(46, 230, 95, 0.15);
    border-radius: 8px;
    padding: 10px 22px;
}
.working-label {
    color: #2ee65f;
    font-size: 18px;
    font-style: italic;
    font-weight: bold;
    letter-spacing: 0.5px;
}
.working-spinner {
    color: #2ee65f;
    min-width: 24px;
    min-height: 24px;
}

/* ===== Proposed-command card (advisory flow) ===== */

.cmd-card {
    background-color: #14171c;
    border: 1px solid #262b33;
    border-left: 4px solid #15a838;
    border-radius: 8px;
    padding: 14px 16px;
    margin: 8px 0;
}
.cmd-card-header {
    margin-bottom: 8px;
}
.cmd-card-title {
    color: #2ee65f;
    font-weight: bold;
    font-size: 15px;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.5px;
}
.risk-badge {
    border-radius: 4px;
    padding: 2px 12px;
    font-size: 13px;
    font-weight: bold;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.5px;
}
.risk-badge.low    { background-color: #2ecc71; color: #0d0f12; }
.risk-badge.medium { background-color: #f0a500; color: #0d0f12; }
.risk-badge.high   { background-color: #e5484d; color: #ffffff; }
.cmd-text {
    background-color: #0a0c0f;
    color: #2ee65f;
    font-family: 'JetBrains Mono', monospace;
    font-size: 18px;
    padding: 12px 14px;
    border-radius: 6px;
    border: 1px solid #262b33;
    margin-bottom: 8px;
}
.cmd-explain {
    color: #aeb6c2;
    font-size: 16px;
    margin-bottom: 12px;
}
.card-warn {
    background-color: rgba(229, 72, 77, 0.10);
    border: 1px solid rgba(229, 72, 77, 0.45);
    border-radius: 8px;
    color: #f3b0b2;
    font-size: 15px;
    padding: 10px 14px;
    margin: 6px 0;
}
.cmd-run-btn {
    background: linear-gradient(135deg, #15a838, #2ee65f);
    color: #ffffff;
    border-radius: 6px;
    padding: 10px 22px;
    font-weight: bold;
    font-size: 16px;
}
.cmd-run-btn:hover { background: linear-gradient(135deg, #2ee65f, #15a838); }
.cmd-run-btn:disabled { background: #262b33; color: #5a626d; }
.cmd-copy-btn {
    background-color: #1b1f26;
    color: #d6dbe2;
    border-radius: 6px;
    padding: 10px 18px;
    font-size: 16px;
    border: 1px solid #262b33;
}
.cmd-copy-btn:hover { background-color: #1f2530; border-color: #15a838; }

/* ===== libadwaita rows / settings / dialogs =====
   Force the Kali surfaces on the built-in widgets so Settings and
   dialogs match the rest of the app instead of showing stock Adwaita
   grey. */

preferencespage, preferencesgroup {
    background-color: #0d0f12;
}
row, .row, list.boxed-list > row {
    background-color: #14171c;
    color: #d6dbe2;
}
list.boxed-list {
    background-color: #14171c;
    border: 1px solid #262b33;
    border-radius: 8px;
}
row:hover { background-color: #1b1f26; }
row > box { background-color: transparent; }

/* Switches: blue when on, dark track when off */
switch {
    background-color: #262b33;
    border-radius: 14px;
}
switch:checked {
    background-color: #15a838;
}
switch > slider {
    background-color: #d6dbe2;
    border-radius: 50%;
}

/* SpinRow / spinbuttons */
spinbutton, spinbutton entry {
    background-color: #1b1f26;
    color: #d6dbe2;
    border-radius: 6px;
}
spinbutton button {
    background-color: #1b1f26;
    color: #2ee65f;
}
spinbutton button:hover { background-color: #262b33; }

/* ComboRow dropdown */
comborow, dropdown {
    background-color: #1b1f26;
    color: #d6dbe2;
}
dropdown > button {
    background-color: #1b1f26;
    color: #d6dbe2;
    border-radius: 6px;
}
popover > contents, popover > arrow {
    background-color: #14171c;
    color: #d6dbe2;
    border: 1px solid #262b33;
}
popover row:selected, dropdown listview > row:selected {
    background-color: #15a838;
    color: #ffffff;
}

/* Dialogs (AlertDialog / PreferencesDialog) */
window.dialog, dialog, .messagedialog, .dialog-content {
    background-color: #14171c;
    color: #d6dbe2;
}
.messagedialog .response-area button {
    background-color: #1b1f26;
    color: #d6dbe2;
    border-radius: 6px;
    margin: 4px;
}
.messagedialog .response-area button.suggested-action {
    background: linear-gradient(135deg, #15a838, #2ee65f);
    color: #ffffff;
}
.messagedialog .response-area button.destructive-action {
    background-color: #e5484d;
    color: #ffffff;
}

/* Search entry in the sidebar */
.sidebar-search, searchentry, searchentry text {
    background-color: #1b1f26;
    color: #d6dbe2;
    border-radius: 6px;
    border: 1px solid #262b33;
}
searchentry:focus-within { border-color: #15a838; }

/* Menu button / popover menu */
menubutton > button, .menu-button {
    color: #d6dbe2;
}
.popover-menu, menu, .menu {
    background-color: #14171c;
    color: #d6dbe2;
}

/* Generic buttons inherit the dark surface unless given a role class */
button {
    background-color: #1b1f26;
    color: #d6dbe2;
    border: 1px solid #262b33;
    border-radius: 11px;
}
button:hover { background-color: #1f2530; border-color: #15a838; }
button.flat { background-color: transparent; border: none; }
button.flat:hover { background-color: #1b1f26; }
button.suggested-action {
    background: linear-gradient(135deg, #15a838, #2ee65f);
    color: #ffffff;
    border: none;
}

/* Dragon avatar tile in chat */
.avatar-dragon {
    border-radius: 8px;
    background-color: #000000;
    box-shadow: 0 0 10px rgba(255, 45, 58, 0.5), 0 0 4px rgba(46, 230, 95, 0.4);
}
.avatar-cross {
    border-radius: 8px;
    background-color: #0a0c0e;
    box-shadow: 0 0 8px rgba(46, 230, 95, 0.35);
}
/* let the penguin watermark show through the chat */
.chat-scroll,
.chat-scroll > viewport,
.chat-scroll viewport {
    background-color: transparent;
    background: transparent;
}
.chat-watermark { background: transparent; }

/* Links (e.g. 'Get an API key') in Kali blue */
link, button.link, *:link { color: #2ee65f; }

/* Voice: mic button + active recording state */
.mic-button {
    background-color: #1b1f26;
    color: #d6dbe2;
    border: 1px solid #262b33;
    border-radius: 11px;
}
.mic-button:hover { background-color: #1f2530; border-color: #15a838; }
.mic-recording {
    background: linear-gradient(135deg, #e5484d, #ff5c61);
    color: #ffffff;
    border: 1px solid #ff5c61;
    box-shadow: 0 0 10px rgba(229, 72, 77, 0.6);
}
.mic-recording:hover {
    background: linear-gradient(135deg, #ff5c61, #ff6f73);
    border-color: #ff6f73;
}

/* Per-message read-aloud button - sits under the reply, clearly tappable */
.msg-footer { margin-top: 6px; }
.msg-speak-btn {
    padding: 4px 13px;
    color: #9aa3ad;
    background-color: #14181d;
    border: 1px solid #20262d;
    border-radius: 11px;
    font-size: 12px;
    font-weight: 500;
}
.msg-speak-btn:hover {
    background-color: #1b2128;
    color: #2ee65f;
    border-color: #15a838;
}
.msg-speak-btn.speaking {
    color: #2ee65f;
    border-color: #15a838;
    background-color: rgba(46, 230, 95, 0.12);
}

/* Composer action icons (attach, audit, scan, mic) - subtle + rounded */
.icon-button {
    background-color: #14181d;
    border: 1px solid #20262d;
    border-radius: 11px;
    color: #9aa3ad;
    padding: 7px;
}
.icon-button:hover {
    background-color: #1b2128;
    color: #2ee65f;
    border-color: #15a838;
}
.icon-button.toggled {
    color: #2ee65f;
    border-color: #15a838;
    background-color: rgba(46, 230, 95, 0.12);
}
/* Send button - blends into the background; only the silver dragon pops.
   Glows softly while working; still acts as Stop when pressed. */
.send-button {
    background-color: #0d0f12;
    border: 1px solid #1c2229;
    border-radius: 16px;
    min-width: 62px;
    min-height: 62px;
    padding: 8px;
    box-shadow: none;
}
.send-button:hover {
    background-color: #141821;
    border-color: #2a323b;
}
.send-button:active {
    background-color: #0a0c0f;
    box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.5);
}
.send-button.working {
    animation: sendglow 1.3s ease-in-out infinite;
}
@keyframes sendglow {
    0%   { box-shadow: 0 0 6px rgba(200, 208, 216, 0.25); border-color: #2a323b; }
    50%  { box-shadow: 0 0 20px rgba(224, 232, 240, 0.75); border-color: #c8d0d8; }
    100% { box-shadow: 0 0 6px rgba(200, 208, 216, 0.25); border-color: #2a323b; }
}
/* Header buttons (sidebar toggle, new chat) - blend into the header, with a
   quiet dragon-green accent only on hover so they don't draw the eye. */
.header-icon-button {
    background-color: transparent;
    background-image: none;
    border: none;
    box-shadow: none;
    color: #5e666f;
    border-radius: 10px;
    padding: 6px;
}
.header-icon-button:hover {
    background-color: rgba(46, 230, 95, 0.10);
    color: #2ee65f;
    box-shadow: none;
}
.header-icon-button:active {
    background-color: rgba(46, 230, 95, 0.16);
}
/* Model / provider switcher in the composer */
.model-switch-btn {
    background-color: #14181d;
    border: 1px solid #20262d;
    border-radius: 10px;
    color: #9aa3ad;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 600;
}
.model-switch-btn:hover {
    background-color: #1b2128;
    color: #2ee65f;
    border-color: #15a838;
}
.model-group-header {
    color: #ff3a47;
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 1px;
    margin-top: 10px;
    margin-bottom: 4px;
    padding-left: 4px;
}
.model-pick-row {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    color: #e8ebef;
    padding: 11px 14px;
    font-size: 17px;
    font-weight: 500;
}
.model-pick-row:hover {
    background-color: rgba(46, 230, 95, 0.10);
    color: #2ee65f;
}
.model-pick-active {
    background-color: rgba(46, 230, 95, 0.16);
    color: #2ee65f;
    font-weight: 700;
}

/* =====================================================================
   POLISH LAYER  --  product-grade finish.  Appended last so it refines
   the base theme above (later rules win): real depth, smooth state
   transitions, tactile buttons, premium surfaces.  Tuned to read like a
   shipped commercial tool, not a script with a window.
   ===================================================================== */

/* Motion: subtle, fast, everywhere it counts. */
button, .quick-chip, .chat-row, entry, .mic-button, switch, row,
.cmd-run-btn, .cmd-copy-btn, .terminal-toggle-btn {
    transition: background-color 130ms ease,
                border-color 130ms ease,
                box-shadow 160ms ease,
                color 130ms ease;
}

/* Header: lift it off the content with a hairline + soft shadow. */
headerbar {
    box-shadow: 0 1px 0 rgba(255,255,255,0.02),
                0 2px 8px rgba(0,0,0,0.35);
}

/* ---- Buttons: depth, gradient sheen, a real pressed state ---- */
button {
    background-image: linear-gradient(180deg,
                      rgba(255,255,255,0.03), rgba(255,255,255,0.0));
    box-shadow: 0 1px 2px rgba(0,0,0,0.25),
                inset 0 1px 0 rgba(255,255,255,0.03);
    padding: 8px 16px;
    font-weight: 500;
}
button:hover {
    box-shadow: 0 2px 6px rgba(0,0,0,0.30),
                inset 0 1px 0 rgba(255,255,255,0.05);
}
button:active {
    background-image: none;
    box-shadow: inset 0 2px 5px rgba(0,0,0,0.40);
}
button:disabled {
    box-shadow: none;
    background-image: none;
    opacity: 0.55;
}
button:focus-visible {
    outline: 2px solid rgba(46, 230, 95,0.65);
    outline-offset: 1px;
}
button.suggested-action {
    box-shadow: 0 2px 8px rgba(46, 230, 95,0.35),
                inset 0 1px 0 rgba(255,255,255,0.15);
}
button.suggested-action:hover {
    box-shadow: 0 3px 14px rgba(46, 230, 95,0.45),
                inset 0 1px 0 rgba(255,255,255,0.20);
}

/* ---- Primary action buttons (Run / Apply) ---- */
.cmd-run-btn {
    box-shadow: 0 2px 10px rgba(46, 230, 95,0.40),
                inset 0 1px 0 rgba(255,255,255,0.18);
    padding: 11px 26px;
    letter-spacing: 0.2px;
}
.cmd-run-btn:hover {
    box-shadow: 0 4px 16px rgba(46, 230, 95,0.50),
                inset 0 1px 0 rgba(255,255,255,0.22);
}
.cmd-run-btn:active {
    box-shadow: inset 0 2px 6px rgba(0,0,0,0.35);
}
.cmd-copy-btn { padding: 11px 20px; }

/* ---- Command / edit cards: lift them onto a surface ---- */
.cmd-card {
    background-image: linear-gradient(180deg, #161a20, #121519);
    box-shadow: 0 4px 18px rgba(0,0,0,0.40),
                inset 0 1px 0 rgba(255,255,255,0.03);
    border: 1px solid #2b313b;
    padding: 16px 18px;
}
.cmd-card-title { letter-spacing: 0.4px; }
.risk-badge {
    box-shadow: 0 1px 3px rgba(0,0,0,0.30);
    letter-spacing: 0.3px;
    font-weight: 700;
}

/* ---- Composer entry: inset depth + a focus glow ---- */
entry {
    background-image: linear-gradient(180deg,
                      rgba(0,0,0,0.18), rgba(0,0,0,0.0));
    box-shadow: inset 0 1px 3px rgba(0,0,0,0.35);
}
entry:focus-within {
    box-shadow: inset 0 1px 3px rgba(0,0,0,0.35),
                0 0 0 3px rgba(46, 230, 95,0.22);
}

/* ---- Message bubbles: quiet depth so they sit above the canvas ---- */
.msg-user {
    box-shadow: 0 2px 10px rgba(46, 230, 95,0.18);
}
.msg-assistant {
    box-shadow: 0 2px 10px rgba(0,0,0,0.28);
}

/* ---- Sidebar chat rows: fire accent handled in the base block above ---- */
.chat-row {
    border-left: 3px solid transparent;
}

/* ---- Quick chips: pill polish ---- */
.quick-chip {
    background-image: linear-gradient(180deg,
                      rgba(255,255,255,0.03), rgba(255,255,255,0.0));
    box-shadow: 0 1px 2px rgba(0,0,0,0.20);
    padding: 7px 15px;
}
.quick-chip:hover {
    box-shadow: 0 2px 8px rgba(46, 230, 95,0.25);
}

/* ---- Mic recording: gentle pulse-ready glow already set; deepen it ---- */
.mic-recording {
    box-shadow: 0 0 0 3px rgba(229,72,77,0.25),
                0 0 14px rgba(229,72,77,0.55);
}

/* ---- Working row: a soft active surface ---- */
.working-row {
    background-image: linear-gradient(90deg,
                      rgba(46, 230, 95,0.10), rgba(46, 230, 95,0.0));
    box-shadow: inset 0 0 0 1px rgba(46, 230, 95,0.15);
}

/* ---- Slim, themed scrollbars ---- */
scrollbar { background-color: transparent; border: none; }
scrollbar slider {
    background-color: #2b313b;
    border-radius: 10px;
    min-width: 7px;
    min-height: 7px;
}
scrollbar slider:hover { background-color: #3a4250; }
scrollbar slider:active { background-color: #2ee65f; }

/* ---- Boxed settings lists: a touch of depth ---- */
list.boxed-list {
    box-shadow: 0 2px 12px rgba(0,0,0,0.30);
}

/* ---- Auto-run note: when Kali runs a command without a card ---- */
.autorun-note {
    color: #6f7a88;
    font-size: 13px;
    font-family: 'JetBrains Mono', monospace;
    margin: 2px 0 6px 0;
}
"""


# ═════════════════════════════════════════════════════════════════════
# MARKDOWN-LITE RENDERING
# ═════════════════════════════════════════════════════════════════════

CODE_FENCE_RE  = re.compile(r"```([a-zA-Z0-9_+-]*)\n?(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
BOLD_RE        = re.compile(r"\*\*([^*\n]+)\*\*")
ITALIC_RE      = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")


def _evidence_report(engagement=None):
    """Evidence summary + integrity + a readable markdown ledger for review."""
    led = get_ledger()
    if led is None:
        return {"error": "evidence ledger unavailable"}
    return {
        "engagement": engagement or led.engagement,
        "summary": led.summary(engagement),
        "integrity": led.verify(engagement),
        "report_markdown": led.export_markdown(engagement),
    }


def _evidence_set_engagement(name):
    """Switch the active engagement that future commands are recorded under."""
    led = get_ledger()
    if led is None:
        return {"error": "evidence ledger unavailable"}
    if not (name or "").strip():
        return {"engagement": led.engagement, "note": "no name given; unchanged"}
    new = led.set_engagement(name)
    return {"engagement": new, "steps": led.summary()["steps"]}


def text_to_pango(text: str) -> str:
    safe = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))
    safe = BOLD_RE.sub(r"<b>\1</b>", safe)
    safe = ITALIC_RE.sub(r"<i>\1</i>", safe)
    safe = INLINE_CODE_RE.sub(
        r'<span font_family="JetBrains Mono" '
        r'background="#0a0c0f" foreground="#d6ffdf"> \1 </span>',
        safe)
    return safe


def split_message_into_blocks(text: str) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    last = 0
    for m in CODE_FENCE_RE.finditer(text):
        if m.start() > last:
            pre = text[last:m.start()].strip("\n")
            if pre:
                blocks.extend(_split_text_and_images(pre))
        lang = m.group(1) or "text"
        code = m.group(2).rstrip("\n")
        blocks.append({"kind": "code", "lang": lang, "content": code})
        last = m.end()
    tail = text[last:].strip("\n")
    if tail:
        blocks.extend(_split_text_and_images(tail))
    if not blocks:
        blocks.append({"kind": "text", "content": text})
    return blocks


# Markdown image syntax: ![alt](url) — optionally with a "title" after the URL.
# This is how the model asks Kali to SHOW a picture inline (a web image-search
# result, an OSINT profile photo, a screenshot it just took, …): it simply
# writes the image in markdown and the renderer turns it into a real picture.
IMAGE_MD_RE = re.compile(
    r'!\[([^\]]*)\]\(\s*(<?)(https?://[^)\s]+?|file://[^)\s]+?|/[^)\s]+?)\2'
    r'(?:\s+"[^"]*")?\s*\)')


def _split_text_and_images(text: str) -> List[Dict[str, str]]:
    """Split a plain-text segment into alternating text and image blocks, so an
    inline ![alt](url) becomes its own rendered picture while the prose around
    it stays prose."""
    out: List[Dict[str, str]] = []
    last = 0
    for m in IMAGE_MD_RE.finditer(text):
        if m.start() > last:
            pre = text[last:m.start()].strip("\n")
            if pre:
                out.append({"kind": "text", "content": pre})
        out.append({"kind": "image",
                    "url": m.group(3).strip(),
                    "alt": (m.group(1) or "").strip()})
        last = m.end()
    tail = text[last:].strip("\n") if last else text
    if tail.strip():
        out.append({"kind": "text", "content": tail})
    elif not out:
        out.append({"kind": "text", "content": text})
    return out


# ═════════════════════════════════════════════════════════════════════
# WIDGETS
# ═════════════════════════════════════════════════════════════════════

class CodeBlockWidget(Gtk.Box):
    def __init__(self, code: str, lang: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("code-block")
        self.code = code

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.add_css_class("code-block-header")
        lbl = Gtk.Label(label=lang or "code", xalign=0.0, hexpand=True)
        header.append(lbl)
        copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_btn.add_css_class("icon-button")
        copy_btn.set_tooltip_text("Copy")
        copy_btn.connect("clicked", self._on_copy)
        header.append(copy_btn)
        self.append(header)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        sw.set_hexpand(True)
        # Don't let a long code line force the whole window wider than the
        # screen — the scroller absorbs the overflow instead.
        sw.set_propagate_natural_width(False)
        sw.set_min_content_width(0)
        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_cursor_visible(False)
        tv.set_monospace(True)
        tv.set_wrap_mode(Gtk.WrapMode.NONE)
        tv.get_buffer().set_text(code)
        sw.set_child(tv)
        self.append(sw)

    def _on_copy(self, _btn):
        text = self.code
        try:
            value = GObject.Value()
            value.init(GObject.TYPE_STRING)
            value.set_string(text)
            provider = Gdk.ContentProvider.new_for_value(value)
            display = self.get_display() or Gdk.Display.get_default()
            display.get_clipboard().set_content(provider)
            # Also set primary clipboard for middle-click paste
            try:
                display.get_primary_clipboard().set_content(provider)
            except Exception:
                pass
            # Visual feedback
            self._show_copied()
        except Exception as e:
            log(f"clipboard copy failed: {e}")

    def _show_copied(self):
        """Brief 'Copied!' flash on the button."""
        try:
            header = self.get_first_child()
            if header is None:
                return
            btn = header.get_last_child()
            if btn is None:
                return
            btn.set_icon_name("emblem-ok-symbolic")
            GLib.timeout_add(900,
                lambda: (btn.set_icon_name("edit-copy-symbolic") or False))
        except Exception:
            pass


# Whether to fetch & render remote images inline.  Default on; the app sets it
# from settings at startup.  Off → image markdown is shown as a tappable link
# instead, for operators who don't want the chat reaching out to image hosts.
_RENDER_IMAGES = True


class ImageWidget(Gtk.Box):
    """An image rendered inline in chat from a URL (http/https/file/local path).

    The model shows a picture by emitting markdown — ![alt](url) — and this
    widget turns it into a real image: a web image-search result, an OSINT
    profile photo, a screenshot Kali just took.  The download and decode happen
    OFF the UI thread (chat never blocks), the bytes are size-capped, and the
    picture is scaled down to fit the bubble.  Any failure degrades to a small
    caption with the link, so a dead URL can never break the conversation."""

    _MAX_BYTES = 12_000_000          # don't pull more than ~12 MB for one image
    _MAX_W = 480                     # display cap (px) — scaled down, never up
    _MAX_H = 480
    _UA = "Mozilla/5.0 (X11; Linux x86_64) Kali/3.2 image-fetch"

    def __init__(self, url: str, alt: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.add_css_class("image-block")
        self.url = (url or "").strip()
        self.alt = (alt or "").strip()
        self._caption = Gtk.Label(label=(self.alt or "loading image…"),
                                  xalign=0.0)
        self._caption.add_css_class("image-caption")
        self._caption.set_wrap(True)
        self._caption.set_max_width_chars(48)
        self.append(self._caption)
        try:
            threading.Thread(target=self._load, daemon=True).start()
        except Exception as e:
            self._fail(str(e))

    # — worker thread —
    def _load(self):
        try:
            data = self._fetch_bytes()
            tex = self._decode(data)
        except Exception as e:
            GLib.idle_add(lambda m=str(e): self._fail(m) or False)
            return
        GLib.idle_add(lambda: self._show(tex) or False)

    def _fetch_bytes(self) -> bytes:
        u = self.url
        if u.startswith("file://"):
            u = u[7:]
        if u.startswith("/"):  # local file path
            with open(u, "rb") as f:
                return f.read(self._MAX_BYTES)
        if not (u.startswith("http://") or u.startswith("https://")):
            raise ValueError("unsupported image URL scheme")
        req = urllib.request.Request(u, headers={
            "User-Agent": self._UA,
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read(self._MAX_BYTES)

    def _decode(self, data: bytes):
        if not data:
            raise ValueError("empty image")
        loader = GdkPixbuf.PixbufLoader()
        try:
            loader.write(data)
        except TypeError:
            loader.write_bytes(GLib.Bytes.new(data))
        loader.close()
        pb = loader.get_pixbuf()
        if pb is None:
            raise ValueError("could not decode image")
        w, h = pb.get_width(), pb.get_height()
        if w <= 0 or h <= 0:
            raise ValueError("bad image dimensions")
        scale = min(self._MAX_W / w, self._MAX_H / h, 1.0)
        if scale < 1.0:
            pb = pb.scale_simple(max(1, int(w * scale)), max(1, int(h * scale)),
                                 GdkPixbuf.InterpType.BILINEAR)
        return Gdk.Texture.new_for_pixbuf(pb)

    # — UI thread —
    def _show(self, tex):
        try:
            pic = Gtk.Picture.new_for_paintable(tex)
            pic.set_can_shrink(True)
            try:
                pic.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
            except Exception:
                pass
            pic.add_css_class("chat-image")
            pic.set_halign(Gtk.Align.START)
            tw, th = tex.get_width(), tex.get_height()
            # Never let an image be wider than the viewport minus the avatar
            # column + margins — otherwise set_size_request makes that width a
            # hard MINIMUM and forces the whole window past the phone screen.
            cap_w = max(160, _VIEWPORT_WIDTH - 120)
            if tw > cap_w and tw > 0:
                th = max(1, int(th * cap_w / tw))
                tw = cap_w
            pic.set_size_request(tw, th)
            if self.alt:
                pic.set_tooltip_text(self.alt)
            try:
                self.remove(self._caption)
            except Exception:
                pass
            self.prepend(pic)
            if self.alt:
                cap = Gtk.Label(label=self.alt, xalign=0.0)
                cap.add_css_class("image-caption")
                cap.set_wrap(True)
                cap.set_max_width_chars(48)
                self.append(cap)
        except Exception as e:
            self._fail(str(e))
        return False

    def _fail(self, msg: str):
        try:
            shown = self.alt or self.url
            self._caption.set_markup(
                f"🖼 <i>couldn't load image</i> — "
                f"<a href=\"{GLib.markup_escape_text(self.url)}\">"
                f"{GLib.markup_escape_text(shown[:80])}</a>")
        except Exception:
            try:
                self._caption.set_text(f"🖼 couldn't load image: {self.url}")
            except Exception:
                pass
        log(f"image load failed ({self.url}): {msg}")
        return False


class ProposedCommandWidget(Gtk.Box):
    """A command Kali wants to run, shown as an advisory card.

    Nothing executes until the operator clicks Run.  on_run is called
    with (command, explanation) when they do.
    """
    def __init__(self, command: str, explanation: str = "",
                 risk: str = "medium",
                 on_run: Optional[Callable[[str, str, Any], None]] = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("cmd-card")
        self.command = command
        self.explanation = explanation
        self._on_run = on_run

        # Header: title + risk badge
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("cmd-card-header")
        title = Gtk.Label(label="⌘  PROPOSED COMMAND", xalign=0.0)
        title.add_css_class("cmd-card-title")
        title.set_hexpand(True)
        header.append(title)
        risk = (risk or "medium").lower()
        if risk not in ("low", "medium", "high"):
            risk = "medium"
        badge = Gtk.Label(label=f"{risk} risk")
        badge.add_css_class("risk-badge")
        badge.add_css_class(risk)
        badge.set_valign(Gtk.Align.CENTER)
        header.append(badge)
        self.append(header)

        # The command itself
        cmd_lbl = Gtk.Label(label=command, xalign=0.0)
        cmd_lbl.add_css_class("cmd-text")
        cmd_lbl.set_wrap(True)
        cmd_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        cmd_lbl.set_selectable(True)
        self.append(cmd_lbl)

        # Explanation
        if explanation:
            exp = _make_wrap_label()
            exp.add_css_class("cmd-explain")
            try:
                exp.set_markup(text_to_pango(explanation))
            except Exception:
                exp.set_text(explanation)
            self.append(exp)

        # Buttons
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.run_btn = Gtk.Button(label="Run")
        self.run_btn.add_css_class("cmd-run-btn")
        self.run_btn.connect("clicked", self._on_run_clicked)
        btn_row.append(self.run_btn)

        copy_btn = Gtk.Button(label="Copy")
        copy_btn.add_css_class("cmd-copy-btn")
        copy_btn.connect("clicked", self._on_copy_clicked)
        btn_row.append(copy_btn)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        btn_row.append(spacer)
        self.append(btn_row)

    def _on_run_clicked(self, _btn):
        if self._on_run is None:
            return
        # One-shot visual: prevent a double-fire while the turn is in
        # flight.  Reset by the host if it couldn't start (busy).
        self.run_btn.set_sensitive(False)
        self.run_btn.set_label("Running…")
        self._on_run(self.command, self.explanation, self)

    def reset_run_button(self):
        self.run_btn.set_sensitive(True)
        self.run_btn.set_label("Run")

    def _on_copy_clicked(self, _btn):
        try:
            value = GObject.Value()
            value.init(GObject.TYPE_STRING)
            value.set_string(self.command)
            provider = Gdk.ContentProvider.new_for_value(value)
            display = self.get_display() or Gdk.Display.get_default()
            display.get_clipboard().set_content(provider)
        except Exception as e:
            log(f"cmd copy failed: {e}")


class ProposedEditWidget(Gtk.Box):
    """A file edit Kali wants to make, shown as an advisory card with a
    compact diff.  Nothing is written until the operator clicks Apply.

    Mirrors ProposedCommandWidget's flow exactly — same one-shot button
    discipline, same host callback shape — so it rides the existing
    confirm-then-execute gate rather than a new bypass.  on_apply is
    called with (path, content, self) when the operator approves.
    """
    def __init__(self, path: str, content: str,
                 diff_lines: Optional[List[str]] = None,
                 added: int = 0, removed: int = 0,
                 is_new: bool = False, truncated: bool = False,
                 explanation: str = "",
                 on_apply: Optional[Callable[[str, str, Any], None]] = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("cmd-card")
        self.path = path
        self.content = content
        self._on_apply = on_apply

        # Header: title + a +adds/-removes badge
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("cmd-card-header")
        verb = "PROPOSED NEW FILE" if is_new else "PROPOSED EDIT"
        title = Gtk.Label(label=f"✎  {verb}", xalign=0.0)
        title.add_css_class("cmd-card-title")
        title.set_hexpand(True)
        header.append(title)
        badge = Gtk.Label(label=f"+{added} −{removed}")
        badge.add_css_class("risk-badge")
        # Reuse the risk colour classes: a big change reads as higher risk.
        badge.add_css_class("high" if (added + removed) > 60
                            else "medium" if (added + removed) > 8
                            else "low")
        badge.set_valign(Gtk.Align.CENTER)
        header.append(badge)
        self.append(header)

        # Target path
        path_lbl = Gtk.Label(label=path, xalign=0.0)
        path_lbl.add_css_class("cmd-text")
        path_lbl.set_wrap(True)
        path_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        path_lbl.set_selectable(True)
        self.append(path_lbl)

        # Compact diff body in a monospace, scrollable view
        if diff_lines:
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            sw.set_hexpand(True)
            tv = Gtk.TextView()
            tv.set_editable(False)
            tv.set_cursor_visible(False)
            tv.set_monospace(True)
            tv.set_wrap_mode(Gtk.WrapMode.NONE)
            buf = tv.get_buffer()
            # colour-tag added / removed lines so the diff reads at a glance
            t_add = buf.create_tag("add", foreground="#2ecc71")
            t_del = buf.create_tag("del", foreground="#e5484d")
            t_hdr = buf.create_tag("hdr", foreground="#6fae84")
            for i, line in enumerate(diff_lines):
                start = buf.get_end_iter()
                buf.insert(start, (line + "\n"))
                # re-grab iters for the line we just inserted
                end = buf.get_end_iter()
                ls = buf.get_iter_at_line(i)
                if isinstance(ls, tuple):           # GTK4 returns (ok, iter)
                    ls = ls[1]
                if line.startswith("+") and not line.startswith("+++"):
                    buf.apply_tag(t_add, ls, end)
                elif line.startswith("-") and not line.startswith("---"):
                    buf.apply_tag(t_del, ls, end)
                elif line.startswith("@@") or line.startswith(("+++", "---")):
                    buf.apply_tag(t_hdr, ls, end)
            sw.set_child(tv)
            self.append(sw)
        if truncated:
            more = Gtk.Label(label="…diff truncated — full content applies on Apply",
                             xalign=0.0)
            more.add_css_class("cmd-explain")
            self.append(more)

        if explanation:
            exp = _make_wrap_label()
            exp.add_css_class("cmd-explain")
            try:
                exp.set_markup(text_to_pango(explanation))
            except Exception:
                exp.set_text(explanation)
            self.append(exp)

        # Buttons
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.apply_btn = Gtk.Button(label="Apply")
        self.apply_btn.add_css_class("cmd-run-btn")
        self.apply_btn.connect("clicked", self._on_apply_clicked)
        btn_row.append(self.apply_btn)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        btn_row.append(spacer)
        self.append(btn_row)

    def _on_apply_clicked(self, _btn):
        if self._on_apply is None:
            return
        self.apply_btn.set_sensitive(False)
        self.apply_btn.set_label("Applying…")
        self._on_apply(self.path, self.content, self)

    def reset_apply_button(self):
        self.apply_btn.set_sensitive(True)
        self.apply_btn.set_label("Apply")


def _find_dragon_svg() -> Optional[str]:
    """Locate the dragon emblem SVG at runtime.  Checks the install dir,
    the icon theme dir, and the directory this script lives in (dev/run
    in place).  Returns None if not found so the avatar falls back to a
    letter."""
    candidates = [
        os.path.expanduser("~/.local/share/kali/kali-dragon.svg"),
        os.path.expanduser(
            "~/.local/share/icons/hicolor/scalable/apps/kali-dragon.svg"),
        os.path.expanduser(
            "~/.local/share/icons/hicolor/scalable/apps/"
            "org.thepriest.kali.svg"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "kali-dragon.svg"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


# Resolved once at import; None if the emblem isn't on disk.
_DRAGON_SVG_PATH = _find_dragon_svg()


def _find_avatar_png() -> Optional[str]:
    """Locate the dragon PNG used as Kali's chat avatar (clean, no ring)."""
    candidates = [
        os.path.expanduser("~/.local/share/kali/kali-avatar.png"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "kali-avatar.png"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


_AVATAR_PNG_PATH = _find_avatar_png()


def _find_watermark_svg() -> Optional[str]:
    """Locate the dragon watermark for the chat background (PNG preferred,
    then SVG).  Falls back to the emblem SVG, then None (no watermark)."""
    candidates = [
        os.path.expanduser("~/.local/share/kali/kali-watermark.png"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "kali-watermark.png"),
        os.path.expanduser("~/.local/share/kali/kali-watermark.svg"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "kali-watermark.svg"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return _DRAGON_SVG_PATH


_WATERMARK_SVG_PATH = _find_watermark_svg()


def _find_cross_svg() -> Optional[str]:
    """Locate the operator's cross emblem (shown as the user avatar)."""
    candidates = [
        os.path.expanduser("~/.local/share/kali/kali-cross.svg"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "kali-cross.svg"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


_CROSS_SVG_PATH = _find_cross_svg()


def _svg_texture(path: str, px: int):
    """Rasterise an SVG file to a px-by-px Gdk.Texture using the pixbuf SVG
    loader (CPU / cairo).  Returns None on any failure.

    Why this exists: handing GTK a live SVG paintable (Gtk.Image.new_from_file
    on an .svg) lets the SVG's own structure become a tree of Gsk render nodes.
    A complex emblem — many hundreds of fill paths behind a feGaussianBlur —
    forces the GL renderer to allocate an offscreen blur surface for the whole
    group, which can exceed the GL texture-size limit and SEGFAULT the entire
    process at draw time.  Flattening to a fixed-size bitmap first means GTK
    only ever composites one small texture, so any emblem is safe and it still
    looks identical at avatar scale."""
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file_at_size(path, px, px)
        if pb is None:
            return None
        return Gdk.Texture.new_for_pixbuf(pb)
    except Exception as e:
        log(f"emblem rasterise failed: {e}")
        return None


def Avatar(kind: str = "user") -> Gtk.Widget:
    """Square avatar.  Kali shows the dragon emblem; the user shows an
    initial.  Falls back to a letter if the emblem SVG can't be loaded so
    the UI never breaks on a missing file.  Returns a plain Gtk.Image or
    Gtk.Label (both are valid box children) rather than a custom widget
    subclass — simpler and impossible to crash on vfunc mismatch."""
    size = _scaled(52, floor=28)
    if kind == "kali" and _AVATAR_PNG_PATH:
        # Preferred: the clean dragon PNG (no ring) as the chat avatar.
        try:
            img = Gtk.Image.new_from_file(_AVATAR_PNG_PATH)
            img.set_pixel_size(size)
            img.set_valign(Gtk.Align.START)
            img.add_css_class("avatar")
            img.add_css_class("avatar-dragon")
            img.set_size_request(size, size)
            return img
        except Exception as e:
            log(f"dragon PNG avatar load failed: {e}")
    if kind == "kali" and _DRAGON_SVG_PATH:
        try:
            # Rasterise to a bounded bitmap instead of a live SVG paintable —
            # see _svg_texture: a filtered, many-path emblem rendered live can
            # overflow the GL surface limit and crash the process.  2x the
            # display size keeps it crisp on HiDPI; capped so it stays bounded.
            px = min(max(size * 2, 96), 256)
            tex = _svg_texture(_DRAGON_SVG_PATH, px)
            if tex is not None:
                img = Gtk.Image.new_from_paintable(tex)
            else:
                img = Gtk.Image.new_from_file(_DRAGON_SVG_PATH)
            img.set_pixel_size(size)
            img.set_valign(Gtk.Align.START)
            img.add_css_class("avatar")
            img.add_css_class("avatar-dragon")
            img.set_size_request(size, size)
            return img
        except Exception as e:
            log(f"dragon avatar load failed: {e}")

    if kind == "user" and _CROSS_SVG_PATH:
        try:
            px = min(max(size * 2, 96), 256)
            tex = _svg_texture(_CROSS_SVG_PATH, px)
            if tex is not None:
                img = Gtk.Image.new_from_paintable(tex)
            else:
                img = Gtk.Image.new_from_file(_CROSS_SVG_PATH)
            img.set_pixel_size(size)
            img.set_valign(Gtk.Align.START)
            img.add_css_class("avatar")
            img.add_css_class("avatar-cross")
            img.set_size_request(size, size)
            return img
        except Exception as e:
            log(f"cross avatar load failed: {e}")

    lbl = Gtk.Label(label="L" if kind == "user" else "K")
    lbl.add_css_class("avatar")
    lbl.add_css_class("avatar-user" if kind == "user" else "avatar-kali")
    lbl.set_valign(Gtk.Align.START)
    lbl.set_size_request(size, size)
    return lbl


def _make_wrap_label() -> Gtk.Label:
    """Return a Gtk.Label that wraps AND reports a wrapped natural
    width, so it shrinks to fit the parent allocation on narrow
    screens instead of overflowing.

    GTK4 background: by default, a Label with set_wrap(True) STILL
    reports its single-line, unwrapped width as the natural width.
    That natural width is propagated up the widget tree, so the
    layout thinks the chat bubble "needs" the full line width.  On a
    Phosh phone the natural width is almost always wider than the
    physical screen, so the bubble overflows the right edge and the
    text gets clipped.

    Two settings fix this:
      - max-width-chars caps the natural width to N characters.  On
        the phone the actual allocation is narrower than that cap, so
        the label is given less width and wraps to it.  On the desktop
        the cap stops a single very long line from making the bubble
        span the entire monitor.
      - natural-wrap-mode = WORD (GTK 4.6+) makes the label's natural
        width the WRAPPED width (at word boundaries) instead of the
        single-line width.  This stops the natural width from being
        inflated by long lines.
    """
    lbl = Gtk.Label()
    lbl.set_wrap(True)
    lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lbl.set_xalign(0.0)
    lbl.set_hexpand(True)
    lbl.set_max_width_chars(_MAX_BUBBLE_CHARS)
    try:
        lbl.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
    except (AttributeError, TypeError):
        # Older libadwaita / GTK without NaturalWrapMode.  The label
        # will still wrap; it just won't shrink as aggressively.
        pass
    return lbl


class MessageWidget(Gtk.Box):
    """A single chat message."""

    def __init__(self, role: str, content: str = "",
                 meta: Optional[Dict[str, Any]] = None,
                 on_run_command: Optional[Callable[[str, str], None]] = None,
                 on_apply_edit: Optional[Callable[[str, str, Any], None]] = None,
                 on_speak: Optional[Callable[["MessageWidget"], None]] = None,
                 show_thoughts: bool = True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.role = role
        self.meta = meta or {}
        self._content = content or ""
        self._on_run_command = on_run_command
        self._on_apply_edit = on_apply_edit
        self._on_speak = on_speak
        self.speak_btn: Optional[Gtk.Button] = None
        self._speak_state = "idle"
        self._blocks_container: Optional[Gtk.Box] = None
        self._streaming_label: Optional[Gtk.Label] = None
        # Captured model reasoning ("thoughts"): from a reasoning_content
        # stream field and/or inline <think> blocks.  Shown in a collapsed
        # expander the operator can click open.
        self._thoughts: str = (self.meta or {}).get("thoughts", "") or ""
        self._thoughts_container: Optional[Gtk.Box] = None
        self._thoughts_label: Optional[Gtk.Label] = None
        self._show_thoughts: bool = show_thoughts
        self.add_css_class("msg-row")
        self._build_shell()
        if content and role != "tool":
            self.set_content(content)
        if self._thoughts:
            self._render_thoughts()

    def _build_shell(self):
        if self.role == "user":
            # User message: row fills the viewport, a left spacer pushes
            # the bubble to the right.  The OLD layout used
            # row.set_halign(Gtk.Align.END) which made the row claim
            # its NATURAL width (the unwrapped one-line size of the
            # message) and overflow the right edge of the screen on
            # narrow phones.  The hexpand-row + spacer pattern keeps
            # the row's own width equal to the viewport so the bubble
            # can't escape.
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.set_hexpand(True)

            spacer = Gtk.Box()
            spacer.set_hexpand(True)
            row.append(spacer)

            content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                  spacing=2)
            content_box.set_halign(Gtk.Align.END)
            content_box.set_hexpand(False)

            label = Gtk.Label(label="YOU", xalign=1.0)
            label.add_css_class("role-label")
            label.add_css_class("user")
            content_box.append(label)

            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            inner.add_css_class("msg-user")
            content_box.append(inner)

            row.append(content_box)
            row.append(Avatar("user"))
            self.append(row)
            self._blocks_container = inner

        elif self.role == "assistant":
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.set_hexpand(True)

            row.append(Avatar("kali"))

            content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                  spacing=2)
            content_box.set_hexpand(True)
            # Header: role label on the left, a per-message play/pause
            # button on the right (so each reply can be read, paused, and
            # replayed on its own).
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            label = Gtk.Label(label="KALI", xalign=0.0)
            label.add_css_class("role-label")
            label.add_css_class("kali")
            header.append(label)
            content_box.append(header)
            # Thoughts container sits between the header and the reply body.
            # It stays empty (and invisible) unless the model exposed its
            # reasoning, in which case _render_thoughts drops a collapsed
            # expander here.  Kept separate from the blocks container so
            # streaming/redraw of the reply never wipes it.
            self._thoughts_container = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=2)
            content_box.append(self._thoughts_container)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            inner.add_css_class("msg-assistant")
            content_box.append(inner)
            # Read-aloud control sits UNDERNEATH the message (left-aligned),
            # where it's easy to reach, rather than off on the far right.
            if self._on_speak is not None:
                footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                 spacing=6)
                footer.add_css_class("msg-footer")
                self.speak_btn = Gtk.Button(label=" Listen")
                self.speak_btn.set_icon_name("audio-volume-high-symbolic")
                self.speak_btn.add_css_class("msg-speak-btn")
                self.speak_btn.set_halign(Gtk.Align.START)
                self.speak_btn.set_tooltip_text("Read this message aloud")
                self.speak_btn.connect(
                    "clicked", lambda *_: self._on_speak(self))
                footer.append(self.speak_btn)
                content_box.append(footer)
            row.append(content_box)
            self.append(row)
            self._blocks_container = inner

        elif self.role == "tool":
            kind = self.meta.get("kind", "result")
            if kind == "result":
                # Hide tool results entirely — let the assistant summarize.
                self.set_visible(False)
                self._blocks_container = None
                return
            # Tool CALL: compact one-line indicator
            tool_name = self.meta.get("tool_name", "")
            if not tool_name:
                # Try to parse from legacy content like "⚙ tool: check_updates({...})"
                import re as _re
                m = _re.search(r'tool:\s*([a-zA-Z_]+)', self._content or "")
                tool_name = m.group(1) if m else "tool"
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row.add_css_class("msg-tool-indicator")
            row.set_halign(Gtk.Align.START)
            lbl = Gtk.Label(label=f"⚙  used {tool_name}", xalign=0.0)
            lbl.add_css_class("tool-indicator-label")
            row.append(lbl)
            self.append(row)
            self._blocks_container = None

        else:
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            inner.add_css_class("msg-system-notice")
            self.append(inner)
            self._blocks_container = inner

    def set_content(self, text: str):
        self._content = text
        if self.role == "tool" or self._blocks_container is None:
            return
        child = self._blocks_container.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._blocks_container.remove(child)
            child = nxt
        if self.role == "assistant":
            visible, think = extract_think_blocks(text)
            if think and think not in self._thoughts:
                self._thoughts = ((self._thoughts + "\n" + think).strip()
                                  if self._thoughts else think)
            if self._thoughts:
                self._render_thoughts()
            display_text = strip_tool_calls(visible)
        else:
            display_text = text
        # If the assistant message carries only tool calls, don't show a
        # placeholder when at least one is a proposal — the card speaks for
        # itself.  Only fall back to the placeholder for a bare execution
        # tag with no prose and no card.
        if not display_text and self.role == "assistant":
            has_propose = False
            try:
                has_propose = any(c.name == "propose"
                                  for c in parse_tool_calls(text))
            except Exception:
                pass
            display_text = "" if has_propose else "_(working…)_"

        blocks = split_message_into_blocks(display_text) if display_text else []
        for b in blocks:
            if b["kind"] == "code":
                self._blocks_container.append(
                    CodeBlockWidget(b["content"], b["lang"]))
            elif b["kind"] == "image":
                if _RENDER_IMAGES:
                    self._blocks_container.append(
                        ImageWidget(b.get("url", ""), b.get("alt", "")))
                else:
                    # Image rendering disabled — show a tappable link instead so
                    # nothing reaches out to the image host unasked.
                    lbl = _make_wrap_label()
                    alt = b.get("alt") or "image"
                    url = b.get("url", "")
                    try:
                        lbl.set_markup(
                            f"🖼 <a href=\"{GLib.markup_escape_text(url)}\">"
                            f"{GLib.markup_escape_text(alt)}</a>")
                    except Exception:
                        lbl.set_text(f"🖼 {url}")
                    self._blocks_container.append(lbl)
            else:
                lbl = _make_wrap_label()
                # NOT selectable — selectable labels swallow touch swipes
                # and break message-list scrolling.  Code blocks have a
                # copy button; prose can be copied via long-press menu.
                try:
                    lbl.set_markup(text_to_pango(b["content"]))
                except Exception:
                    lbl.set_text(b["content"])
                self._blocks_container.append(lbl)

        # Render any proposed-command cards from the raw text.  These are
        # advisory only — the model emits <tool name="propose"> and the
        # operator decides whether to run.  Parsed from the raw (un-
        # stripped) content so the cards survive a chat reload.
        if self.role == "assistant":
            try:
                for call in parse_tool_calls(text):
                    _rendered = False
                    if call.name == "propose":
                        cmd = (call.args.get("command")
                               or call.args.get("cmd") or "").strip()
                        if not cmd:
                            self._append_card_warn(
                                "Kali tried to propose a command but the call "
                                "had no command text — nothing to run.")
                            break
                        try:
                            self._blocks_container.append(ProposedCommandWidget(
                                cmd,
                                explanation=str(call.args.get("explanation", "")),
                                risk=str(call.args.get("risk", "medium")),
                                on_run=self._on_run_command))
                            _rendered = True
                        except Exception as e:
                            log(f"command card build failed: {e}")
                            self._append_card_warn(
                                f"Kali proposed a command but the card failed "
                                f"to render ({e}). Nothing was run.")
                            break
                    elif call.name in ("propose_edit", "write_file"):
                        # An edit proposal renders as a diff card.  It NEVER
                        # writes on its own — the operator's Apply click is
                        # the approval, and tool_write_file still enforces
                        # the parse-check + backup + immutable-guardrail net.
                        epath = (call.args.get("path") or "").strip()
                        econtent = call.args.get("content")
                        # The tag WAS emitted but the args are unusable — say
                        # WHY in the chat instead of silently drawing nothing
                        # and letting Kali claim a card that isn't there.
                        if "_raw" in call.args or not epath or econtent is None:
                            if "_raw" in call.args:
                                why = ("the file contents couldn't be parsed — "
                                       "most likely an unescaped \" or a stray "
                                       "control character in the JSON")
                            elif not epath:
                                why = "no target path was given"
                            else:
                                why = "no file content was given"
                            self._append_card_warn(
                                f"⚠ Kali tried to write a file but {why}, so no "
                                f"diff card could be drawn and nothing was "
                                f"written. Ask it to re-send the change.")
                            break
                        econtent = str(econtent)
                        try:
                            d = make_edit_diff(epath, econtent)
                        except Exception:
                            d = {"ok": False}
                        try:
                            self._blocks_container.append(ProposedEditWidget(
                                epath, econtent,
                                diff_lines=d.get("diff") if d.get("ok") else None,
                                added=d.get("added", 0),
                                removed=d.get("removed", 0),
                                is_new=d.get("is_new", False),
                                truncated=d.get("truncated", False),
                                explanation=str(call.args.get("explanation", "")),
                                on_apply=self._on_apply_edit))
                            _rendered = True
                        except Exception as e:
                            log(f"edit card build failed: {e}")
                            self._append_card_warn(
                                f"⚠ Kali proposed an edit to {epath} but the "
                                f"diff card failed to render ({e}). Nothing was "
                                f"written.")
                            break
                    # One command at a time: only the first proposal becomes a
                    # card.  Anything past it is ignored at render time.
                    if _rendered:
                        break
            except Exception as e:
                log(f"propose render failed: {e}")

    def _append_card_warn(self, msg: str):
        """Show a visible, in-chat diagnostic when a proposal/edit tag was
        emitted but no card could be drawn.  Without this the failure is
        silent and Kali looks like it's lying about a card that isn't there."""
        if self._blocks_container is None:
            return
        try:
            lbl = _make_wrap_label()
            lbl.set_text(msg)
            lbl.add_css_class("card-warn")
            self._blocks_container.append(lbl)
        except Exception as e:
            log(f"card-warn render failed: {e}")

    def set_speak_state(self, state: str):
        """state: 'idle' | 'speaking' | 'paused'."""
        self._speak_state = state
        if not self.speak_btn:
            return
        if state == "speaking":
            self.speak_btn.set_icon_name("media-playback-pause-symbolic")
            self.speak_btn.set_tooltip_text("Pause")
            self.speak_btn.add_css_class("speaking")
        elif state == "paused":
            self.speak_btn.set_icon_name("media-playback-start-symbolic")
            self.speak_btn.set_tooltip_text("Resume")
            self.speak_btn.add_css_class("speaking")
        else:  # idle
            self.speak_btn.set_icon_name("audio-volume-high-symbolic")
            self.speak_btn.set_tooltip_text("Read this message aloud")
            self.speak_btn.remove_css_class("speaking")

    def start_streaming(self):
        child = self._blocks_container.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._blocks_container.remove(child)
            child = nxt
        self._streaming_label = _make_wrap_label()
        # NOT selectable — see comment in set_content
        self._streaming_label.set_text("")
        self._blocks_container.append(self._streaming_label)
        self._content = ""

    def append_streaming(self, token: str):
        if self._streaming_label is None:
            self.start_streaming()
        self._content += token
        # Hide both tool XML and any inline <think> reasoning from the live
        # reply.  The reasoning (if any) gets captured at finish_streaming /
        # set_content and shown in the collapsible thoughts panel.
        display = strip_tool_calls(strip_think_blocks(self._content))
        self._streaming_label.set_text(display)

    def finish_streaming(self) -> str:
        final = self._content
        self._streaming_label = None
        self.set_content(final)
        return final

    # ── thoughts (model reasoning) ─────────────────────────────────
    def append_thought(self, token: str):
        """Accumulate a reasoning token (from a reasoning_content stream)
        and reveal/refresh the collapsed thoughts expander live."""
        if not token:
            return
        self._thoughts += token
        self._render_thoughts()

    def get_thoughts(self) -> str:
        return (self._thoughts or "").strip()

    def _render_thoughts(self):
        """Create (once) and update a collapsed 'Thoughts' expander holding
        the model's reasoning.  No-op for non-assistant messages."""
        text = (self._thoughts or "").strip()
        if not text or self._thoughts_container is None or not self._show_thoughts:
            return
        if self._thoughts_label is None:
            expander = Gtk.Expander(label="💭  Thoughts")
            expander.set_expanded(False)          # click to open
            expander.add_css_class("thoughts-expander")
            lbl = _make_wrap_label()
            lbl.add_css_class("thoughts-text")
            lbl.set_margin_top(4)
            lbl.set_margin_start(6)
            lbl.set_margin_bottom(4)
            expander.set_child(lbl)
            self._thoughts_container.append(expander)
            self._thoughts_label = lbl
        try:
            self._thoughts_label.set_text(text)
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════
# CHAT ROW
# ═════════════════════════════════════════════════════════════════════

class ChatRow(Gtk.ListBoxRow):
    def __init__(self, chat: Chat):
        super().__init__()
        self.chat = chat
        self.add_css_class("chat-row")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if chat.pinned:
            pin = Gtk.Label(label="📌")
            pin.add_css_class("pin-icon")
            title_row.append(pin)
        if chat.agent_mode:
            mode = Gtk.Label(label="⚡")
            mode.add_css_class("pin-icon")
            title_row.append(mode)

        title = Gtk.Label(label=chat.title, xalign=0.0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_hexpand(True)
        title.add_css_class("title-line")
        title_row.append(title)
        outer.append(title_row)

        meta_lbl = Gtk.Label(label=self._format_meta(chat), xalign=0.0)
        meta_lbl.add_css_class("meta-line")
        meta_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        outer.append(meta_lbl)

        self.set_child(outer)

    @staticmethod
    def _format_meta(chat: Chat) -> str:
        try:
            dt = datetime.datetime.fromtimestamp(chat.updated_at)
            delta = datetime.datetime.now() - dt
            if delta.days == 0:
                stamp = dt.strftime("%H:%M")
            elif delta.days == 1:
                stamp = "yesterday"
            elif delta.days < 7:
                stamp = dt.strftime("%a")
            else:
                stamp = dt.strftime("%d %b")
        except Exception:
            stamp = ""
        model_short = (chat.model or "").split(":", 1)[0].split("/")[-1]
        if model_short and stamp:
            return f"{stamp}   ·   {model_short}"
        return stamp or model_short or ""


# ═════════════════════════════════════════════════════════════════════
# CONFIRM DIALOGS
# ═════════════════════════════════════════════════════════════════════

def confirm_command_dialog(parent: Gtk.Window, command: str, reason: str,
                            on_decision: Callable[[bool, Optional[str]], None],
                            catastrophic: bool = False):
    """Confirm a shell command.  If it needs sudo, show an inline
    password field so the operator can authenticate in one step.

    on_decision(allow: bool, password: Optional[str]) — password is the
    typed sudo password when the command needs sudo and the operator
    approved; otherwise None.

    catastrophic=True is the auto-run backstop: the command matched a
    system-destroying pattern (disk wipe, fs nuke, recursive root delete).
    The dialog shouts, defaults to Cancel, and is shown even in auto-run
    mode so an irreversible mistake always stops for a human.
    """
    needs_sudo = command_needs_sudo(command)
    if catastrophic:
        title = "⚠ DESTRUCTIVE COMMAND — confirm to run"
        subtitle = ("This command can irreversibly destroy data or this "
                    "system (disk/filesystem wipe, recursive delete of a "
                    "system path, or similar). It will NOT auto-run. Only "
                    "continue if you typed it or fully understand it.\n\n"
                    f"{reason}")
    else:
        title = "Run shell command?"
        subtitle = (f"{reason}\n\nRuns as your user.  Output goes back to Kali."
                    if not needs_sudo else
                    f"{reason}\n\nThis needs root.  Enter your sudo password to "
                    f"let it through — Kali never stores or sees it.")
    dlg = Adw.AlertDialog.new(title, subtitle)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    cmd_lbl = Gtk.Label(label=command, xalign=0.0)
    cmd_lbl.set_wrap(True)
    cmd_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    cmd_lbl.set_selectable(True)
    cmd_lbl.add_css_class("confirm-cmd")
    body.append(cmd_lbl)

    pw_entry: Optional[Gtk.PasswordEntry] = None
    if needs_sudo:
        pw_entry = Gtk.PasswordEntry()
        pw_entry.set_show_peek_icon(True)
        pw_entry.add_css_class("sudo-pass")
        pw_entry.set_property("placeholder-text", "sudo password")
        body.append(pw_entry)

    dlg.set_extra_child(body)
    dlg.add_response("cancel", "Cancel")
    run_label = ("Run anyway" if catastrophic
                 else "Run" if not needs_sudo else "Authenticate & run")
    dlg.add_response("run", run_label)
    if catastrophic:
        # Red button, and default to Cancel so a reflexive Enter is safe.
        dlg.set_response_appearance("run", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
    else:
        dlg.set_response_appearance("run", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("run")
    dlg.set_close_response("cancel")

    def _cb(_dlg, response):
        allow = (response == "run")
        pw = pw_entry.get_text() if (allow and pw_entry is not None) else None
        on_decision(allow, pw)
    dlg.connect("response", _cb)

    # Pressing Enter in the password field activates the run response.
    # (Not for catastrophic commands — there the default is Cancel.)
    if pw_entry is not None and not catastrophic:
        pw_entry.connect("activate", lambda *_: dlg.response("run"))

    dlg.present(parent)
    if pw_entry is not None:
        pw_entry.grab_focus()


def confirm_sensitive_read_dialog(parent: Gtk.Window, path: str,
                                   on_decision: Callable[[bool], None]):
    dlg = Adw.AlertDialog.new(
        "Read sensitive file?",
        f"Kali wants to read:\n\n{path}\n\nThis path is on the "
        f"sensitive list (keys, secrets, system auth).",
    )
    dlg.add_response("cancel", "Deny")
    dlg.add_response("read", "Allow")
    dlg.set_response_appearance("read", Adw.ResponseAppearance.DESTRUCTIVE)
    dlg.set_default_response("cancel")
    dlg.set_close_response("cancel")

    def _cb(_dlg, response):
        on_decision(response == "read")
    dlg.connect("response", _cb)
    dlg.present(parent)


# ═════════════════════════════════════════════════════════════════════
# SETTINGS DIALOG
# ═════════════════════════════════════════════════════════════════════

class SettingsDialog(Adw.PreferencesDialog):
    def __init__(self, parent: "MainWindow"):
        super().__init__()
        self.win = parent
        self.set_title("Settings")

        # ── BACKENDS ───────────────────────────────────────
        page = Adw.PreferencesPage()
        page.set_title("Backends")
        page.set_icon_name("network-server-symbolic")

        # ── Provider routing (which cloud provider is active) ──
        self._model_rows = {}   # provider_key -> (combo_row, [names])

        rg = Adw.PreferencesGroup()
        rg.set_title("Provider routing")
        rg.set_description(
            "Pick which cloud provider Kali uses.  Set that provider's "
            "API key and model in its section below.")

        self.active_provider_row = Adw.ComboRow()
        self.active_provider_row.set_title("Active provider")
        prov_labels = [p.label for p in PROVIDERS]
        self.active_provider_row.set_model(Gtk.StringList.new(prov_labels))
        cur_key = parent.settings.get("active_provider", "siliconflow")
        prov_keys = [p.key for p in PROVIDERS]
        if cur_key in prov_keys:
            self.active_provider_row.set_selected(prov_keys.index(cur_key))
        self.active_provider_row.connect("notify::selected",
                                         self._on_active_provider)
        rg.add(self.active_provider_row)
        page.add(rg)

        # ── One group per cloud provider: key + model picker ──
        for spec in PROVIDERS:
            self._build_provider_group(page, spec, parent)

        self.add(page)

        # ── GENERATION ─────────────────────────────────────
        gen_page = Adw.PreferencesPage()
        gen_page.set_title("Generation")
        gen_page.set_icon_name("preferences-other-symbolic")

        gen_g = Adw.PreferencesGroup()
        gen_g.set_title("Parameters")

        temp_row = Adw.SpinRow.new_with_range(0.0, 2.0, 0.05)
        temp_row.set_title("Temperature")
        temp_row.set_subtitle("Higher = more creative")
        temp_row.set_value(parent.settings["temperature"])
        temp_row.connect("notify::value", self._on_temp)
        gen_g.add(temp_row)

        max_row = Adw.SpinRow.new_with_range(256, 8192, 128)
        max_row.set_title("Max response tokens")
        max_row.set_value(parent.settings["max_tokens"])
        max_row.connect("notify::value", self._on_max)
        gen_g.add(max_row)

        gen_page.add(gen_g)

        # ── Intelligence & trust ──
        intel_g = Adw.PreferencesGroup()
        intel_g.set_title("Intelligence &amp; trust")
        intel_g.set_description(
            "Verification, reasoning, and context handling.")

        self.headroom_row = Adw.SwitchRow()
        self.headroom_row.set_title("Context compression")
        self.headroom_row.set_subtitle(
            "Crush bulky tool output before it reaches the model — saves "
            "context and tokens on long sessions.")
        self.headroom_row.set_active(
            bool(parent.settings.get("headroom_enabled", True)))
        self.headroom_row.connect(
            "notify::active",
            lambda r, _ps: self._set("headroom_enabled", r.get_active()))
        intel_g.add(self.headroom_row)

        self.thoughts_row = Adw.SwitchRow()
        self.thoughts_row.set_title("Show reasoning panel")
        self.thoughts_row.set_subtitle(
            "Add a click-to-open Thoughts panel on a reply when the model "
            "exposes its reasoning.")
        self.thoughts_row.set_active(
            bool(parent.settings.get("show_thoughts", True)))
        self.thoughts_row.connect(
            "notify::active",
            lambda r, _ps: self._set("show_thoughts", r.get_active()))
        intel_g.add(self.thoughts_row)

        verify_row = Adw.SpinRow.new_with_range(2, 8, 1)
        verify_row.set_title("Verification sources")
        verify_row.set_subtitle(
            "How many independent sources web_verify cross-checks before "
            "she trusts a claim.")
        verify_row.set_value(int(parent.settings.get("verify_max_sources", 5)))
        verify_row.connect(
            "notify::value",
            lambda r, *_: self._set("verify_max_sources", int(r.get_value())))
        intel_g.add(verify_row)

        gen_page.add(intel_g)

        # ── Extensions (sidecar capabilities) ──
        ext_g = Adw.PreferencesGroup()
        ext_g.set_title("Extensions")
        ext_g.set_description(
            "Kali's sidecar capabilities. Memory, skills and foresight are on "
            "by default. MCP stays off until you start it here.")

        self.memory_row = Adw.SwitchRow()
        self.memory_row.set_title("Memory")
        self.memory_row.set_subtitle(
            "Persistent cross-session recall of facts about you and your gear.")
        self.memory_row.set_active(
            bool(parent.settings.get("memory_enabled", True)))
        self.memory_row.connect(
            "notify::active",
            lambda r, _ps: self._set("memory_enabled", r.get_active()))
        ext_g.add(self.memory_row)

        self.skills_row = Adw.SwitchRow()
        self.skills_row.set_title("Skills")
        self.skills_row.set_subtitle(
            "Let Kali write and sandbox-test small reusable skills.")
        self.skills_row.set_active(
            bool(parent.settings.get("skills_enabled", True)))
        self.skills_row.connect(
            "notify::active",
            lambda r, _ps: self._set("skills_enabled", r.get_active()))
        ext_g.add(self.skills_row)

        self.foresight_row = Adw.SwitchRow()
        self.foresight_row.set_title("Foresight")
        self.foresight_row.set_subtitle(
            "Predict a command's consequences before running it. "
            "Catastrophic commands are always blocked regardless.")
        self.foresight_row.set_active(
            bool(parent.settings.get("foresight_enabled", True)))
        self.foresight_row.connect(
            "notify::active",
            lambda r, _ps: self._set("foresight_enabled", r.get_active()))
        ext_g.add(self.foresight_row)

        self.mcp_row = Adw.SwitchRow()
        self.mcp_row.set_title("MCP (external tool servers)")
        self.mcp_row.set_subtitle(
            "Start the MCP servers configured below. Off by default — MCP runs "
            "external subprocesses (an RCE surface), so only enable it for "
            "servers you trust.")
        self.mcp_row.set_active(bool(parent.settings.get("mcp_enabled", False)))
        self.mcp_row.connect("notify::active", self._on_mcp_toggled)
        ext_g.add(self.mcp_row)

        self.mcp_servers_row = Adw.EntryRow()
        self.mcp_servers_row.set_title("Add MCP server (command)")
        self.mcp_servers_row.set_text("")
        self.mcp_servers_row.set_show_apply_button(True)
        self.mcp_servers_row.connect("apply", self._on_mcp_server_add)
        ext_g.add(self.mcp_servers_row)

        self.mcp_status_row = Adw.ActionRow()
        self.mcp_status_row.set_title("MCP status")
        self._refresh_mcp_status()
        ext_g.add(self.mcp_status_row)

        gen_page.add(ext_g)
        self.add(gen_page)

        # ── DISPLAY ────────────────────────────────────────
        d_page = Adw.PreferencesPage()
        d_page.set_title("Display")
        d_page.set_icon_name("video-display-symbolic")

        dg = Adw.PreferencesGroup()
        dg.set_title("UI scale")
        dg.set_description(
            "Resize text, padding, and controls.  Changes apply live — "
            "no restart needed.  Set to 0 for automatic detection based "
            "on screen size.")

        # Use a SpinRow over the full useful range.  0 is a sentinel
        # meaning "let auto-detection pick" — clamped on the lower side
        # so a slip of the finger doesn't make the UI invisible.
        ui_scale_current = parent.settings.get("ui_scale", 0) or 0
        scale_row = Adw.SpinRow.new_with_range(0.0, 2.0, 0.05)
        scale_row.set_title("Scale factor")
        scale_row.set_subtitle("1.0 = unmodified.  Higher = bigger.  0 = auto.")
        scale_row.set_value(float(ui_scale_current))
        scale_row.set_digits(2)
        scale_row.connect("notify::value", self._on_ui_scale)
        dg.add(scale_row)

        # Reset button row
        reset_row = Adw.ActionRow()
        reset_row.set_title("Reset to auto-detect")
        reset_row.set_subtitle("Sets scale back to 0 and re-runs detection.")
        reset_btn = Gtk.Button(label="Reset")
        reset_btn.set_valign(Gtk.Align.CENTER)
        reset_btn.add_css_class("icon-button")
        def _reset_scale(_b):
            scale_row.set_value(0.0)
        reset_btn.connect("clicked", _reset_scale)
        reset_row.add_suffix(reset_btn)
        dg.add(reset_row)

        d_page.add(dg)

        # Images & vision
        iv_g = Adw.PreferencesGroup()
        iv_g.set_title("Images &amp; vision")
        iv_g.set_description(
            "Show pictures in chat, and choose the model Kali uses to SEE "
            "images (analyze_image).")

        self.render_images_row = Adw.SwitchRow()
        self.render_images_row.set_title("Show images in chat")
        self.render_images_row.set_subtitle(
            "Render image links as pictures.  Off = a tappable link instead "
            "(no auto-download; better OPSEC).")
        self.render_images_row.set_active(
            bool(parent.settings.get("chat_render_images", True)))
        self.render_images_row.connect(
            "notify::active",
            lambda r, _ps: self._set_render_images(r.get_active()))
        iv_g.add(self.render_images_row)

        self.vision_provider_row = Adw.ComboRow()
        self.vision_provider_row.set_title("Vision provider")
        self.vision_provider_row.set_subtitle(
            "Which provider hosts the vision model (must have a key set).")
        _vp_labels = [p.label for p in PROVIDERS]
        _vp_keys = [p.key for p in PROVIDERS]
        self.vision_provider_row.set_model(Gtk.StringList.new(_vp_labels))
        _cur_vp = parent.settings.get("vision_provider", "siliconflow")
        if _cur_vp in _vp_keys:
            self.vision_provider_row.set_selected(_vp_keys.index(_cur_vp))
        self.vision_provider_row.connect(
            "notify::selected",
            lambda r, _ps: self._set("vision_provider", _vp_keys[r.get_selected()])
            if 0 <= r.get_selected() < len(_vp_keys) else None)
        iv_g.add(self.vision_provider_row)

        self.vision_model_row = Adw.EntryRow()
        self.vision_model_row.set_title("Vision model")
        self.vision_model_row.set_text(
            parent.settings.get("vision_model", "") or "")
        self.vision_model_row.set_show_apply_button(True)
        self.vision_model_row.connect(
            "apply",
            lambda r: self._set("vision_model", r.get_text().strip()))
        iv_g.add(self.vision_model_row)

        d_page.add(iv_g)
        self.add(d_page)

        # ── BEHAVIOUR ──────────────────────────────────────
        b_page = Adw.PreferencesPage()
        b_page.set_title("Behaviour")
        b_page.set_icon_name("system-run-symbolic")

        bg = Adw.PreferencesGroup()
        bg.set_title("Agent mode")
        self.agent_default_row = Adw.SwitchRow()
        self.agent_default_row.set_title("Agent mode by default")
        self.agent_default_row.set_active(parent.settings["agent_mode_default"])
        self.agent_default_row.connect("notify::active", self._on_agent_default)
        bg.add(self.agent_default_row)

        self.confirm_all_row = Adw.SwitchRow()
        self.confirm_all_row.set_title("Confirm every command")
        self.confirm_all_row.set_subtitle(
            "Off (default): Kali runs commands without a click. "
            "System-destroying commands always prompt regardless.")
        self.confirm_all_row.set_active(parent.settings["confirm_all_commands"])
        self.confirm_all_row.connect("notify::active", self._on_confirm_all)
        bg.add(self.confirm_all_row)
        b_page.add(bg)

        # Watcher
        wg = Adw.PreferencesGroup()
        wg.set_title("Watcher (background)")
        wg.set_description(
            "Periodically checks system state and surfaces notable events.")

        self.watcher_row = Adw.SwitchRow()
        self.watcher_row.set_title("Enable watcher")
        self.watcher_row.set_active(parent.settings["watcher_enabled"])
        self.watcher_row.connect("notify::active", self._on_watcher_enable)
        wg.add(self.watcher_row)

        self.w_updates_row = Adw.SwitchRow()
        self.w_updates_row.set_title("Watch for security updates")
        self.w_updates_row.set_active(parent.settings["watcher_check_updates"])
        self.w_updates_row.connect("notify::active",
                                    lambda r, _ps: self._set("watcher_check_updates",
                                                              r.get_active()))
        wg.add(self.w_updates_row)

        self.w_dl_row = Adw.SwitchRow()
        self.w_dl_row.set_title("Watch Downloads folder")
        self.w_dl_row.set_active(parent.settings["watcher_check_downloads"])
        self.w_dl_row.connect("notify::active",
                               lambda r, _ps: self._set("watcher_check_downloads",
                                                         r.get_active()))
        wg.add(self.w_dl_row)

        self.w_journal_row = Adw.SwitchRow()
        self.w_journal_row.set_title("Watch system journal")
        self.w_journal_row.set_subtitle("Surfaces failed logins, USB, OOM")
        self.w_journal_row.set_active(parent.settings["watcher_check_journal"])
        self.w_journal_row.connect("notify::active",
                                    lambda r, _ps: self._set("watcher_check_journal",
                                                              r.get_active()))
        wg.add(self.w_journal_row)

        interval = Adw.SpinRow.new_with_range(5, 360, 5)
        interval.set_title("Check interval (minutes)")
        interval.set_value(parent.settings["watcher_interval_minutes"])
        interval.connect("notify::value",
                          lambda r, *_: self._set("watcher_interval_minutes",
                                                  int(r.get_value())))
        wg.add(interval)
        b_page.add(wg)

        # History / retention
        hg = Adw.PreferencesGroup()
        hg.set_title("Chat history")
        hg.set_description(
            "Keep things ephemeral.  Pinned chats are always kept.")

        self.fresh_chat_row = Adw.SwitchRow()
        self.fresh_chat_row.set_title("Start a new chat each launch")
        self.fresh_chat_row.set_active(
            bool(parent.settings.get("ephemeral_new_chat_on_launch", True)))
        self.fresh_chat_row.connect(
            "notify::active",
            lambda r, _ps: self._set("ephemeral_new_chat_on_launch",
                                     r.get_active()))
        hg.add(self.fresh_chat_row)

        self.discard_empty_row = Adw.SwitchRow()
        self.discard_empty_row.set_title("Discard empty chats")
        self.discard_empty_row.set_subtitle(
            "Bin unused 'New chat' placeholders on close.")
        self.discard_empty_row.set_active(
            bool(parent.settings.get("discard_empty_chats", True)))
        self.discard_empty_row.connect(
            "notify::active",
            lambda r, _ps: self._set("discard_empty_chats", r.get_active()))
        hg.add(self.discard_empty_row)

        retain_row = Adw.SpinRow.new_with_range(0, 720, 1)
        retain_row.set_title("Auto-delete chats after (hours)")
        retain_row.set_subtitle("Idle chats older than this go.  0 = keep forever.")
        retain_row.set_value(
            float(parent.settings.get("chat_retention_hours", 24)))
        retain_row.connect(
            "notify::value",
            lambda r, *_: self._set("chat_retention_hours",
                                    int(r.get_value())))
        hg.add(retain_row)
        b_page.add(hg)
        self.add(b_page)

        # ── VOICE ──────────────────────────────────────────
        v_page = Adw.PreferencesPage()
        v_page.set_title("Voice")
        v_page.set_icon_name("audio-input-microphone-symbolic")

        tts = getattr(parent, "tts", None)
        stt = getattr(parent, "stt", None)

        # Output (read replies aloud)
        og = Adw.PreferencesGroup()
        og.set_title("Read replies aloud")
        if tts is not None and tts.available():
            og.set_description(f"Speech engine: {tts.engine_name()}.")
        elif tts is not None:
            og.set_description(
                "No speech engine found.  Install espeak-ng (basic) or "
                "Piper (neural) — see install.sh --voice.")
        else:
            og.set_description("Voice module unavailable.")

        self.tts_enabled_row = Adw.SwitchRow()
        self.tts_enabled_row.set_title("Read assistant replies aloud")
        self.tts_enabled_row.set_active(bool(parent.settings.get("tts_enabled")))
        self.tts_enabled_row.set_sensitive(tts is not None and tts.available())
        self.tts_enabled_row.connect("notify::active", self._on_tts_enable)
        og.add(self.tts_enabled_row)

        self.tts_engine_row = Adw.ComboRow()
        self.tts_engine_row.set_title("Voice engine")
        self.tts_engine_row.set_subtitle("Auto prefers Piper, falls back to espeak")
        self._tts_engine_keys = ["auto", "piper", "espeak"]
        self.tts_engine_row.set_model(Gtk.StringList.new(
            ["Auto", "Piper (neural)", "espeak (robotic)"]))
        cur_eng = (parent.settings.get("tts_engine") or "auto").lower()
        if cur_eng in self._tts_engine_keys:
            self.tts_engine_row.set_selected(self._tts_engine_keys.index(cur_eng))
        self.tts_engine_row.connect("notify::selected", self._on_tts_engine)
        og.add(self.tts_engine_row)

        rate_row = Adw.SpinRow.new_with_range(0.5, 2.0, 0.05)
        rate_row.set_title("Speech rate")
        rate_row.set_subtitle("1.0 = normal.  Lower = slower.")
        rate_row.set_digits(2)
        rate_row.set_value(float(parent.settings.get("tts_rate", 1.0) or 1.0))
        rate_row.connect("notify::value",
                         lambda r, *_: self._set("tts_rate",
                                                 round(r.get_value(), 2)))
        og.add(rate_row)

        self.tts_voice_row = Adw.EntryRow()
        self.tts_voice_row.set_title("Piper voice file (.onnx)")
        self.tts_voice_row.set_text(parent.settings.get("tts_voice", "") or "")
        self.tts_voice_row.set_show_apply_button(True)
        self.tts_voice_row.connect("apply", self._on_tts_voice)
        og.add(self.tts_voice_row)

        test_row = Adw.ActionRow()
        test_row.set_title("Test voice")
        test_row.set_subtitle("Speak a short sample with the current settings.")
        test_btn = Gtk.Button(label="▶ Test")
        test_btn.set_valign(Gtk.Align.CENTER)
        test_btn.add_css_class("icon-button")
        test_btn.set_sensitive(tts is not None and tts.available())
        test_btn.connect("clicked", self._on_tts_test)
        test_row.add_suffix(test_btn)
        og.add(test_row)
        v_page.add(og)

        # Input (speak instead of type)
        ig = Adw.PreferencesGroup()
        ig.set_title("Speak instead of type")
        if stt is not None and stt.recorder_available():
            ig.set_description(
                f"Mic recorder: {stt.recorder_name()}.  Transcribed by "
                "SiliconFlow (SenseVoiceSmall) or Groq (Whisper) — whichever "
                "key you have.")
        elif stt is not None:
            ig.set_description(
                "No microphone recorder found.  Install pulseaudio-utils "
                "(parecord) or alsa-utils (arecord).")
        else:
            ig.set_description("Voice module unavailable.")

        self.autosend_row = Adw.SwitchRow()
        self.autosend_row.set_title("Auto-send after transcription")
        self.autosend_row.set_subtitle(
            "Off = drop the text in the box so you can edit before sending.")
        self.autosend_row.set_active(bool(parent.settings.get("voice_autosend", True)))
        self.autosend_row.set_sensitive(stt is not None and stt.recorder_available())
        self.autosend_row.connect("notify::active",
                                  lambda r, _ps: self._set("voice_autosend",
                                                           r.get_active()))
        ig.add(self.autosend_row)

        self.stt_provider_row = Adw.ComboRow()
        self.stt_provider_row.set_title("Transcription provider")
        self.stt_provider_row.set_subtitle(
            "Auto uses your active chat provider when it can transcribe.")
        self._stt_provider_keys = ["auto", "siliconflow", "groq"]
        self.stt_provider_row.set_model(Gtk.StringList.new(
            ["Auto", "SiliconFlow (SenseVoiceSmall)", "Groq (Whisper)"]))
        cur_sp = (parent.settings.get("stt_provider") or "auto").lower()
        if cur_sp in self._stt_provider_keys:
            self.stt_provider_row.set_selected(
                self._stt_provider_keys.index(cur_sp))
        self.stt_provider_row.set_sensitive(
            stt is not None and stt.recorder_available())
        self.stt_provider_row.connect(
            "notify::selected",
            lambda r, *_: self._set(
                "stt_provider",
                self._stt_provider_keys[r.get_selected()]))
        ig.add(self.stt_provider_row)

        self.stt_model_row = Adw.EntryRow()
        self.stt_model_row.set_title("Groq Whisper model")
        self.stt_model_row.set_text(
            parent.settings.get("stt_model", "whisper-large-v3-turbo"))
        self.stt_model_row.set_show_apply_button(True)
        self.stt_model_row.connect("apply",
                                   lambda r: self._set("stt_model",
                                                       r.get_text().strip()
                                                       or "whisper-large-v3-turbo"))
        ig.add(self.stt_model_row)

        self.stt_lang_row = Adw.EntryRow()
        self.stt_lang_row.set_title("Language hint (optional)")
        self.stt_lang_row.set_text(parent.settings.get("stt_language", "") or "")
        self.stt_lang_row.set_show_apply_button(True)
        self.stt_lang_row.connect("apply",
                                  lambda r: self._set("stt_language",
                                                      r.get_text().strip()))
        ig.add(self.stt_lang_row)

        stt_test_row = Adw.ActionRow()
        stt_test_row.set_title("Test microphone")
        stt_test_row.set_subtitle(
            "Records ~4s, transcribes, shows the exact result or error.")
        self.stt_test_btn = Gtk.Button(label="● Record 4s")
        self.stt_test_btn.set_valign(Gtk.Align.CENTER)
        self.stt_test_btn.add_css_class("icon-button")
        self.stt_test_btn.set_sensitive(
            stt is not None and stt.recorder_available())
        self.stt_test_btn.connect("clicked", self._on_stt_test)
        stt_test_row.add_suffix(self.stt_test_btn)
        ig.add(stt_test_row)
        v_page.add(ig)
        self.add(v_page)

        # ── SYSTEM PROMPT ──────────────────────────────────
        sp_page = Adw.PreferencesPage()
        sp_page.set_title("Persona")
        sp_page.set_icon_name("emblem-favorite-symbolic")

        sp_g = Adw.PreferencesGroup()
        sp_g.set_title("Custom addendum to system prompt")
        sp_g.set_description(
            "Appended to Kali's built-in persona.  "
            "Edit kali_persona.py for deeper changes.")

        sp_card = Gtk.Frame()
        sp_card.set_margin_top(8)
        sp_card.set_margin_bottom(8)
        sp_sw = Gtk.ScrolledWindow()
        sp_sw.set_min_content_height(_scaled(200, floor=140))
        sp_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.sp_view = Gtk.TextView()
        self.sp_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.sp_view.set_top_margin(8)
        self.sp_view.set_bottom_margin(8)
        self.sp_view.set_left_margin(8)
        self.sp_view.set_right_margin(8)
        self.sp_view.get_buffer().set_text(parent.settings.get("system_prompt", ""))
        self.sp_view.get_buffer().connect("changed", self._on_sp_changed)
        sp_sw.set_child(self.sp_view)
        sp_card.set_child(sp_sw)
        sp_g.add(sp_card)
        sp_page.add(sp_g)
        self.add(sp_page)

    # ── helpers ────────────────────────────────────────────

    def _build_provider_group(self, page, spec, parent):
        """Build a Settings group for one cloud provider: API key entry,
        a model picker (curated big-first list, refreshable from the live
        catalogue), and a 'get a key' link."""
        g = Adw.PreferencesGroup()
        g.set_title(spec.label)
        g.set_description(spec.blurb)

        # API key
        key_row = Adw.PasswordEntryRow()
        key_row.set_title("API key")
        key_row.set_text(parent.settings.get(f"{spec.key}_api_key", ""))
        key_row.connect(
            "changed",
            lambda row, k=spec.key: self._on_provider_key(k, row.get_text()))
        g.add(key_row)

        # Model picker
        model_row = Adw.ComboRow()
        model_row.set_title("Model")
        model_row.set_subtitle("Biggest first. Use ⟳ to fetch live list.")
        names = list(spec.chain)
        saved = parent.settings.get(f"{spec.key}_model", spec.default_model)
        if saved and saved not in names:
            names.insert(0, saved)   # keep a custom/old selection visible
        model_row.set_model(Gtk.StringList.new(names))
        if saved in names:
            model_row.set_selected(names.index(saved))
        model_row.connect(
            "notify::selected",
            lambda row, _ps, k=spec.key: self._on_provider_model(k, row))
        self._model_rows[spec.key] = (model_row, names)

        # Refresh-from-API button lives as a suffix on the model row
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_valign(Gtk.Align.CENTER)
        refresh_btn.add_css_class("flat")
        refresh_btn.set_tooltip_text("Fetch available models from the API")
        refresh_btn.connect(
            "clicked",
            lambda _b, k=spec.key: self._fetch_live_models(k))
        model_row.add_suffix(refresh_btn)
        g.add(model_row)

        # Get-a-key link
        link_row = Adw.ActionRow()
        link_row.set_title("Get an API key")
        link_btn = Gtk.LinkButton.new_with_label(spec.key_url, "Open")
        link_btn.set_valign(Gtk.Align.CENTER)
        link_row.add_suffix(link_btn)
        g.add(link_row)

        page.add(g)

    def _set(self, key, value):
        self.win.settings[key] = value
        save_settings(self.win.settings)

    def _set_render_images(self, on):
        # Persist and apply live so the chat renderer picks it up immediately.
        self._set("chat_render_images", on)
        global _RENDER_IMAGES
        _RENDER_IMAGES = bool(on)

    def _ext(self):
        return getattr(self.win, "_ext", None)

    def _refresh_mcp_status(self):
        row = getattr(self, "mcp_status_row", None)
        if row is None:
            return
        ext = self._ext()
        if ext is None:
            row.set_subtitle("extensions not loaded")
            return
        try:
            st = ext.mcp_status()
            if st.get("running"):
                row.set_subtitle(
                    f"running — {st.get('tools', 0)} tools from "
                    f"{st.get('configured_servers', 0)} server(s)")
            else:
                row.set_subtitle(
                    f"stopped — {st.get('configured_servers', 0)} "
                    f"server(s) configured")
        except Exception:
            row.set_subtitle("status unavailable")

    def _on_mcp_toggled(self, row, _ps):
        on = row.get_active()
        if getattr(self, "_mcp_toggling", False):
            return
        self._set("mcp_enabled", on)
        ext = self._ext()
        if ext is None:
            self.win._show_toast("Extensions not loaded — MCP unavailable")
            return
        try:
            res = ext.set_mcp_enabled(on)
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        if res.get("ok"):
            self.win._show_toast(
                f"MCP started — {res.get('tools', 0)} tools" if on
                else "MCP stopped")
        else:
            self.win._show_toast(f"MCP: {res.get('error', 'failed to start')}")
            if on:                       # revert the switch without recursing
                self._mcp_toggling = True
                row.set_active(False)
                self._mcp_toggling = False
                self._set("mcp_enabled", False)
        self._refresh_mcp_status()

    def _on_mcp_server_add(self, row):
        raw = (row.get_text() or "").strip()
        if not raw:
            return
        # Parse "command arg1 arg2" into {name, command, args}.
        parts = raw.split()
        cmd = parts[0]
        args = parts[1:]
        name = os.path.basename(cmd).split(".")[0] or "server"
        servers = list(self.win.settings.get("mcp_servers") or [])
        if any(s.get("name") == name for s in servers):
            name = f"{name}-{len(servers) + 1}"
        servers.append({"name": name, "command": cmd, "args": args})
        self._set("mcp_servers", servers)
        row.set_text("")
        self.win._show_toast(
            f"Added MCP server '{name}'. Toggle MCP off/on to (re)start.")
        self._refresh_mcp_status()

    def _on_provider_key(self, key, text):
        self.win.settings[f"{key}_api_key"] = text
        save_settings(self.win.settings)
        backend = self.win.cloud.get(key)
        if backend is not None and hasattr(backend, "set_api_key"):
            backend.set_api_key(text)
        self.win.update_status_pills()

    def _on_provider_model(self, key, row):
        m = row.get_model()
        idx = row.get_selected()
        if m and 0 <= idx < m.get_n_items():
            name = m.get_string(idx)
            if name and not name.startswith("("):
                self.win.settings[f"{key}_model"] = name
                save_settings(self.win.settings)

    def _on_active_provider(self, row, _ps):
        idx = row.get_selected()
        keys = [p.key for p in PROVIDERS]
        if 0 <= idx < len(keys):
            self.win.settings["active_provider"] = keys[idx]
            save_settings(self.win.settings)
            self.win.update_status_pills()

    def _fetch_live_models(self, key):
        """Query the provider's live /models catalogue on a background
        thread and repopulate its picker.  Falls back silently to the
        curated chain on any failure."""
        backend = self.win.cloud.get(key)
        if backend is None or not hasattr(backend, "list_models_live"):
            self.win._show_toast("This provider has no live model list.")
            return
        spec = PROVIDERS_BY_KEY.get(key)
        self.win._show_toast(f"Fetching {spec.label if spec else key} models…")

        def _bg():
            ids = backend.list_models_live()
            GLib.idle_add(lambda: self._apply_live_models(key, ids) or False)

        threading.Thread(target=_bg, daemon=True).start()

    def _apply_live_models(self, key, ids):
        entry = self._model_rows.get(key)
        if not entry:
            return
        model_row, _old = entry
        if not ids:
            self.win._show_toast("No models returned — keeping defaults.")
            return
        # Keep the currently-saved model visible even if the live list
        # omits it (some catalogues page or filter).
        saved = self.win.settings.get(f"{key}_model", "")
        names = list(ids)
        if saved and saved not in names:
            names.insert(0, saved)
        model_row.set_model(Gtk.StringList.new(names))
        if saved in names:
            model_row.set_selected(names.index(saved))
        self._model_rows[key] = (model_row, names)
        spec = PROVIDERS_BY_KEY.get(key)
        self.win._show_toast(
            f"{spec.label if spec else key}: {len(ids)} models loaded.")

    def _on_temp(self, row, *args):
        self._set("temperature", float(row.get_value()))

    def _on_max(self, row, *args):
        self._set("max_tokens", int(row.get_value()))

    def _on_ui_scale(self, row, *args):
        # Persist as float.  Then trigger a LIVE CSS reload so the
        # change is visible immediately — no app restart needed.
        # Debounce the reload by 200ms so rapid scrolling doesn't
        # spam the CSS provider.
        value = float(row.get_value())
        self._set("ui_scale", value)

        if hasattr(self, "_ui_scale_timeout") and self._ui_scale_timeout:
            try:
                GLib.source_remove(self._ui_scale_timeout)
            except Exception:
                pass
            self._ui_scale_timeout = None

        def _do_reload():
            try:
                self.win.app.reload_css(value)
            except Exception as e:
                log(f"ui_scale live reload failed: {e}")
            self._ui_scale_timeout = None
            return False

        self._ui_scale_timeout = GLib.timeout_add(200, _do_reload)

    def _on_agent_default(self, row, _ps):
        self._set("agent_mode_default", row.get_active())

    def _on_confirm_all(self, row, _ps):
        self._set("confirm_all_commands", row.get_active())

    def _on_watcher_enable(self, row, _ps):
        self._set("watcher_enabled", row.get_active())
        if row.get_active():
            self.win.watcher.start()
        else:
            self.win.watcher.stop()

    def _on_sp_changed(self, buf):
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self._set("system_prompt", text)

    # ── voice handlers ──
    def _on_tts_enable(self, row, _ps):
        on = row.get_active()
        self._set("tts_enabled", on)
        # Keep the toolbar speaker toggle in sync if it exists.
        tb = getattr(self.win, "tts_toggle", None)
        if tb is not None and tb.get_active() != on:
            tb.set_active(on)
        if not on and getattr(self.win, "tts", None):
            self.win.tts.stop()

    def _on_tts_engine(self, row, _ps):
        idx = row.get_selected()
        key = self._tts_engine_keys[idx] if 0 <= idx < len(self._tts_engine_keys) else "auto"
        self._set("tts_engine", key)
        tts = getattr(self.win, "tts", None)
        if tts is not None:
            tts.reconfigure()
            avail = tts.available()
            self.tts_enabled_row.set_sensitive(avail)
            if avail:
                self.win._show_toast(f"Voice engine: {tts.engine_name()}")
            else:
                self.win._show_toast("That engine isn't available on this box.")

    def _on_tts_voice(self, row):
        self._set("tts_voice", row.get_text().strip())
        tts = getattr(self.win, "tts", None)
        if tts is not None:
            tts.reconfigure()
            self.tts_enabled_row.set_sensitive(tts.available())
            self.win._show_toast(f"Voice engine: {tts.engine_name()}")

    def _on_tts_test(self, _btn):
        tts = getattr(self.win, "tts", None)
        if tts is None or not tts.available():
            self.win._show_toast("No voice engine available.")
            return
        tts.stop()
        tts.speak_all("Voice check. Kali is online and ready.")

    def _on_stt_test(self, _btn):
        stt = getattr(self.win, "stt", None)
        if stt is None or not stt.recorder_available():
            self.win._show_toast("No microphone recorder available.")
            return
        reason = stt.unavailable_reason()
        if reason:
            self.win._show_toast(reason, timeout=6)
            return
        self.stt_test_btn.set_sensitive(False)
        self.stt_test_btn.set_label("● Listening 4s…")
        self.win._show_toast("Listening for 4 seconds — say something.", timeout=4)

        def _bg():
            text, err = stt.test_capture(4.0)

            def _show():
                self.stt_test_btn.set_sensitive(True)
                self.stt_test_btn.set_label("● Record 4s")
                if err:
                    self.win._show_toast(f"Mic test failed: {err}", timeout=8)
                    self.win.terminal_log(f"mic test FAILED: {err}", "error")
                elif text:
                    self.win._show_toast(f"Heard: “{text}”", timeout=8)
                    self.win.terminal_log(f"mic test OK: {text}", "ok")
                else:
                    self.win._show_toast(
                        "Recorded but transcript was empty — likely silence "
                        "or wrong input source.", timeout=8)
                    self.win.terminal_log("mic test: empty transcript", "error")
                return False
            GLib.idle_add(_show)
        threading.Thread(target=_bg, daemon=True).start()


# ═════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ═════════════════════════════════════════════════════════════════════

class MainWindow(Adw.ApplicationWindow):

    def __init__(self, app: "KaliApp"):
        super().__init__(application=app)
        self.set_title(APP_NAME)
        w, h = _default_window_size()
        self.set_default_size(w, h)
        self.app = app
        self.settings = load_settings()
        # Apply the inline-image toggle to the module global the renderer reads.
        global _RENDER_IMAGES
        try:
            _RENDER_IMAGES = bool(self.settings.get("chat_render_images", True))
        except Exception:
            _RENDER_IMAGES = True
        # Build one backend per registered cloud provider.  Groq keeps its
        # library-backed backend; everything else rides the generic
        # OpenAI-compatible backend.  Keyed by provider id for the router.
        self.cloud: Dict[str, Any] = {}
        for spec in PROVIDERS:
            key = self.settings.get(f"{spec.key}_api_key", "")
            if spec.engine == "groq":
                self.cloud[spec.key] = GroqBackend(key)
            else:
                self.cloud[spec.key] = OpenAICompatBackend(spec, key)
        # Back-compat alias used in a few spots.
        self.groq = self.cloud.get("groq")
        self.router = BackendRouter(self.cloud, self.settings)
        self.store = ChatStore()
        self.watcher = Watcher(self.settings, self._on_watcher_event)

        # ── kali_ext sidecar (optional) ──
        # Imports nothing from this app; depends only on stdlib + the two
        # callables handed to init().  If the package is missing or init
        # raises, self._ext stays None and every hook below no-ops, leaving
        # Kali identical to a stock build.  Nothing here starts a background
        # thread unless the matching setting is on.
        self._ext = None
        try:
            from kali_ext import extman as _extman
            _extman.init(settings=self.settings,
                         data_dir="~/.local/share/kali",
                         complete_fn=self._ext_complete,
                         embed_fn=None,
                         ledger=get_ledger())
            self._ext = _extman
        except Exception as _e:
            log(f"kali_ext not loaded: {_e}")

        self.current_chat_id: Optional[int] = None
        self.current_agent_mode = bool(self.settings.get("agent_mode_default",
                                                          True))
        self.streaming_thread: Optional[threading.Thread] = None
        self.streaming_cancel: Optional[threading.Event] = None
        self.streaming_msg_widget: Optional[MessageWidget] = None
        self.streaming_msg_db_id: Optional[int] = None
        # Chat the active streaming/tool turn belongs to.  Used so that
        # if the user navigates to a different chat mid-turn, tool results
        # and follow-up assistant messages still land in the chat that
        # started the turn — not whichever chat happens to be displayed
        # when the background work completes.
        self.streaming_chat_id: Optional[int] = None
        self._tool_chain_depth: int = 0
        # Set once per turn when the tool-step budget is exhausted: the next
        # turn ignores any tool calls and just answers, so we never dead-end.
        self._tools_locked: bool = False
        # Set when the operator hits the stop button.  Halts the current
        # stream AND prevents the tool chain from kicking another turn.
        self._stop_requested: bool = False

        # ── Voice (optional) ──
        # stt: tap-to-talk transcription via Groq Whisper.
        # tts: read assistant replies aloud (Piper or espeak).
        # streamer: turns the token stream into speakable sentences.
        self.stt = None
        self.tts = None
        self._tts_streamer = None
        self._recording = False
        self._tts_suspended = False    # true for a turn that's running tools
        # The assistant message whose audio is currently queued/playing,
        # so its per-message button reflects play/pause and switching to
        # another message stops this one.
        self._speaking_widget = None
        self._turn_active = False       # an assistant turn is mid-flight
        if _VOICE_OK:
            try:
                self.stt = kali_voice.SpeechToText(lambda: self.settings)
                self.tts = kali_voice.TextToSpeech(lambda: self.settings)
                self._tts_streamer = kali_voice.SpeechStreamer()
                self.tts.set_state_callback(
                    lambda st: GLib.idle_add(self._on_tts_state, st))
            except Exception as _e:
                log(f"voice init failed: {_e}")
                self.stt = None
                self.tts = None

        self._build_ui()
        self._wire_actions()
        self._boot()
        GLib.idle_add(self._initial_chat_load)
        GLib.idle_add(self._refresh_sidebar)

    def _initial_chat_load(self):
        """At launch: tidy up per the history policy, then either open a
        brand-new chat (the default) or resume the most recent one."""
        self._run_retention()
        if self.settings.get("ephemeral_new_chat_on_launch", True):
            self._new_chat()
            return False
        chats = self.store.list_chats(limit=1)
        if chats:
            self._load_chat(chats[0].id)
        else:
            self._new_chat()
        return False

    def _run_retention(self):
        """Apply the chat-history policy: drop chats idle past the
        retention window and abandoned empty placeholders.  Never removes
        the chat currently open, nor pinned chats."""
        keep = self.current_chat_id
        try:
            hours = float(self.settings.get("chat_retention_hours", 24) or 0)
        except (TypeError, ValueError):
            hours = 24.0
        removed = 0
        try:
            if hours > 0:
                removed += self.store.purge_old_chats(hours * 3600.0,
                                                      keep_chat_id=keep)
            if self.settings.get("discard_empty_chats", True):
                removed += self.store.purge_empty_chats(keep_chat_id=keep)
        except Exception as e:
            log(f"retention error: {e}")
        if removed:
            log(f"retention: removed {removed} chat(s)")
            self._refresh_sidebar()
        return removed

    def _periodic_retention(self):
        """Hourly sweep so a long-running session still honours the
        retention window (a startup-only purge would miss it)."""
        self._run_retention()
        return True   # keep the GLib timer alive

    # ── boot ────────────────────────────────────────────────────

    def _boot(self):
        def _bg():
            GLib.idle_add(self.update_status_pills)
            if self.settings.get("watcher_enabled"):
                self.watcher.start()
        threading.Thread(target=_bg, daemon=True).start()
        # Roll old chats hourly so a session left open for days still
        # honours the retention window.
        GLib.timeout_add_seconds(3600, self._periodic_retention)

    # ── UI construction ─────────────────────────────────────────

    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        self.split = Adw.OverlaySplitView()
        self.split.set_min_sidebar_width(280)
        self.split.set_max_sidebar_width(360)
        self.split.set_sidebar_width_fraction(0.28)
        self.toast_overlay.set_child(self.split)

        self.split.set_sidebar(self._build_sidebar())
        self.split.set_content(self._build_main())

        # On narrow screens (phones, split-view tablets) the 280-360 px
        # sidebar eats the whole window, leaving no room for the chat
        # area.  Collapse it so the sidebar overlays content instead of
        # pushing it aside.  Two paths: a libadwaita Breakpoint when
        # available (reactive to resize), and a static fallback gated
        # on actual screen width when Breakpoint isn't supported.
        try:
            bp = Adw.Breakpoint.new(
                Adw.BreakpointCondition.parse("max-width: 820px"))
            bp.add_setter(self.split, "collapsed", True)
            self.add_breakpoint(bp)
        except Exception as e:
            log(f"breakpoint unavailable, using static collapse: {e}")
            # Detect narrow screen via Gdk directly so we don't depend on
            # UI scale (which is about font sizes, not screen geometry).
            # Use LOGICAL width (device width / scale factor) so a phone that
            # reports raw device pixels (e.g. 1080) still collapses correctly.
            try:
                display = Gdk.Display.get_default()
                mon = display.get_monitors().get_item(0) if display else None
                if mon:
                    geo = mon.get_geometry()
                    sf = mon.get_scale_factor() or 1
                    logical_w = geo.width / sf if sf > 0 else geo.width
                    if logical_w < 820 or geo.width < 820:
                        self.split.set_collapsed(True)
            except Exception:
                pass

    def _build_sidebar(self):
        sb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sb.add_css_class("sidebar")

        # Header
        sb_header = Adw.HeaderBar()
        sb_header.set_show_end_title_buttons(False)
        sb_header.set_show_start_title_buttons(False)

        # Header — KALI (with a live online dot) on the left, new-chat on the
        # right.  The dot is green when online, red when offline.
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        t = Gtk.Label(label=APP_NAME.upper(), xalign=0.0)
        t.add_css_class("app-title")
        t.set_valign(Gtk.Align.CENTER)
        title_box.append(t)
        self.online_dot = Gtk.Label(label="●")
        self.online_dot.add_css_class("online-dot")
        self.online_dot.set_valign(Gtk.Align.CENTER)
        self.online_dot.set_tooltip_text("Connectivity")
        title_box.append(self.online_dot)
        sb_header.pack_start(title_box)

        new_btn = Gtk.Button.new_from_icon_name("document-new-symbolic")
        new_btn.set_tooltip_text("New chat")
        new_btn.add_css_class("header-icon-button")
        new_btn.connect("clicked", lambda *_: self._new_chat())
        sb_header.pack_end(new_btn)
        sb.append(sb_header)

        # (Chat search removed by request.)

        # List
        self.chat_listbox = Gtk.ListBox()
        self.chat_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.chat_listbox.connect("row-activated", self._on_chat_selected)

        gc = Gtk.GestureClick()
        gc.set_button(3)
        gc.connect("pressed", self._on_chat_rightclick)
        self.chat_listbox.add_controller(gc)
        lp = Gtk.GestureLongPress()
        lp.connect("pressed", self._on_chat_longpress)
        self.chat_listbox.add_controller(lp)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        sw.set_child(self.chat_listbox)
        sb.append(sw)
        return sb

    def _build_main(self):
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header
        hb = Adw.HeaderBar()
        sb_toggle = Gtk.Button.new_from_icon_name("sidebar-show-symbolic")
        sb_toggle.add_css_class("header-icon-button")
        sb_toggle.set_tooltip_text("Toggle sidebar")
        sb_toggle.connect("clicked", lambda *_:
                          self.split.set_show_sidebar(
                              not self.split.get_show_sidebar()))
        hb.pack_start(sb_toggle)

        self.title_widget_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                         spacing=0)
        self.chat_title_lbl = Gtk.Label(label="New chat", xalign=0.5)
        self.chat_title_lbl.add_css_class("chat-title")
        # Subtitle label kept for code that references it, but never shown.
        self.chat_subtitle_lbl = Gtk.Label(label="", xalign=0.5)
        self.chat_subtitle_lbl.add_css_class("chat-subtitle")
        self.title_widget_box.append(self.chat_title_lbl)
        hb.set_title_widget(self.title_widget_box)

        # (Provider + online status used to live here as pills; the operator
        # knows their provider, so that's gone — connectivity is now just the
        # green/red dot next to KALI in the sidebar header.)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.add_css_class("icon-button")
        menu = Gio.Menu()
        menu.append("Pin chat", "win.pin-chat")
        menu.append("Rename chat", "win.rename-chat")
        menu.append("Delete chat", "win.delete-chat")
        menu.append("Settings", "win.settings")
        menu.append("About", "win.about")
        menu_btn.set_menu_model(menu)
        hb.pack_end(menu_btn)

        main.append(hb)

        # Watcher event banner
        self.banner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                   spacing=0)
        main.append(self.banner_box)

        # "Working..." status row, shown while assistant is generating or
        # a tool is running.  Hidden by default.
        self.working_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                    spacing=12)
        self.working_row.add_css_class("working-row")
        self.working_row.set_halign(Gtk.Align.CENTER)
        self.working_row.set_margin_top(8)
        self.working_row.set_margin_bottom(8)
        self.working_spinner = Gtk.Spinner()
        self.working_spinner.add_css_class("working-spinner")
        self.working_label = Gtk.Label(label="working…")
        self.working_label.add_css_class("working-label")
        self.working_row.append(self.working_spinner)
        self.working_row.append(self.working_label)
        self.working_row.set_visible(False)
        main.append(self.working_row)

        # Messages
        self.msg_scroll = Gtk.ScrolledWindow()
        self.msg_scroll.set_policy(Gtk.PolicyType.NEVER,
                                    Gtk.PolicyType.AUTOMATIC)
        self.msg_scroll.set_vexpand(True)
        # Force kinetic (swipe) scrolling — needed for phone touch input
        self.msg_scroll.set_kinetic_scrolling(True)
        self.msg_scroll.set_overlay_scrolling(True)
        self.msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.msg_box.set_margin_top(12)
        self.msg_box.set_margin_bottom(12)
        self.msg_box.set_margin_start(8)
        self.msg_box.set_margin_end(8)
        self.msg_scroll.set_child(self.msg_box)
        self.msg_scroll.add_css_class("chat-scroll")

        # A faint menacing-penguin watermark sits BEHIND the conversation.
        # Gtk.Overlay draws its main child at the back and overlays on top, so
        # the watermark is the main child and the (transparent) scroller is the
        # overlay — messages render over the penguin.  Falls back to just the
        # scroller if the watermark SVG isn't on disk.
        wm = self._build_chat_watermark()
        if wm is not None:
            chat_overlay = Gtk.Overlay()
            chat_overlay.set_vexpand(True)
            chat_overlay.set_child(wm)
            chat_overlay.add_overlay(self.msg_scroll)
            main.append(chat_overlay)
        else:
            main.append(self.msg_scroll)

        main.append(self._build_input_area())

        # Terminal log panel — hidden by default, shown when user taps the log button
        self._terminal_visible = False
        self.terminal_panel = self._build_terminal_panel()
        self.terminal_panel.set_visible(False)
        main.append(self.terminal_panel)

        return main

    def _build_chat_watermark(self):
        """A large, faint dragon watermark for behind the chat.  Loads either a
        PNG (the dragon emblem, already alpha-baked) or an SVG.  Non-interactive
        (never grabs touch/clicks), scaled to fit, low opacity so it sets the
        mood without fighting the text.  Returns None if the art isn't on disk."""
        path = _WATERMARK_SVG_PATH
        if not path:
            return None
        try:
            if path.lower().endswith(".png"):
                tex = None
                try:
                    tex = Gdk.Texture.new_from_filename(path)
                except Exception:
                    from gi.repository import Gio
                    tex = Gdk.Texture.new_from_file(Gio.File.new_for_path(path))
                opacity = 0.6          # PNG alpha is pre-baked subtle
            else:
                tex = _svg_texture(path, 720)
                opacity = 0.09
            if tex is None:
                return None
            pic = Gtk.Picture.new_for_paintable(tex)
            pic.set_can_target(False)
            pic.set_hexpand(True)
            pic.set_vexpand(True)
            pic.set_halign(Gtk.Align.FILL)
            pic.set_valign(Gtk.Align.FILL)
            pic.set_opacity(opacity)
            try:
                pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            except Exception:
                pass
            pic.add_css_class("chat-watermark")
            return pic
        except Exception as e:
            log(f"watermark build failed: {e}")
            return None

    def _build_terminal_panel(self):
        """Live terminal output panel — shows exactly what tools are doing."""
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panel.add_css_class("terminal-panel")
        panel.set_size_request(-1, _scaled(220, floor=140))

        # Header row
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("terminal-panel-header")

        title_lbl = Gtk.Label(label="▶ TERMINAL LOG", xalign=0.0)
        title_lbl.add_css_class("terminal-panel-title")
        title_lbl.set_hexpand(True)
        header.append(title_lbl)

        self.terminal_status_lbl = Gtk.Label(label="idle", xalign=1.0)
        self.terminal_status_lbl.add_css_class("tool-indicator-label")
        header.append(self.terminal_status_lbl)

        clear_btn = Gtk.Button(label="clear")
        clear_btn.add_css_class("terminal-toggle-btn")
        clear_btn.connect("clicked", self._clear_terminal_log)
        header.append(clear_btn)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("icon-button")
        close_btn.connect("clicked", self._toggle_terminal_panel)
        header.append(close_btn)

        panel.append(header)

        # Log view
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        sw.set_kinetic_scrolling(True)

        self.terminal_log_view = Gtk.TextView()
        self.terminal_log_view.set_editable(False)
        self.terminal_log_view.set_cursor_visible(False)
        self.terminal_log_view.set_monospace(True)
        self.terminal_log_view.set_wrap_mode(Gtk.WrapMode.CHAR)
        self.terminal_log_view.add_css_class("terminal-log-view")
        self.terminal_log_buf = self.terminal_log_view.get_buffer()

        # Colour tags
        self.terminal_log_buf.create_tag("cmd",    foreground="#2ee65f", weight=700)
        self.terminal_log_buf.create_tag("stdout", foreground="#9aa3ad")
        self.terminal_log_buf.create_tag("stderr", foreground="#e5484d")
        self.terminal_log_buf.create_tag("info",   foreground="#2ee65f")
        self.terminal_log_buf.create_tag("error",  foreground="#e5484d", weight=700)
        self.terminal_log_buf.create_tag("ok",     foreground="#2ee65f", weight=700)
        self.terminal_log_buf.create_tag("dim",    foreground="#7d8794")

        sw.set_child(self.terminal_log_view)
        panel.append(sw)
        return panel

    def _model_button_label(self) -> str:
        key = self.settings.get("active_provider", "siliconflow")
        spec = PROVIDERS_BY_KEY.get(key)
        plabel = spec.label if spec else key
        model = self.settings.get(
            f"{key}_model", spec.default_model if spec else "")
        short = model.split("/")[-1] if "/" in model else model
        return f"⮂  {plabel}  ·  {short or 'pick a model'}"

    def _update_model_button(self):
        btn = getattr(self, "model_btn", None)
        if btn is not None:
            btn.set_label(self._model_button_label())

    def _provider_has_key(self, key: str) -> bool:
        return bool((self.settings.get(f"{key}_api_key", "") or "").strip())

    def _models_priced_high_to_low(self, spec):
        """Order a provider's models most-expensive (biggest) -> cheapest.
        Bigger parameter counts cost more, so sort by the largest 'NNb' / 'NNB'
        number in the model id, descending; ties keep the curated chain order."""
        import re as _re
        def size_of(m):
            nums = _re.findall(r"(\d+(?:\.\d+)?)\s*[bB]\b", m)
            return max((float(n) for n in nums), default=0.0)
        ordered = sorted(
            list(enumerate(spec.chain)),
            key=lambda im: (-size_of(im[1]), im[0]))
        return [m for _i, m in ordered]

    def _open_model_switcher(self, *_):
        pop = Gtk.Popover()
        pop.set_parent(self.model_btn)
        pop.add_css_class("model-switch-pop")
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.set_margin_top(8)
        outer.set_margin_bottom(8)
        outer.set_margin_start(8)
        outer.set_margin_end(8)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_max_content_height(440)
        sw.set_min_content_width(240)
        sw.set_propagate_natural_height(True)
        listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        cur_key = self.settings.get("active_provider", "siliconflow")
        cur_model = self.settings.get(f"{cur_key}_model", "")
        any_provider = False
        for spec in PROVIDERS:
            if not self._provider_has_key(spec.key):
                continue
            any_provider = True
            hdr = Gtk.Label(label=spec.label.upper(), xalign=0.0)
            hdr.add_css_class("model-group-header")
            listbox.append(hdr)
            for model in self._models_priced_high_to_low(spec):
                short = model.split("/")[-1] if "/" in model else model
                b = Gtk.Button(label=short)
                b.add_css_class("model-pick-row")
                b.set_halign(Gtk.Align.FILL)
                if spec.key == cur_key and model == cur_model:
                    b.add_css_class("model-pick-active")
                b.connect("clicked",
                          lambda _w, k=spec.key, m=model: self._switch_model(
                              k, m, pop))
                listbox.append(b)

        if not any_provider:
            hint = Gtk.Label(
                label="No API keys yet.\nAdd one in Settings → Providers.",
                xalign=0.0)
            hint.add_css_class("model-group-header")
            listbox.append(hint)

        sw.set_child(listbox)
        outer.append(sw)
        pop.set_child(outer)
        pop.connect("closed", lambda p: p.unparent())
        pop.popup()

    def _switch_model(self, provider, model, pop=None):
        self.settings["active_provider"] = provider
        self.settings[f"{provider}_model"] = model
        save_settings(self.settings)
        self._update_model_button()
        self.update_status_pills()
        spec = PROVIDERS_BY_KEY.get(provider)
        short = model.split("/")[-1] if "/" in model else model
        self._show_toast(f"Now using {spec.label if spec else provider} · {short}")
        if pop is not None:
            pop.popdown()

    def _build_input_area(self):
        area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        area.add_css_class("input-area")

        # Model switcher — shows the active provider · model, click to switch
        # to any model on any provider you hold a key for, on the fly.
        model_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        model_bar.set_margin_start(4)
        model_bar.set_margin_end(4)
        self.model_btn = Gtk.Button()
        self.model_btn.add_css_class("model-switch-btn")
        self.model_btn.set_halign(Gtk.Align.START)
        self.model_btn.set_tooltip_text("Switch model / provider")
        self.model_btn.connect("clicked", self._open_model_switcher)
        self._update_model_button()
        model_bar.append(self.model_btn)
        area.append(model_bar)

        # Action chips
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        actions.set_margin_start(4)
        actions.set_margin_end(4)

        self.agent_toggle = Gtk.ToggleButton()
        self.agent_toggle.set_icon_name("applications-system-symbolic")
        self.agent_toggle.add_css_class("icon-button")
        self.agent_toggle.set_tooltip_text("Agent mode (system tools)")
        self.agent_toggle.set_active(self.current_agent_mode)
        if self.current_agent_mode:
            self.agent_toggle.add_css_class("toggled")
        self.agent_toggle.connect("toggled", self._on_agent_toggled)
        actions.append(self.agent_toggle)

        for icon, tip, cb in [
            ("security-high-symbolic", "Audit security",
             self._user_action_audit),
            ("network-wireless-symbolic", "Scan network",
             self._user_action_scan),
            ("system-software-update-symbolic", "Check for updates",
             self._user_action_updates),
            ("folder-download-symbolic", "Recent downloads",
             self._user_action_downloads),
            ("computer-symbolic", "System info",
             self._user_action_sysinfo),
            ("mail-attachment-symbolic", "Attach file",
             self._pick_attachment),
            ("camera-photo-symbolic", "Take a photo (Kali can see it)",
             self._user_action_camera),
        ]:
            btn = Gtk.Button.new_from_icon_name(icon)
            btn.add_css_class("icon-button")
            btn.set_tooltip_text(tip)
            btn.connect("clicked", lambda *_, c=cb: c())
            actions.append(btn)

        # Speaker toggle — read assistant replies aloud.  Only shown when
        # a TTS engine is actually available on the box.
        self.tts_toggle = None
        if self.tts is not None and self.tts.available():
            self.tts_toggle = Gtk.ToggleButton()
            self.tts_toggle.set_icon_name("audio-volume-high-symbolic")
            self.tts_toggle.add_css_class("icon-button")
            self.tts_toggle.set_tooltip_text(
                f"Read replies aloud — {self.tts.engine_name()}")
            on = bool(self.settings.get("tts_enabled"))
            self.tts_toggle.set_active(on)
            if on:
                self.tts_toggle.add_css_class("toggled")
            self.tts_toggle.connect("toggled", self._on_tts_toggled)
            actions.append(self.tts_toggle)

        # Log toggle sits right alongside the other toolbar buttons.
        self.terminal_toggle_btn = Gtk.Button.new_from_icon_name(
            "utilities-terminal-symbolic")
        self.terminal_toggle_btn.add_css_class("icon-button")
        self.terminal_toggle_btn.set_tooltip_text("Show/hide live terminal log")
        self.terminal_toggle_btn.connect("clicked", self._toggle_terminal_panel)
        actions.append(self.terminal_toggle_btn)

        # The chips live in a horizontal scroller so a phone too narrow to fit
        # them all can't be forced wider than the screen — they scroll instead.
        actions.set_margin_start(0)
        actions.set_margin_end(0)
        chips_scroll = Gtk.ScrolledWindow()
        chips_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        chips_scroll.set_hexpand(True)
        chips_scroll.set_propagate_natural_height(True)
        chips_scroll.set_kinetic_scrolling(True)
        chips_scroll.set_overlay_scrolling(True)
        chips_scroll.add_css_class("chips-scroll")
        chips_scroll.set_child(actions)

        actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        actions_row.set_margin_start(4)
        actions_row.set_margin_end(4)
        actions_row.append(chips_scroll)

        area.append(actions_row)

        # Input
        ibox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ibox.add_css_class("input-frame")
        ibox.set_margin_start(4)
        ibox.set_margin_end(4)

        in_scroll = Gtk.ScrolledWindow()
        in_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        in_scroll.set_min_content_height(_scaled(88, floor=64))
        in_scroll.set_max_content_height(_scaled(300, floor=170))
        in_scroll.set_propagate_natural_height(True)
        in_scroll.set_hexpand(True)

        self.input_view = Gtk.TextView()
        self.input_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.input_view.set_top_margin(10)
        self.input_view.set_bottom_margin(10)
        self.input_view.set_left_margin(4)
        self.input_view.set_right_margin(4)
        in_scroll.set_child(self.input_view)
        ibox.append(in_scroll)

        kc = Gtk.EventControllerKey()
        kc.connect("key-pressed", self._on_input_key)
        self.input_view.add_controller(kc)

        # (Mic / speech-to-text button removed — the composer leads with a
        # single big Send button instead.)
        self.mic_btn = None

        # Big Send button wearing the dragon logo.  It glows while Kali is
        # working (a tap then stops her) rather than turning into a stop icon.
        self.send_btn = Gtk.Button()
        self.send_btn.add_css_class("send-button")
        self.send_btn.set_valign(Gtk.Align.END)
        self.send_btn.set_tooltip_text("Send")
        if _AVATAR_PNG_PATH:
            _send_img = Gtk.Image.new_from_file(_AVATAR_PNG_PATH)
            _send_img.set_pixel_size(_scaled(40, floor=30))
            self.send_btn.set_child(_send_img)
        else:
            self.send_btn.set_icon_name("send-to-symbolic")
        self.send_btn.connect("clicked", lambda *_: self._on_send_or_stop())
        ibox.append(self.send_btn)

        area.append(ibox)
        return area

    # ── actions ────────────────────────────────────────────────

    def _wire_actions(self):
        def add(name, cb):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_: cb())
            self.add_action(a)
        add("settings", self._open_settings)
        add("about", self._open_about)
        add("rename-chat", self._rename_current_chat)
        add("delete-chat", self._delete_current_chat)
        add("pin-chat", self._toggle_pin_current)
        GLib.timeout_add_seconds(10, self._poll_status)
        self._poll_status()

    def _poll_status(self):
        def _bg():
            on = is_online(timeout=0.8)
            GLib.idle_add(self.update_status_pills, on)
        threading.Thread(target=_bg, daemon=True).start()
        return True

    def update_status_pills(self, online: Optional[bool] = None):
        # Connectivity is now a single green/red dot next to KALI in the
        # sidebar header (the old provider/online pills were removed).
        if online is None:
            online = is_online(max_age=15)
        dot = getattr(self, "online_dot", None)
        if dot is None:
            return False
        if online:
            dot.remove_css_class("offline")
            dot.add_css_class("online")
            dot.set_tooltip_text("Online")
        else:
            dot.remove_css_class("online")
            dot.add_css_class("offline")
            dot.set_tooltip_text("Offline")
        return False

    # ── chat list ───────────────────────────────────────────────

    def _refresh_sidebar(self, query: str = ""):
        child = self.chat_listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.chat_listbox.remove(child)
            child = nxt

        chats = self.store.list_chats()
        if query:
            ql = query.lower()
            chats = [c for c in chats if ql in c.title.lower()]
        if not chats:
            empty = Gtk.Label(
                label="No matches." if query else "No chats yet.")
            empty.add_css_class("empty-state")
            self.chat_listbox.append(empty)
            return False
        for c in chats:
            row = ChatRow(c)
            self.chat_listbox.append(row)
            if c.id == self.current_chat_id:
                self.chat_listbox.select_row(row)
        return False

    def _on_search(self, entry):
        self._refresh_sidebar(entry.get_text().strip())

    def _on_chat_selected(self, _lb, row):
        if isinstance(row, ChatRow) and row.chat.id != self.current_chat_id:
            self._load_chat(row.chat.id)

    def _on_chat_rightclick(self, gesture, n_press, x, y):
        row = self.chat_listbox.get_row_at_y(int(y))
        if isinstance(row, ChatRow):
            self.chat_listbox.select_row(row)
            self._load_chat(row.chat.id)
            self._show_chat_context_menu(row, x, y)

    def _on_chat_longpress(self, gesture, x, y):
        row = self.chat_listbox.get_row_at_y(int(y))
        if isinstance(row, ChatRow):
            self.chat_listbox.select_row(row)
            self._load_chat(row.chat.id)
            self._show_chat_context_menu(row, x, y)

    def _show_chat_context_menu(self, row, x, y):
        menu = Gio.Menu()
        menu.append("Pin / unpin", "win.pin-chat")
        menu.append("Rename", "win.rename-chat")
        menu.append("Delete", "win.delete-chat")
        popover = Gtk.PopoverMenu.new_from_model(menu)
        # The gesture coords (x, y) are relative to the LISTBOX, so the popover
        # must be parented to the listbox for them to line up — parenting to the
        # row (its own coordinate space) is what made it appear at a random spot.
        popover.set_parent(self.chat_listbox)
        popover.set_has_arrow(False)
        popover.add_css_class("context-menu")
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        # Unparent when dismissed so it doesn't leak / warn.
        popover.connect("closed", lambda p: p.unparent())
        popover.popup()

    # ── chat load / new ─────────────────────────────────────────

    def _new_chat(self):
        # Don't leave an unused 'New chat' behind when starting another.
        if (self.settings.get("discard_empty_chats", True)
                and self.current_chat_id is not None):
            try:
                if self.store.count_messages(self.current_chat_id) == 0:
                    self.store.delete_chat(self.current_chat_id)
            except Exception:
                pass
        backend, model = self.router.pick()
        cid = self.store.create_chat(
            title="New chat", model=model,
            agent_mode=self.settings.get("agent_mode_default", True))
        self._load_chat(cid)
        self._refresh_sidebar()
        return False

    def _load_chat(self, chat_id: int):
        self.current_chat_id = chat_id
        chat = self.store.get_chat(chat_id)
        if not chat:
            return
        self.current_agent_mode = bool(chat.agent_mode)
        self.agent_toggle.set_active(self.current_agent_mode)
        if self.current_agent_mode:
            self.agent_toggle.add_css_class("toggled")
        else:
            self.agent_toggle.remove_css_class("toggled")
        self.chat_title_lbl.set_text(chat.title)
        self._refresh_subtitle()

        child = self.msg_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.msg_box.remove(child)
            child = nxt

        msgs = self.store.list_messages(chat_id)
        if not msgs:
            self._show_empty_state()
        else:
            for m in msgs:
                kind = (m.meta or {}).get("kind")
                # Skip stored tool-result rows entirely; the assistant's
                # follow-up message already conveys their content.
                if kind == "tool_result":
                    continue
                # Skip tool 'call' indicators (⚙ tool: …).  The user wants
                # these hidden — the spinner banner tells them work is
                # happening, and the assistant's follow-up describes what.
                if m.role == "tool":
                    continue
                # Skip empty assistant placeholders — these are pre-allocated
                # DB rows for in-flight streams.  Rendering them produces an
                # empty bubble; the real content arrives when the stream
                # completes and updates this row.
                if m.role == "assistant" and not m.content.strip():
                    continue
                self._append_message_widget(m.role, m.content, m.meta)

        GLib.idle_add(self._force_scroll_to_bottom)

    def _show_empty_state(self):
        # Intentionally blank: a new chat just shows the dragon watermark.
        # No greeting text, no suggestion chips (those actions live in the
        # composer toolbar already).
        return

    def _refresh_subtitle(self):
        # Model + agent indicator removed from the header by request: the model
        # is visible in the composer switcher, and agent state shows as the
        # green-lit toggle.  Keep the label empty so the header stays slim.
        if hasattr(self, "chat_subtitle_lbl") and self.chat_subtitle_lbl:
            self.chat_subtitle_lbl.set_text("")

    # ── messages ────────────────────────────────────────────────

    def _append_message_widget(self, role, content, meta=None):
        # Clear empty state if present
        first = self.msg_box.get_first_child()
        if first is not None and not isinstance(first, MessageWidget):
            self.msg_box.remove(first)
        w = MessageWidget(role, content, meta,
                          on_run_command=self._run_proposed_command,
                          on_apply_edit=self._run_proposed_edit,
                          on_speak=self._on_message_speak,
                          show_thoughts=self.settings.get("show_thoughts", True))
        self.msg_box.append(w)
        # New message → force scroll.  This is when the user sent something
        # or a new assistant turn started; they want to see it.  Mid-stream
        # token updates use the smart _scroll_to_bottom that respects
        # the user reading history above.
        GLib.idle_add(self._force_scroll_to_bottom)
        return w

    def _scroll_to_bottom(self):
        adj = self.msg_scroll.get_vadjustment()
        if adj is None:
            return False
        # If the user has scrolled UP to read earlier messages, don't
        # yank them back to the bottom on every token.  Only follow if
        # they're already within ~120 px of the bottom.
        at_bottom = (adj.get_value() + adj.get_page_size()
                     >= adj.get_upper() - 120)
        if at_bottom:
            adj.set_value(adj.get_upper())
        return False

    def _force_scroll_to_bottom(self):
        """Unconditional scroll — used when sending a NEW user message
        or loading a chat, where the user expects to see the latest."""
        adj = self.msg_scroll.get_vadjustment()
        if adj is not None:
            adj.set_value(adj.get_upper())
        return False

    # ── sending ─────────────────────────────────────────────────

    def _on_input_key(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
            if not shift:
                self._send_user_message()
                return True
        # Escape stops Kali mid-reply.
        if keyval == Gdk.KEY_Escape and self._is_busy():
            self._request_stop()
            return True
        return False

    def _on_send_or_stop(self):
        """The primary button is Send when idle, Stop when Kali is working."""
        if self._is_busy():
            self._request_stop()
        else:
            self._send_user_message()

    def _set_send_mode(self, working: bool):
        """Keep the dragon logo at all times.  While Kali is working the button
        GLOWS (and a tap stops her); idle, it's the normal Send button."""
        if working:
            self.send_btn.set_tooltip_text("Working… tap to stop")
            self.send_btn.add_css_class("working")
        else:
            self.send_btn.set_tooltip_text("Send")
            self.send_btn.remove_css_class("working")
        self.send_btn.set_sensitive(True)

    def _request_stop(self):
        """Operator pressed Stop.  Cancel the in-flight stream and make
        sure the tool chain doesn't kick another turn behind our back."""
        self._stop_requested = True
        if self.streaming_cancel:
            self.streaming_cancel.set()
        if self.tts:
            self.tts.stop()
        self._show_toast("Stopping…")
        # If a stream is live, the backend will fire on_done({cancelled})
        # and _on_stream_done tears everything down.  If we're between
        # tool turns (no live stream), tear down here so we don't hang.
        if not (self.streaming_thread and self.streaming_thread.is_alive()):
            self._finish_turn_cleanup(mark_partial=True)

    def _finish_turn_cleanup(self, mark_partial: bool = False):
        """Single teardown path for the end of an assistant turn —
        whether it finished, errored, or was stopped."""
        if mark_partial and self.streaming_msg_widget is not None:
            partial = (self.streaming_msg_widget._content or "").strip()
            final_text = partial if partial else "_(stopped)_"
            try:
                self.streaming_msg_widget.set_content(final_text)
            except Exception:
                pass
            if self.streaming_msg_db_id:
                self.store.update_message(self.streaming_msg_db_id, final_text)
        self.streaming_msg_widget = None
        self.streaming_msg_db_id = None
        self.streaming_chat_id = None
        self._tool_chain_depth = 0
        self._tools_locked = False
        self._turn_active = False
        self._set_working(False)
        self._set_send_mode(False)

    def _send_user_message(self):
        if self._is_busy():
            self._show_toast("Already replying — hit stop first.")
            return
        # Fresh turn — clear any leftover stop flag.
        self._stop_requested = False
        # Fresh turn — reset the guard that stops a malformed propose/edit
        # from being bounced back to the model forever.
        self._bad_propose_retries = 0
        buf = self.input_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(),
                            False).strip()
        if not text:
            return
        buf.set_text("")

        # (#3) /panic — jump straight to tool-first triage: no preamble, run
        # a batched health-check sweep, report what's abnormal.  Expands into
        # a directive the model acts on (the read-only checks batch into one
        # round-trip via the parallel executor).
        if text.lower().split() and text.lower().split()[0] in ("/panic",):
            text = ("[PANIC MODE] Fast triage — skip ALL preamble and "
                    "questions. In ONE turn, fire these read-only checks "
                    "together: quick_facts, system_info, disk_usage, "
                    "processes, network_status, service_status, and "
                    "journal_tail (recent errors). Then give a tight bullet "
                    "summary of anything abnormal and the single most likely "
                    "problem. Look first, report second.")
            self._show_toast("Panic mode — running health sweep.", timeout=4)

        # A new message means stop reading the previous reply out loud.
        if self.tts:
            self.tts.stop()

        if self.current_chat_id is None:
            self._new_chat()
        cid = self.current_chat_id
        self.store.add_message(cid, "user", text)
        self._append_message_widget("user", text)
        self._maybe_set_title_from_first(cid, text)

        self._kick_assistant_turn()

    # ── voice (speech in / speech out) ──────────────────────────

    def _on_tts_toggled(self, btn):
        on = btn.get_active()
        self.settings["tts_enabled"] = on
        save_settings(self.settings)
        if on:
            btn.add_css_class("toggled")
        else:
            btn.remove_css_class("toggled")
            # Turning it off should also shut it up right now.
            if self.tts:
                self.tts.stop()

    # ── per-message playback (play / pause / resume / replay) ──
    def _on_message_speak(self, widget):
        """The speaker button on a single assistant message was tapped."""
        if not (self.tts and self.tts.available()):
            self._show_toast(
                "No voice engine — set one up in Settings → Voice.", timeout=5)
            return
        content = (getattr(widget, "_content", "") or "").strip()
        if not content:
            self._show_toast("Nothing to read yet.")
            return
        if widget is self._speaking_widget:
            # Toggle this message's playback.
            if self.tts.is_paused():
                self.tts.resume()
            elif self.tts.is_speaking():
                self.tts.pause()
            else:
                # Finished already — replay from the top.
                self._start_speaking_widget(widget)
            return
        # A different message — take over.
        self._start_speaking_widget(widget)

    def _start_speaking_widget(self, widget):
        prev = self._speaking_widget
        if prev is not None and prev is not widget:
            prev.set_speak_state("idle")
        # Manual playback shouldn't be re-read by the streamer.
        self._turn_active = False
        self.tts.stop()
        self._speaking_widget = widget
        widget.set_speak_state("speaking")
        self.tts.speak_all(getattr(widget, "_content", "") or "")

    def _on_tts_state(self, state):
        """Driven from the TTS worker (marshalled here): keep the owning
        message's button in sync with what the speaker is doing."""
        w = self._speaking_widget
        if state == "idle":
            # Ignore a stale idle: either the speaker is busy again, or
            # we're still streaming a live reply that will queue more.
            if self.tts and self.tts.is_speaking():
                return False
            if self._turn_active and w is self.streaming_msg_widget:
                return False
            if w is not None:
                w.set_speak_state("idle")
            self._speaking_widget = None
        elif state == "speaking":
            if w is not None:
                w.set_speak_state("speaking")
        elif state == "paused":
            if w is not None:
                w.set_speak_state("paused")
        return False

    def _set_mic_visual(self, state: str):
        """state: 'idle' | 'recording' | 'busy'."""
        if not self.mic_btn:
            return
        self.mic_btn.remove_css_class("mic-recording")
        if state == "recording":
            self.mic_btn.set_icon_name("media-playback-stop-symbolic")
            self.mic_btn.add_css_class("mic-recording")
            self.mic_btn.set_tooltip_text("Listening… tap to stop & send")
            self.mic_btn.set_sensitive(True)
        elif state == "busy":
            self.mic_btn.set_icon_name("content-loading-symbolic")
            self.mic_btn.set_tooltip_text("Transcribing…")
            self.mic_btn.set_sensitive(False)
        else:  # idle
            self.mic_btn.set_icon_name("audio-input-microphone-symbolic")
            self.mic_btn.set_tooltip_text("Speak (tap to start, tap to send)")
            self.mic_btn.set_sensitive(True)

    def _on_mic_clicked(self):
        if not self.stt:
            return
        # Already recording → stop and transcribe.
        if self._recording:
            self._recording = False
            self._set_mic_visual("busy")
            threading.Thread(target=self._transcribe_worker,
                             daemon=True).start()
            return

        # Not recording → check we can, then start.
        reason = self.stt.unavailable_reason()
        if reason:
            self._show_toast(reason, timeout=5)
            return
        # Don't let Kali talk over the operator.
        if self.tts:
            self.tts.stop()
        if self.stt.start():
            self._recording = True
            self._set_mic_visual("recording")
        else:
            why = self.stt.last_error()
            self._show_toast(
                f"Couldn't start the microphone — {why}." if why
                else "Couldn't start the microphone.", timeout=5)

    def _transcribe_worker(self):
        """Runs off the UI thread: stop the recorder, send to Groq, hand
        the result back to the UI thread."""
        wav = self.stt.stop()
        if not wav:
            reason = self.stt.last_error()
            probe = self.stt.probe_inputs()
            if reason:
                msg = f"No audio — {reason}"
                if not probe:
                    msg += " (no mic visible to PipeWire/PulseAudio)"
            elif probe:
                msg = f"No audio captured. Inputs seen: {probe}"
            else:
                msg = ("No audio — no mic visible to PipeWire/PulseAudio. "
                       "Check it's plugged in and unmuted.")
            GLib.idle_add(self._apply_transcript, "", msg)
            return
        text, err = self.stt.transcribe(wav)
        GLib.idle_add(self._apply_transcript, text, err)

    def _apply_transcript(self, text: str, err: Optional[str]):
        self._set_mic_visual("idle")
        if err:
            self._show_toast(err, timeout=5)
            return
        if not text:
            self._show_toast("Didn't catch that — try again.")
            return
        buf = self.input_view.get_buffer()
        existing = buf.get_text(buf.get_start_iter(),
                                buf.get_end_iter(), False)
        # Append to whatever's already typed rather than clobbering it.
        if existing.strip():
            buf.set_text((existing.rstrip() + " " + text).strip())
        else:
            buf.set_text(text)
        if self.settings.get("voice_autosend", True):
            self._send_user_message()
        else:
            self.input_view.grab_focus()
        return False

    def _set_working(self, working: bool, label: str = "working…"):
        """Show or hide the 'working' spinner banner.  Called from the
        UI thread."""
        if working:
            self.working_label.set_text(label)
            self.working_spinner.start()
            self.working_row.set_visible(True)
            self.terminal_log(f"── {label}", "dim")
        else:
            self.working_spinner.stop()
            self.working_row.set_visible(False)

    # Friendly present-tense phrases for the working banner, so a tool chain
    # reads "searching the web… → reading a page… → cross-checking sources…"
    # instead of a bare tool name or a flat "working…".
    _TOOL_STATUS = {
        "web_search":       "searching the web",
        "image_search":     "finding images",
        "analyze_image":    "looking at the image",
        "capture_photo":    "taking a photo",
        "detect_faces":     "finding faces",
        "web_read":         "reading a page",
        "web_verify":       "cross-checking sources",
        "github":           "browsing GitHub",
        "osint_username":   "checking public profiles",
        "osint_lookup":     "checking public profiles",
        "social_read":      "reading a profile",
        "tooling_check":    "checking installed tools",
        "pentest_plan":     "planning recon",
        "cve_lookup":       "looking up CVEs",
        "parse_output":     "parsing scan output",
        "methodology":      "pulling up methodology",
        "wordlist_find":    "finding wordlists",
        "cheatsheet":       "pulling up syntax",
        "report_findings":  "building the report",
        "nuclei_template":  "writing a nuclei template",
        "reflect_findings": "double-checking the findings",
        "read_file":        "reading a file",
        "write_file":       "writing a file",
        "list_dir":         "listing files",
        "find_file":        "searching files",
        "path_info":        "checking a path",
        "make_dir":         "making a folder",
        "copy_path":        "copying files",
        "move_path":        "moving files",
        "delete_path":      "deleting files",
        "system_info":      "checking the system",
        "disk_usage":       "checking disk usage",
        "processes":        "listing processes",
        "network_status":   "checking the network",
        "recent_downloads": "checking downloads",
        "service_status":   "checking a service",
        "journal_tail":     "reading the journal",
        "desktop_info":     "checking the desktop",
        "list_apps":        "listing apps",
        "list_windows":     "listing windows",
        "launch_app":       "launching an app",
        "open_url":         "opening a link",
        "browser":          "using the browser",
        "focus_window":     "switching windows",
        "close_window":     "closing a window",
        "type_text":        "typing",
        "press_key":        "pressing keys",
        "media_control":    "controlling media",
        "screenshot":       "taking a screenshot",
        "read_screen":      "reading the screen",
        "notify":           "sending a notification",
        "quick_facts":      "checking the system",
    }

    def _status_for_call(self, call) -> str:
        """One short human phrase describing what a single tool call does."""
        n = (getattr(call, "name", "") or "").strip()
        a = getattr(call, "args", None) or {}
        if n == "run":
            cmd = str(a.get("command", "")).strip()
            head = cmd.split()[0] if cmd else ""
            return f"running {head}" if head else "running a command"
        if n.startswith("memory_"):
            return "checking memory"
        if n.startswith("skill"):
            return "using a skill"
        return self._TOOL_STATUS.get(n, f"running {n}" if n else "working")

    def _status_for_batch(self, calls) -> str:
        """Summarise what a parallel batch of read-only tools is doing."""
        if not calls:
            return "running tools"
        labels = [self._status_for_call(c) for c in calls]
        extra = len(labels) - 1
        return f"{labels[0]} + {extra} more" if extra > 0 else labels[0]

    def _ext_complete(self, system: str, user: str) -> str:
        """Short, synchronous, non-streaming completion for the sidecar
        (memory consolidation; the optional foresight model pass).  Routes
        through the existing BackendRouter so it inherits the fallback chain.
        Blocks the CALLING thread — the sidecar only ever calls this from a
        background thread, never the UI thread.  Tolerant of failure: returns
        "" on any error or timeout so a flaky model never wedges a feature."""
        try:
            if not self.router.any_available():
                return ""
            msgs = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
            buf = {"t": ""}
            done = threading.Event()
            self.router.stream_chat(
                msgs,
                lambda tok: buf.__setitem__("t", buf["t"] + tok),
                lambda meta: done.set(),
                lambda err: done.set(),
                threading.Event())
            done.wait(timeout=30)
            return buf["t"]
        except Exception:
            return ""

    def _kick_assistant_turn(self):
        # If the operator hit stop between tool turns, don't start another.
        if self._stop_requested:
            self._finish_turn_cleanup()
            return

        if not self.router.any_available():
            self._show_toast(
                "No provider ready.  Add an API key in Settings → Backends.")
            self.streaming_chat_id = None
            self._tool_chain_depth = 0
            self._set_working(False)
            self._set_send_mode(False)
            return

        # Preserve streaming_chat_id across a tool chain.  Only snapshot
        # when starting a fresh turn (not continuing from a tool result).
        if self.streaming_chat_id is None:
            self.streaming_chat_id = self.current_chat_id
            self._tool_chain_depth = 0
            self._tools_locked = False

        # Limit how many model round-trips a turn may chain.  Rather than
        # dead-ending with "chain too long" and no answer (annoying), once
        # the budget is spent we lock tools and take ONE more turn to answer
        # with whatever was gathered.  The directive below tells the model
        # to stop calling tools; _after_stream ignores any it emits anyway.
        self._tool_chain_depth += 1
        if self._tool_chain_depth > MAX_TOOL_CHAIN and not self._tools_locked:
            self._tools_locked = True
            self.terminal_log("── tool budget reached; finalizing answer", "dim")
            try:
                fin_chat = self.streaming_chat_id or self.current_chat_id
                self.store.add_message(
                    fin_chat, "user",
                    "<tool_result>\n[system note: tool-step budget reached. "
                    "Do not call any more tools. Give your best final answer "
                    "now using everything gathered so far.]\n</tool_result>",
                    meta={"kind": "tool_result"})
            except Exception:
                pass
            # fall through — this turn runs with tools locked.

        chat_id = self.streaming_chat_id

        history = self._build_history_for_model(chat_id)
        addendum = self.settings.get("system_prompt", "")
        # (#3) Urgency fast-path: if the operator's latest message reads as
        # urgent, tell the model (for THIS turn only) to skip preamble and
        # go straight to the most likely fix.
        if self.settings.get("urgency_fast_path", True) and not self._tools_locked:
            try:
                last_user = ""
                for m in reversed(history):
                    if m.get("role") == "user" \
                            and "<tool_result>" not in (m.get("content") or ""):
                        last_user = m.get("content", "")
                        break
                u = detect_urgency(last_user)
                if u.get("urgent"):
                    addendum = (addendum + "\n\n[URGENT: the operator is in a "
                                "hurry (markers: "
                                + ", ".join(u["markers"]) + "). Skip pleasantries "
                                "and context-gathering. Lead with the single most "
                                "likely fix or answer, then offer detail.]").strip()
                    self.terminal_log("⚡ urgency fast-path engaged", "dim")
            except Exception:
                pass
        if getattr(self, "_ext", None):
            try:
                extra = self._ext.system_prompt_block()
                if extra:
                    addendum = (addendum + "\n\n" + extra).strip()
            except Exception:
                pass
        sysprompt = build_system_prompt(
            agent_mode=self.current_agent_mode,
            custom_addendum=addendum)
        full = assemble_messages(sysprompt, history)
        # Splice in relevance-scoped recall (top-k memories for THIS turn).
        # No-op unless memory is enabled; never grows with history length.
        if getattr(self, "_ext", None):
            try:
                full = self._ext.inject_memory(full)
            except Exception:
                pass

        # Fresh assistant widget for this step — reset the speech streamer
        # so sentence detection starts clean, and clear the tool-turn
        # suspend flag (it re-arms below if this turn emits a tool call).
        if self._tts_streamer is not None:
            self._tts_streamer.reset()
        self._tts_suspended = False
        self._turn_active = True

        # Only show the streaming widget if user is looking at this chat
        if chat_id == self.current_chat_id:
            self.streaming_msg_widget = self._append_message_widget(
                "assistant", "")
            self.streaming_msg_widget.start_streaming()
        else:
            # User has navigated away.  We still need a widget to buffer
            # tokens for finish_streaming, but don't attach it to msg_box.
            self.streaming_msg_widget = MessageWidget(
                "assistant", "", on_run_command=self._run_proposed_command,
                on_apply_edit=self._run_proposed_edit,
                on_speak=self._on_message_speak,
                show_thoughts=self.settings.get("show_thoughts", True))
            self.streaming_msg_widget.start_streaming()

        self.streaming_msg_db_id = self.store.add_message(
            chat_id, "assistant", "")

        self.streaming_cancel = threading.Event()

        def _on_tok(tok):
            GLib.idle_add(self._on_stream_token, tok)
        def _on_done(meta):
            GLib.idle_add(self._on_stream_done, meta)
        def _on_err(err):
            GLib.idle_add(self._on_stream_error, err)
        def _on_reason(tok):
            GLib.idle_add(self._on_stream_reasoning, tok)

        def _bg():
            self.router.stream_chat(full, _on_tok, _on_done, _on_err,
                                    self.streaming_cancel,
                                    on_reasoning=_on_reason)

        self.streaming_thread = threading.Thread(target=_bg, daemon=True)
        self.streaming_thread.start()
        self._set_send_mode(True)
        self._set_working(True, "thinking…")
        self.terminal_log("── stream start", "dim")

    def _on_stream_token(self, tok):
        if self.streaming_msg_widget:
            self.streaming_msg_widget.append_streaming(tok)
            # Only scroll if user is on the chat that owns this stream
            if self.streaming_chat_id == self.current_chat_id:
                self._scroll_to_bottom()
            self._feed_tts_stream()
        return False

    def _on_stream_reasoning(self, tok):
        """Reasoning tokens (model 'thoughts') arrive separately from the
        reply; route them to the message's collapsible thoughts panel."""
        if self.streaming_msg_widget:
            self.streaming_msg_widget.append_thought(tok)
            if self.streaming_chat_id == self.current_chat_id:
                self._scroll_to_bottom()
        return False

    def _feed_tts_stream(self):
        """Hand any newly-completed sentences to the speaker as the reply
        streams in.  Suspends for a turn that emits tool tags so we never
        read raw tool XML aloud — the post-tool prose reply gets read
        instead."""
        if not (self.tts and self.settings.get("tts_enabled")):
            return
        if self._tts_streamer is None or self.streaming_msg_widget is None:
            return
        # Strip the model's <think> reasoning before speaking — only the
        # actual reply should be read aloud, never the chain-of-thought.
        content = strip_think_blocks(self.streaming_msg_widget._content or "")
        if not self._tts_suspended and ("<tool" in content):
            # Model is doing a tool turn — stop streaming this widget's
            # audio.  Drop anything already queued from it.
            self._tts_suspended = True
            self.tts.stop()
            return
        if self._tts_suspended:
            return
        try:
            sentences = self._tts_streamer.feed(content)
            if sentences:
                # This reply now owns the speaker; its per-message button
                # will show pause while it reads.
                if self._speaking_widget is not self.streaming_msg_widget:
                    prev = self._speaking_widget
                    if prev is not None:
                        prev.set_speak_state("idle")
                    self._speaking_widget = self.streaming_msg_widget
                for sentence in sentences:
                    self.tts.speak(sentence)
        except Exception as e:
            log(f"tts stream feed error: {e}")

    def _on_stream_done(self, meta):
        if not self.streaming_msg_widget:
            self._finish_turn_cleanup()
            return False
        final = self.streaming_msg_widget.finish_streaming()
        # Flush the last sentence to the speaker (unless this turn ran
        # tools, in which case it was never spoken).
        if (self.tts and self.settings.get("tts_enabled")
                and not self._tts_suspended and self._tts_streamer is not None
                and not (meta.get("cancelled") or self._stop_requested)):
            try:
                for sentence in self._tts_streamer.flush(final):
                    self.tts.speak(sentence)
            except Exception as e:
                log(f"tts flush error: {e}")
        if self.streaming_msg_db_id:
            self.store.update_message(self.streaming_msg_db_id, final)
            # Persist any captured reasoning so the thoughts panel survives a
            # chat reload.  Merge, don't clobber, whatever meta already exists.
            try:
                thoughts = self.streaming_msg_widget.get_thoughts()
                if thoughts:
                    m = dict(self.streaming_msg_widget.meta or {})
                    m["thoughts"] = thoughts
                    self.streaming_msg_widget.meta = m
                    self.store.update_message_meta(
                        self.streaming_msg_db_id, m)
            except Exception as e:
                log(f"thoughts persist failed: {e}")
        calls = parse_tool_calls(final)
        cancelled = meta.get("cancelled") or self._stop_requested
        self.terminal_log(f"── stream done{' (cancelled)' if cancelled else ''}", "dim")
        # `propose` is advisory — it renders a command card (already done by
        # finish_streaming → set_content) and must NOT execute.  Only the
        # sensing/run tools are executable here.
        executable = [c for c in calls
                      if c.name not in ("propose", "propose_edit", "write_file")]
        # When the tool budget is spent we lock tools for the final answer
        # turn — ignore anything the model still tried to call.
        if self._tools_locked:
            executable = []
        # Honour the agent-mode toggle and the stop button.  If the user
        # turned agent mode off or hit stop, don't execute even if the
        # model emitted a tool tag.
        if executable and not cancelled and self.current_agent_mode:
            # EFFICIENCY: gather the leading run of read-only tools and run
            # them together in ONE round-trip (parallel), instead of one
            # model call per lookup.  Stop at the first side-effecting tool
            # so anything with side effects still goes one-at-a-time through
            # its own confirm gate next turn — the safety model is unchanged.
            batch = []
            for c in executable:
                if self._pure_tool_fn(c) is not None:
                    batch.append(c)
                else:
                    break
            if len(batch) >= 2:
                self._set_working(True, self._status_for_batch(batch) + "…")
                self._execute_tool_batch(batch)
            elif batch:
                self._set_working(True, self._status_for_call(batch[0]) + "…")
                self._execute_tool_calls(batch)
            else:
                # First executable tool has side effects → one at a time.
                self._set_working(
                    True, self._status_for_call(executable[0]) + "…")
                self._execute_tool_calls(executable[:1])
        else:
            # (#7) Degraded-output check: if the model returned junk (empty,
            # one-word, or stuck repeating) and it wasn't a deliberate stop,
            # flag it.  With auto_fallback_on_degraded on, hop to the next
            # provider that has a key so the NEXT turn retries elsewhere.
            if (not cancelled and not executable
                    and looks_degraded(final)):
                self.terminal_log("⚠ response looked degraded (empty/"
                                  "repetitive)", "error")
                if self.settings.get("auto_fallback_on_degraded", False):
                    nxt = self._next_provider_with_key()
                    if nxt:
                        self.settings["active_provider"] = nxt
                        save_settings(self.settings)
                        self._show_toast(
                            f"Response looked off — switched to {nxt} for "
                            "the next reply.", timeout=6)
                        self._refresh_subtitle()
                else:
                    self._show_toast(
                        "That reply looked degraded. Try again, or enable "
                        "auto-fallback in Settings → Behaviour.", timeout=6)
            # Turn has fully settled (no tool chaining).  Record it for
            # persistent memory in the background — no-op unless memory is on.
            if getattr(self, "_ext", None) and not cancelled:
                try:
                    rec_chat = self.streaming_chat_id or self.current_chat_id
                    msgs = self.store.list_messages(rec_chat)
                    utext = ""
                    for m in reversed(msgs):
                        if (m.role == "user"
                                and "<tool_result>" not in (m.content or "")):
                            utext = m.content
                            break
                    threading.Thread(
                        target=self._ext.record_turn,
                        args=(utext, final), daemon=True).start()
                except Exception:
                    pass
            self._finish_turn_cleanup()
        return False

    def _on_stream_error(self, err):
        self.terminal_log(f"✗ stream error: {err}", "error")
        if self.streaming_msg_widget:
            # Preserve any tokens that already streamed in.  Wiping the
            # widget and replacing with just the error text discards
            # potentially useful partial output (an explanation that got
            # cut off, a half-finished tool call, etc).
            partial = self.streaming_msg_widget._content or ""
            sep = "\n\n" if partial.strip() else ""
            final_text = f"{partial}{sep}_(error: {err})_"
            self.streaming_msg_widget.set_content(final_text)
            if self.streaming_msg_db_id:
                self.store.update_message(self.streaming_msg_db_id,
                                          final_text)
        self._show_toast(f"Error: {err}")
        # Clear widget refs without re-marking the message (we just wrote
        # the error into it above), then restore the button/banner.
        self.streaming_msg_widget = None
        self.streaming_msg_db_id = None
        self.streaming_chat_id = None
        self._tool_chain_depth = 0
        self._turn_active = False
        self._set_working(False)
        self._set_send_mode(False)
        return False

    # ── tool execution ──────────────────────────────────────────

    def _pure_tool_fn(self, call):
        """Return a zero-arg callable that produces a result dict for a
        read-only, side-effect-free tool that's safe to run in parallel and
        batch — or None if this tool must take the normal (gated / specially
        rendered) single path.  This is the allow-list that decides what can
        be bundled into one round-trip."""
        n = call.name
        a = call.args or {}

        def i(v, d):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return d

        # Web / GitHub research — the tools most likely to chain.
        if n == "web_search":
            return lambda: tool_web_search(
                a.get("query", a.get("q", "")), i(a.get("max_results", 6), 6),
                a.get("site", ""))
        if n == "web_read":
            return lambda: tool_web_read(
                a.get("url", ""), i(a.get("max_chars", 6000), 6000))
        if n == "osint_username":
            return lambda: tool_osint_username(
                a.get("username", a.get("user", "")), a.get("sites", ""),
                i(a.get("timeout", 12), 12))
        if n == "osint_lookup":
            return lambda: tool_osint_lookup(
                a.get("target", a.get("name", "")), a.get("full_name", ""))
        if n == "social_read":
            return lambda: tool_social_read(
                a.get("url", a.get("handle", a.get("url_or_handle", ""))),
                i(a.get("max_chars", 6000), 6000))
        if n == "github":
            return lambda: tool_github(
                a.get("action", ""), a.get("query", ""), a.get("repo", ""),
                a.get("user", ""), a.get("path", ""),
                a.get("ref", a.get("branch", "")), i(a.get("limit", 10), 10))
        # Pentest planning / inventory / reference — pure local work (which-
        # checks, building a command plan, text parsing, reading the
        # filesystem, formatting), no network and no execution, so it's safe
        # to bundle.  web_verify and cve_lookup are deliberately NOT here:
        # they fan out their own network requests and must stay single-path.
        if n == "tooling_check":
            return lambda: tool_tooling_check()
        if n == "pentest_plan":
            return lambda: tool_pentest_plan(
                a.get("target", a.get("host", a.get("url", ""))),
                a.get("profile", a.get("mode", "web")),
                a.get("intensity", a.get("speed", "normal")))
        if n == "parse_output":
            return lambda: tool_parse_output(
                a.get("tool", a.get("name", "")),
                a.get("raw", a.get("output", a.get("text", ""))),
                a.get("enrich_cves", a.get("enrich", False)) not in
                    (False, "false", "0", 0, None))
        if n == "methodology":
            return lambda: tool_methodology(
                a.get("area", a.get("topic", "")),
                a.get("phase", ""))
        if n == "wordlist_find":
            return lambda: tool_wordlist_find(
                a.get("kind", a.get("type", a.get("category", ""))))
        if n == "cheatsheet":
            return lambda: tool_cheatsheet(
                a.get("topic", a.get("tool", a.get("name", ""))))
        if n == "report_findings":
            return lambda: tool_report_findings(
                a.get("findings", a.get("items", [])),
                a.get("target", a.get("host", a.get("url", ""))),
                a.get("scope_note", a.get("scope", "")),
                a.get("title", ""))
        # Pure system / desktop sensing (independent subprocesses).
        if n == "system_info":
            return tool_system_info
        if n == "disk_usage":
            return tool_disk_usage
        if n == "processes":
            return lambda: tool_processes(i(a.get("top_n", 15), 15))
        if n == "network_status":
            return tool_network_status
        if n == "recent_downloads":
            return lambda: tool_recent_downloads(i(a.get("limit", 20), 20))
        if n == "service_status":
            return lambda: tool_service_status(a.get("name"))
        if n == "journal_tail":
            return lambda: tool_journal_tail(
                i(a.get("lines", 50), 50), a.get("unit"))
        if n == "desktop_info":
            return tool_desktop_info
        if n == "list_apps":
            return lambda: tool_list_apps(
                a.get("filter", a.get("filter_text", "")))
        if n == "list_windows":
            return tool_list_windows
        if n == "list_dir":
            return lambda: tool_list_dir(a.get("path", "."))
        if n == "find_file":
            return lambda: tool_find_file(
                a.get("pattern", "*"), a.get("search_path", "~"),
                i(a.get("max_results", 50), 50),
                a.get("min_size_kb", 0), a.get("max_size_kb", 0),
                a.get("modified_within_days", 0))
        if n == "path_info":
            return lambda: tool_path_info(a.get("path", ""))
        if n == "quick_facts":
            return lambda: tool_quick_facts()
        if n == "read_file":
            p = a.get("path", "")
            # Sensitive reads keep their confirm gate — never auto-batched.
            if p and not is_sensitive_path(p):
                return lambda: tool_read_file(p)
            return None
        return None

    def _execute_tool_batch(self, calls):
        """Run several read-only tools concurrently and feed ONE combined
        tool_result back.  A multi-lookup turn then costs a single model
        round-trip (and a single chain step) instead of one per tool."""
        chat_id = self.streaming_chat_id or self.current_chat_id
        for c in calls:
            self.store.add_message(
                chat_id, "tool",
                f"⚙ tool: {c.name}({json.dumps(c.args)})",
                meta={"kind": "call"})
        names = ", ".join(c.name for c in calls)
        self.terminal_log(f"→ batch: {names} ({len(calls)} in parallel)", "info")

        def _bg():
            import concurrent.futures
            results: list = [None] * len(calls)

            def run_one(pair):
                idx, c = pair
                fn = self._pure_tool_fn(c)
                try:
                    res = fn()
                    txt = json.dumps(res, indent=2, default=str)
                except Exception as e:
                    txt = f"error: {type(e).__name__}: {str(e)[:200]}"
                return idx, c.name, txt

            workers = max(1, min(TOOL_BATCH_MAX_WORKERS, len(calls)))
            try:
                with concurrent.futures.ThreadPoolExecutor(
                        max_workers=workers) as ex:
                    for idx, name, txt in ex.map(
                            run_one, list(enumerate(calls))):
                        results[idx] = (name, txt)
            except Exception as e:
                GLib.idle_add(self._feed_tool_result,
                              f"batch error: {e}")
                return

            blocks = []
            for n, (name, txt) in enumerate(results, 1):
                blocks.append(f"[tool {n}/{len(results)}: {name}]\n{txt}")
            combined = "\n\n".join(blocks)
            GLib.idle_add(lambda: self.terminal_log(
                f"✓ batch done ({len(calls)} tools)", "ok") or False)
            GLib.idle_add(self._feed_tool_result, combined)

        threading.Thread(target=_bg, daemon=True).start()

    def _execute_tool_calls(self, calls):
        call = calls[0]
        # `propose` and `propose_edit` are advisory — the card (command or
        # diff) already rendered and carries its own Run/Apply button.
        # They never execute here; if one slips through, end the turn so
        # the card stands on its own.
        if call.name in ("propose", "propose_edit", "write_file"):
            # …but ONLY if the card actually had the data to render.  A
            # propose_edit whose JSON couldn't be parsed (e.g. unescaped
            # quotes inside `content` that the lenient parser can't safely
            # repair) arrives here with no path/content and renders NOTHING —
            # and silently finishing the turn would leave the model believing
            # a diff card is waiting when the screen is empty.  Catch that,
            # tell the model plainly, and let it re-emit instead of lying to
            # the operator about a card that doesn't exist.
            if call.name == "propose":
                card_ok = bool((call.args.get("command")
                                or call.args.get("cmd") or "").strip())
                what = "command proposal"
            else:
                card_ok = (bool((call.args.get("path") or "").strip())
                           and call.args.get("content") is not None)
                what = "file proposal (diff card)"
            if not card_ok:
                retries = getattr(self, "_bad_propose_retries", 0)
                if retries < 2:
                    self._bad_propose_retries = retries + 1
                    self.terminal_log(
                        f"✗ {call.name} did not render (unparseable args) — "
                        f"asking model to re-emit", "error")
                    self._feed_tool_result(
                        f"Your {call.name} did NOT render — its arguments "
                        f"could not be parsed (most likely an unescaped \" or "
                        f"a stray control character inside the \"content\" "
                        f"string). NO {what} is on screen and NOTHING was "
                        f"written or proposed. Re-send it now as a single "
                        f"well-formed tool call: the JSON must be valid — "
                        f"escape every \" inside content as \\\" and use \\n "
                        f"for newlines. Until the card actually renders, do "
                        f"not tell the operator that a proposal or diff card "
                        f"exists.")
                    return
                # Gave it two honest shots; stop bouncing and let the turn end
                # so we don't loop.  The error is in context for next turn.
                self.terminal_log(
                    f"✗ {call.name} still unparseable after retries — "
                    f"ending turn", "error")
            self._finish_turn_cleanup()
            return
        # Always write to the chat this turn was started in, not whichever
        # one the user might have navigated to.
        chat_id = self.streaming_chat_id or self.current_chat_id

        # Update the working banner with a human phrase for this tool so the
        # operator can see what's happening as a chain runs ("searching the
        # web…", "running nmap…").  Hidden tool indicators in the message
        # stream stay hidden — they're noisy.
        self._set_working(True, self._status_for_call(call) + "…")

        self.store.add_message(chat_id, "tool",
                                f"⚙ tool: {call.name}({json.dumps(call.args)})",
                                meta={"kind": "call"})

        # Models drift and sometimes emit non-numeric values for numeric
        # args ("fifteen", null, "15.5", {}).  A bare int() on those raises
        # and kills the whole tool turn — coerce safely and fall back to
        # the default instead.
        def _safe_int(v, default):
            try:
                return int(float(v))   # tolerates "15", 15, "15.5"
            except (TypeError, ValueError):
                return default

        dispatch = {
            "read_file":         lambda a: self._tool_read_file(a.get("path", "")),
            "list_dir":          lambda a: self._tool_list_dir(a.get("path", ".")),
            "find_file":         lambda a: self._tool_find_file(
                a.get("pattern", "*"), a.get("search_path", "~"),
                _safe_int(a.get("max_results", 50), 50),
                a.get("min_size_kb", 0), a.get("max_size_kb", 0),
                a.get("modified_within_days", 0)),
            "quick_facts":       lambda a: self._tool_simple(
                lambda: tool_quick_facts()),
            "system_info":       lambda a: self._tool_simple(tool_system_info),
            "disk_usage":        lambda a: self._tool_simple(tool_disk_usage),
            "processes":         lambda a: self._tool_simple(
                lambda: tool_processes(_safe_int(a.get("top_n", 15), 15))),
            "network_status":    lambda a: self._tool_simple(tool_network_status),
            "recent_downloads":  lambda a: self._tool_simple(
                lambda: tool_recent_downloads(_safe_int(a.get("limit", 20), 20))),
            "check_updates":     lambda a: self._tool_simple(tool_check_updates),
            "service_status":    lambda a: self._tool_simple(
                lambda: tool_service_status(a.get("name"))),
            "journal_tail":      lambda a: self._tool_simple(
                lambda: tool_journal_tail(
                    _safe_int(a.get("lines", 50), 50), a.get("unit"))),
            "run":               lambda a: self._tool_run(
                a.get("command", ""), a.get("reason", "")),
            "audit":             lambda a: self._tool_audit(),
            "scan_net":          lambda a: self._tool_scan_net(a.get("cidr")),

            # ── Desktop control (read-only: simple) ──
            "desktop_info":      lambda a: self._tool_simple(tool_desktop_info),
            "list_apps":         lambda a: self._tool_simple(
                lambda: tool_list_apps(a.get("filter", a.get("filter_text", "")))),
            "list_windows":      lambda a: self._tool_simple(tool_list_windows),
            "media_control":     lambda a: self._tool_simple(
                lambda: tool_media_control(a.get("action", "status"))),
            "notify":            lambda a: self._tool_simple(
                lambda: tool_notify(a.get("message", ""),
                                    a.get("title", "Kali"))),

            # ── Desktop control (actions: confirm-gated) ──
            "launch_app":        lambda a: self._action_tool(
                "launch_app", lambda: tool_launch_app(
                    a.get("app", ""), a.get("args", "")),
                f"launch app: {a.get('app','')}"),
            "open_url":          lambda a: self._action_tool(
                "open_url", lambda: tool_open_url(a.get("url", "")),
                f"open URL: {a.get('url','')}"),
            "focus_window":      lambda a: self._action_tool(
                "focus_window", lambda: tool_focus_window(a.get("title", "")),
                f"focus window: {a.get('title','')}"),
            "close_window":      lambda a: self._action_tool(
                "close_window", lambda: tool_close_window(a.get("title", "")),
                f"close window: {a.get('title','')}"),
            "type_text":         lambda a: self._action_tool(
                "type_text", lambda: tool_type_text(a.get("text", "")),
                f"type {len(a.get('text',''))} chars into focused window"),
            "press_key":         lambda a: self._action_tool(
                "press_key", lambda: tool_press_key(a.get("keys", "")),
                f"press key: {a.get('keys','')}"),

            # ── Screenshots & screen reading (read-only: simple) ──
            "screenshot":        lambda a: self._tool_simple(
                lambda: tool_screenshot(a.get("save_path", a.get("path", "")))),
            "read_screen":       lambda a: self._tool_simple(
                lambda: tool_read_screen(a.get("region", ""))),

            # ── Filesystem (read-only: simple) ──
            "path_info":         lambda a: self._tool_simple(
                lambda: tool_path_info(a.get("path", ""))),
            "make_dir":          lambda a: self._tool_simple(
                lambda: tool_make_dir(a.get("path", ""))),
            "copy_path":         lambda a: self._tool_simple(
                lambda: tool_copy_path(a.get("src", ""), a.get("dst", ""))),

            # ── Filesystem (destructive: confirm-gated) ──
            "move_path":         lambda a: self._action_tool(
                "move_path", lambda: tool_move_path(
                    a.get("src", ""), a.get("dst", "")),
                f"move {a.get('src','')} → {a.get('dst','')}"),
            "delete_path":       lambda a: self._action_tool(
                "delete_path", lambda: tool_delete_path(
                    a.get("path", ""),
                    bool(a.get("recursive", False))),
                f"DELETE {a.get('path','')}"
                f"{' (recursive)' if a.get('recursive') else ''}"),

            # ── Browser automation ──
            # read/title/url are read-only; goto/click/fill/screenshot/close
            # are actions but low-risk, so they run without a blocking
            # confirm (the operator can still stop the turn).  Destructive
            # browser side-effects come from the page, not the tool.
            "browser":           lambda a: self._tool_simple(
                lambda: tool_browser(
                    a.get("action", ""), a.get("target", ""),
                    a.get("value", ""))),

            # ── Web search & read (read-only: simple, headless) ──
            # Fast HTTP search/read — no GUI browser, no API key.  This is
            # the path the model should reach for to "look something up";
            # the browser tool is reserved for interactive/login-gated work.
            "web_search":        lambda a: self._tool_simple(
                lambda: tool_web_search(
                    a.get("query", a.get("q", "")),
                    _safe_int(a.get("max_results", 6), 6),
                    a.get("site", ""))),
            "web_read":          lambda a: self._tool_simple(
                lambda: tool_web_read(
                    a.get("url", ""),
                    _safe_int(a.get("max_chars", 6000), 6000))),
            "image_search":      lambda a: self._tool_simple(
                lambda: tool_image_search(
                    a.get("query", a.get("q", "")),
                    _safe_int(a.get("max_results", 4), 4))),
            "analyze_image":     lambda a: self._tool_simple(
                lambda: tool_analyze_image(
                    a.get("image_path", a.get("path", a.get("url", ""))),
                    a.get("question", a.get("prompt", "")),
                    self._vision_key(), self._vision_base_url(),
                    self.settings.get("vision_model", ""))),
            "capture_photo":     lambda a: self._tool_simple(
                lambda: tool_capture_photo(a.get("out_path", ""))),
            "detect_faces":      lambda a: self._tool_simple(
                lambda: tool_detect_faces(
                    a.get("image_path", a.get("path", "")))),

            # ── OSINT (read-only: simple, public sources only) ──
            # Footprint / username discovery across public profile sites and
            # platform-aware public readers.  No login, no gated data.
            "osint_username":    lambda a: self._tool_simple(
                lambda: tool_osint_username(
                    a.get("username", a.get("user", "")),
                    a.get("sites", ""),
                    _safe_int(a.get("timeout", 12), 12))),
            "osint_lookup":      lambda a: self._tool_simple(
                lambda: tool_osint_lookup(
                    a.get("target", a.get("name", "")),
                    a.get("full_name", ""))),
            "social_read":       lambda a: self._tool_simple(
                lambda: tool_social_read(
                    a.get("url", a.get("handle", a.get("url_or_handle", ""))),
                    _safe_int(a.get("max_chars", 6000), 6000))),

            # ── GitHub (read-only: simple, headless) ──
            "github":            lambda a: self._tool_simple(
                lambda: tool_github(
                    a.get("action", ""), a.get("query", ""),
                    a.get("repo", ""), a.get("user", ""),
                    a.get("path", ""), a.get("ref", a.get("branch", "")),
                    _safe_int(a.get("limit", 10), 10))),

            # ── Verification & anti-propaganda (read-only) ──
            # Cross-check a claim across several INDEPENDENT sources, score
            # them for credibility, flag state-media / satire, and report a
            # confidence label.  The path the model should take before
            # asserting anything current, factual, or security-relevant.
            "web_verify":        lambda a: self._tool_simple(
                lambda: tool_web_verify(
                    a.get("query", a.get("q", a.get("claim", ""))),
                    _safe_int(a.get("max_sources",
                                    self.settings.get("verify_max_sources", 5)),
                              self.settings.get("verify_max_sources", 5)),
                    self.settings)),

            # ── Pentest support (read-only / proposing only) ──
            # None of these execute an attack: pentest_plan returns PROPOSED
            # commands that still go through the approve-before-run gate; the
            # rest are inventory, text parsing, filesystem lookups, reference
            # knowledge and report formatting.  cve_lookup is the only one
            # that touches the network (NVD + KEV + EPSS).
            "tooling_check":     lambda a: self._tool_simple(
                lambda: tool_tooling_check()),
            "pentest_plan":      lambda a: self._tool_simple(
                lambda: tool_pentest_plan(
                    a.get("target", a.get("host", a.get("url", ""))),
                    a.get("profile", a.get("mode", "web")),
                    a.get("intensity", a.get("speed", "normal")))),
            "cve_lookup":        lambda a: self._tool_simple(
                lambda: tool_cve_lookup(
                    a.get("product", a.get("name", a.get("software", ""))),
                    a.get("version", a.get("ver", "")),
                    _safe_int(a.get("limit", 8), 8),
                    a.get("enrich", True) not in (False, "false", "0", 0))),
            "parse_output":      lambda a: self._tool_simple(
                lambda: tool_parse_output(
                    a.get("tool", a.get("name", "")),
                    a.get("raw", a.get("output", a.get("text", ""))),
                    a.get("enrich_cves", a.get("enrich", False)) not in
                        (False, "false", "0", 0, None))),
            "methodology":       lambda a: self._tool_simple(
                lambda: tool_methodology(
                    a.get("area", a.get("topic", "")),
                    a.get("phase", ""))),
            "wordlist_find":     lambda a: self._tool_simple(
                lambda: tool_wordlist_find(
                    a.get("kind", a.get("type", a.get("category", ""))))),
            "cheatsheet":        lambda a: self._tool_simple(
                lambda: tool_cheatsheet(
                    a.get("topic", a.get("tool", a.get("name", ""))))),
            "report_findings":   lambda a: self._tool_simple(
                lambda: tool_report_findings(
                    a.get("findings", a.get("items", [])),
                    a.get("target", a.get("host", a.get("url", ""))),
                    a.get("scope_note", a.get("scope", "")),
                    a.get("title", ""))),
            "evidence_report":   lambda a: self._tool_simple(
                lambda: _evidence_report(
                    a.get("engagement", a.get("name", None)))),
            "evidence_verify":   lambda a: self._tool_simple(
                lambda: (get_ledger().verify(a.get("engagement", None))
                         if get_ledger() else {"error": "ledger unavailable"})),
            "evidence_engagement": lambda a: self._tool_simple(
                lambda: _evidence_set_engagement(
                    a.get("engagement", a.get("name", a.get("value", ""))))),
            "nuclei_template":   lambda a: self._tool_simple(
                lambda: tool_nuclei_template(
                    a.get("spec", a.get("template", a)),
                    a.get("mode", "build"),
                    a.get("yaml", a.get("yaml_text", "")))),
            "reflect_findings":  lambda a: self._tool_simple(
                lambda: tool_reflect_findings(
                    a.get("findings", a.get("items", a)))),
        }
        # Merge sidecar tools (memory_*, skill_list, skill_run).  Returns an
        # empty dict unless the matching feature is enabled, so stock Kali is
        # unchanged.  skill_write is registered here (not in the sidecar) so
        # the save goes through Kali's own confirm dialog.
        if getattr(self, "_ext", None):
            try:
                for _tname, _tfn in self._ext.extra_tools(self).items():
                    # Sidecar tools return a result STRING.  Run each off the
                    # GTK main loop (this dispatch runs ON it) and feed the
                    # result back via the loop — skill_run spawns a sandbox
                    # subprocess that can take many seconds, and running it
                    # inline here froze the whole UI until it returned.
                    dispatch[_tname] = (lambda f:
                                        (lambda a: self._bg_feed_text(
                                            lambda: f(a))))(_tfn)
                if self.settings.get("skills_enabled", False):
                    dispatch["skill_write"] = self._tool_skill_write
            except Exception:
                pass
        fn = dispatch.get(call.name)
        if fn:
            self.terminal_log(f"→ tool: {call.name}({json.dumps(call.args, separators=(',',':'))[:80]})", "info")
            fn(call.args)
        else:
            self.terminal_log(f"✗ unknown tool: {call.name}", "error")
            self._feed_tool_result(f"Unknown tool '{call.name}'.")

    def _feed_tool_result(self, result_text):
        # Route to the chat this turn was started in.  Resolved from
        # streaming_chat_id; if the turn was torn down (stop / delete)
        # it's None and we fall back to the current chat.
        chat_id = self.streaming_chat_id or self.current_chat_id
        self.store.add_message(chat_id, "user",
                                f"<tool_result>\n{result_text}\n</tool_result>",
                                meta={"kind": "tool_result"})
        self.streaming_msg_widget = None
        self.streaming_msg_db_id = None
        # If the operator stopped while the tool was running, record the
        # result for context but don't start another model turn.
        if self._stop_requested:
            self._finish_turn_cleanup()
            return
        # streaming_chat_id stays set — _kick_assistant_turn will preserve it
        self._kick_assistant_turn()

    def _bg_feed_text(self, fn):
        """Run fn() — which returns the final result STRING — on a background
        thread, then feed that string back via the main loop.  Like
        _tool_simple, but for callables that already produce the finished text
        (no JSON re-encoding), e.g. the sidecar's memory_*/skill_* tools."""
        def _bg():
            try:
                text = fn()
            except Exception as e:
                text = f"error: {type(e).__name__}: {e}"
            if not isinstance(text, str):
                text = json.dumps(text, default=str)
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

    def _vision_key(self) -> str:
        prov = self.settings.get("vision_provider", "siliconflow")
        return (self.settings.get(f"{prov}_api_key", "") or "").strip()

    def _vision_base_url(self) -> str:
        prov = self.settings.get("vision_provider", "siliconflow")
        spec = PROVIDERS_BY_KEY.get(prov)
        return spec.base_url if spec else ""

    def _tool_simple(self, fn):
        def _bg():
            try:
                GLib.idle_add(lambda: self.terminal_log(f"→ running {fn.__name__ if hasattr(fn, '__name__') else 'tool'}…", "info") or False)
                result = fn()
                text = json.dumps(result, indent=2, default=str)
                GLib.idle_add(lambda: self.terminal_log("✓ done", "ok") or False)
            except Exception as e:
                # Capture the message NOW — `e` is deleted when this except
                # block exits, but the idle_add lambda runs later in the main
                # loop, so referencing `e` inside it raises NameError.
                msg = str(e)
                text = f"error: {msg}"
                GLib.idle_add(lambda m=msg: self.terminal_log(f"✗ {m}", "error") or False)
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

    def _action_tool(self, name, fn, description):
        """Run an action tool (one with side effects: launching apps,
        typing, moving/deleting files).  Honours the SAME 'Confirm every
        command' toggle the shell `run` tool uses — when it's on, the
        operator approves via a dialog first; when off (auto mode), the
        action runs immediately.  Either way the result is fed back to
        the model."""
        def _go(allow=True, password=None):
            if not allow:
                self._feed_tool_result(f"operator declined: {description}")
                return
            self._tool_simple(fn)

        if self.settings.get("confirm_all_commands", True):
            confirm_command_dialog(self, description,
                                   f"Kali wants to: {description}", _go)
        else:
            _go(True)

    def _tool_skill_write(self, a):
        """Self-written skill.  The model supplies name/code/test/description/
        capabilities.  Saving is gated by the same confirm dialog the operator
        uses for commands: on approval the sidecar ast-checks the code, runs
        its test IN THE SANDBOX, and keeps it only if the test passes.  Nothing
        executes in Kali's own process."""
        name = str(a.get("name", "")).strip()
        code = str(a.get("code", ""))
        test = str(a.get("test", ""))
        desc = str(a.get("description", ""))
        caps = list(a.get("capabilities", []) or [])

        def _go(allow=True, password=None):
            if not allow:
                self._feed_tool_result(f"operator declined saving skill {name!r}")
                return

            def _bg():
                try:
                    r = self._ext.commit_skill(name, code, test, desc, caps)
                except Exception as e:
                    r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                if r.get("ok"):
                    self.terminal_log(f"✓ skill saved: {name} "
                                      f"(sandbox: {r.get('tier')})", "ok")
                else:
                    self.terminal_log(f"✗ skill rejected: "
                                      f"{r.get('reason') or r.get('error')}", "error")
                GLib.idle_add(self._feed_tool_result,
                              json.dumps(r, indent=2, default=str))
            threading.Thread(target=_bg, daemon=True).start()

        descr = (f"save self-written skill '{name}'"
                 + (f" (caps: {', '.join(caps)})" if caps else "")
                 + " — sandbox-tested before keeping")
        if self.settings.get("confirm_all_commands", True):
            # Surface what's actually being approved: capabilities, any flagged
            # constructs from the static screen, and a code preview.  Approving
            # a skill you can't see defeats the point of the gate.
            try:
                from kali_ext import skills as _sk
                flags = sorted({r for r in _sk._RISKY if r in code})
            except Exception:
                flags = []
            preview = code.strip().splitlines()
            preview_txt = "\n".join(preview[:18])
            if len(preview) > 18:
                preview_txt += f"\n… (+{len(preview) - 18} more lines)"
            msg = (f"Kali wrote a skill '{name}' and wants to save it. It is "
                   f"tested in a sandbox before being kept.\n\n"
                   f"capabilities: {', '.join(caps) if caps else 'none'}\n"
                   + (f"flagged: {', '.join(flags)}\n" if flags else "")
                   + f"\ncode:\n{preview_txt}")
            confirm_command_dialog(self, descr, msg, _go)
        else:
            _go(True)


    def _tool_read_file(self, path):
        if not path:
            self._feed_tool_result("error: no path")
            return
        def do_read():
            def _bg():
                r = tool_read_file(path)
                GLib.idle_add(self._render_read, r)
            threading.Thread(target=_bg, daemon=True).start()
        if is_sensitive_path(path):
            confirm_sensitive_read_dialog(self, path, lambda allow:
                do_read() if allow
                else self._feed_tool_result(f"denied: {path}"))
        else:
            do_read()

    def _render_read(self, r):
        if not r.get("ok"):
            self._feed_tool_result(f"read_file error: {r.get('error')}")
            return
        body = r["content"]
        header = (f"file: {r['path']} ({r['size']} bytes"
                  f"{' truncated' if r['truncated'] else ''})")
        self._feed_tool_result(f"{header}\n\n{body}")

    def _tool_list_dir(self, path):
        def _bg():
            self.terminal_log(f"→ list_dir {path}", "info")
            r = tool_list_dir(path)
            if not r.get("ok"):
                text = f"list_dir error: {r.get('error')}"
                self.terminal_log(f"✗ {r.get('error')}", "error")
            else:
                lines = [f"dir: {r['path']}", ""]
                for e in r["entries"]:
                    sz = "" if e["is_dir"] else f"  ({e['size']}B)"
                    lines.append(f"  {e['name']}{sz}")
                text = "\n".join(lines)
                self.terminal_log(f"✓ {len(r['entries'])} entries", "ok")
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

    def _tool_find_file(self, pattern, search_path, max_results=50,
                        min_size_kb=0, max_size_kb=0,
                        modified_within_days=0):
        def _bg():
            self.terminal_log(f"→ find {pattern} in {search_path}", "info")
            r = tool_find_file(pattern, search_path, max_results,
                               min_size_kb, max_size_kb, modified_within_days)
            if r.get("ok"):
                lines = [f"find {pattern} in {r['search_path']}: "
                         f"{r['count']} hit(s)"]
                for hit in r["found"]:
                    if isinstance(hit, dict):
                        sz = hit.get("size")
                        szs = f"  ({sz}B)" if sz is not None else ""
                        lines.append(f"  {hit.get('path')}{szs}")
                    else:
                        lines.append(f"  {hit}")
                text = "\n".join(lines)
                self.terminal_log(f"✓ {r['count']} found", "ok")
            else:
                text = f"find_file error: {r.get('error')}"
                self.terminal_log(f"✗ {r.get('error')}", "error")
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

    def _tool_run(self, command, reason):
        # Reached only when the model emits <tool name="run"> after the
        # operator approved.  Goes through the same gate as the card.
        self._execute_command(command, reason)

    def _reload_persona(self) -> bool:
        """Hot-reload kali_persona after a self-edit and rebind the names this
        module imported from it, so a change to Kali's persona applies on the
        next reply without a relaunch.  kali.py / kali_core.py changes still
        need a relaunch (you can't safely swap a running app's own modules)."""
        try:
            import importlib
            import kali_persona as _kp
            importlib.reload(_kp)
            global build_system_prompt, assemble_messages, title_from_first_message
            build_system_prompt = _kp.build_system_prompt
            assemble_messages = _kp.assemble_messages
            title_from_first_message = _kp.title_from_first_message
            log("persona hot-reloaded")
            return True
        except Exception as e:
            log(f"persona reload failed: {e}")
            return False

    def _run_proposed_edit(self, path, content, card=None):
        """Called when the operator clicks Apply on a proposed-edit card.
        The click IS the approval.  Mirrors _run_proposed_command: set up
        a turn context, write the file (with the parse-check + backup net
        in tool_write_file), then feed the result back so Kali confirms.

        A file write is the same kind of action as a command — it goes
        through the same confirm-by-clicking gate.  We surface a sudo
        prompt only if the write lands somewhere the user can't write,
        in which case we tell Kali to retry via `sudo tee` rather than
        silently failing."""
        if not path:
            if card is not None:
                card.reset_apply_button()
            return
        if self._is_busy():
            self._show_toast("Busy — let the current task finish or stop it.")
            if card is not None:
                card.reset_apply_button()
            return
        self._stop_requested = False
        if self.current_chat_id is None:
            self._new_chat()
        self.streaming_chat_id = self.current_chat_id
        self._tool_chain_depth = 0
        self._set_working(True, "writing file…")
        self._set_send_mode(True)

        def _bg():
            r = tool_write_file(path, content)
            if r.get("ok"):
                parts = [f"wrote {r['path']} ({r['size']} bytes)"]
                if r.get("created"):
                    parts.append("(new file created)")
                if r.get("backup"):
                    parts.append(f"backup: {r['backup']}")
                if r.get("is_python"):
                    base = os.path.basename(r["path"])
                    if base == "kali_persona.py":
                        if self._reload_persona():
                            parts.append("Persona reloaded live — the new "
                                         "character takes effect on my next "
                                         "reply, no relaunch needed.")
                        else:
                            parts.append("Python syntax was checked, but the "
                                         "live persona reload failed — "
                                         "relaunch to apply.")
                    else:
                        parts.append("Python syntax was checked before "
                                     "writing. This is a core file (kali.py / "
                                     "kali_core.py) — relaunch to load it.")
                out = "\n".join(parts)
            else:
                out = f"write failed for {path}\nerror: {r.get('error')}"
            GLib.idle_add(self._feed_tool_result, out)
        threading.Thread(target=_bg, daemon=True).start()

    def _run_proposed_command(self, command, explanation="", card=None):
        """Called when the operator clicks Run on a proposed-command card.
        The click IS the approval — we set up a turn context and execute,
        then Kali interprets the output."""
        if not command:
            if card is not None:
                card.reset_run_button()
            return
        if self._is_busy():
            self._show_toast("Busy — let the current task finish or stop it.")
            if card is not None:
                card.reset_run_button()
            return
        self._stop_requested = False
        if self.current_chat_id is None:
            self._new_chat()
        # This is the start of a turn — capture the chat and show the
        # stop affordance so a long command can be interrupted.
        self.streaming_chat_id = self.current_chat_id
        self._tool_chain_depth = 0
        self._set_working(True, "running…")
        self._set_send_mode(True)
        # The click on the card IS the approval, so don't re-confirm a safe
        # command — only stop for a sudo password when root is required.
        self._execute_command(command, explanation or "operator approved",
                              from_card=True)

    def _execute_command(self, command, reason, from_card=False):
        """Confirm (with sudo password if needed), run, feed result back.
        Shared by the model's `run` tool and the card's Run button.

        from_card=True means the operator already approved by clicking Run,
        so we skip the redundant y/n and only surface a dialog when the
        command needs root (to collect the password)."""
        if not command:
            self._feed_tool_result("error: no command")
            return

        # ── HARD BLOCK — the one gate with no override ──
        # A command in the catastrophic class (rm -rf /, mkfs, dd onto a disk,
        # fork bomb, recursive delete of root/system dirs, …) is REFUSED
        # outright, before any confirm dialog, before foresight, before the
        # shell.  There is no "Run anyway" button and no setting that turns
        # this off: Kali, as an AI, will never be the thing that runs a
        # system-destroying command.  A human who truly needs such an op does
        # it themselves in a real terminal.
        if is_catastrophic_command(command):
            self.terminal_log("■ BLOCKED — catastrophic command refused "
                              "(no override)", "error")
            self._feed_tool_result(
                "REFUSED. This command is in the catastrophic class — it would "
                "irreversibly destroy the system or its data — so Kali will not "
                "run it under any circumstances. There is no override; this is "
                "a hard safety floor. If a human genuinely needs this, they "
                "must do it themselves in a real terminal.\n\n  " + command)
            return

        # ── foresight gate ──
        # Predict consequences before running.  Off unless foresight_enabled.
        # Runs in a background thread so the optional model pass can't freeze
        # the UI, then resumes here.  A `block` (catastrophic / irreversible)
        # refuses outright; a `caution` is surfaced and then proceeds through
        # the normal confirm path.  The _fs_cleared flag stops re-entry.
        if (not getattr(self, "_fs_cleared", False)
                and getattr(self, "_ext", None)
                and self.settings.get("foresight_enabled", False)):
            def _fbg():
                try:
                    v = self._ext.foresight(command)
                except Exception:
                    v = {"verdict": "allow"}
                def _resume():
                    try:
                        from kali_ext.foresight import render_card
                    except Exception:
                        render_card = lambda x: ""
                    verdict = v.get("verdict")
                    force_confirm = False
                    if verdict in ("block", "caution"):
                        # Risky, but the truly system-destroying set is already
                        # hard-blocked above with no override.  Anything that
                        # reaches here (broad deletes, service stops, firewall
                        # flushes, force-push, …) is shown with its consequence
                        # card and then STOPS for the operator's explicit OK —
                        # never silently auto-run, never flatly refused.
                        card = render_card(v)
                        if card:
                            self.terminal_log(card, "error")
                        force_confirm = True
                    self._fs_cleared = True
                    self._fs_force_confirm = force_confirm
                    try:
                        self._execute_command(command, reason,
                                              from_card=from_card)
                    finally:
                        self._fs_cleared = False
                        self._fs_force_confirm = False
                    return False
                GLib.idle_add(_resume)
            threading.Thread(target=_fbg, daemon=True).start()
            return

        # ── (#4) command de-duplication ──
        # Record every command that reaches execution; if the operator opted
        # in, warn when the exact command was already run very recently (a
        # stale re-issue or an accidental double-tap).  Non-blocking.
        if self.settings.get("warn_duplicate_commands", False):
            try:
                if recent_duplicate(command, 600):
                    self._show_toast(
                        "You just ran this command. Intentional, or stale?",
                        timeout=5)
                    self.terminal_log(
                        f"⚠ duplicate command within 10m: {command[:60]}",
                        "dim")
            except Exception:
                pass
        try:
            note_command(command)
        except Exception:
            pass

        # Long-running ops (package work, scans, builds) need more than the
        # old hard 60s or they time out mid-apt and look broken.  Match on
        # the actual COMMAND TOKENS, not raw substrings — the old `k in low`
        # check false-matched "make" inside "cmake", "install" inside any
        # path containing it, "dd " inside "add ", etc., handing trivial
        # commands a needless 30-min window.
        long_cmds = {"apt", "apt-get", "dpkg", "nmap", "make", "pip", "pip3",
                     "rsync", "dd", "git", "wget", "curl", "docker"}
        long_words = {"upgrade", "dist-upgrade", "install"}  # subcommands
        # Split on shell separators, then take the leading token of each
        # simple command (skipping leading VAR=val assignments and sudo).
        tokens = re.split(r'[\n;&|]+', command.lower())
        is_long = False
        for seg in tokens:
            words = seg.split()
            i = 0
            while i < len(words) and ("=" in words[i] or words[i] == "sudo"):
                i += 1
            if i >= len(words):
                continue
            head = os.path.basename(words[i])   # strip any path prefix
            if head in long_cmds:
                is_long = True
                break
            if any(w in long_words for w in words[i:]):
                is_long = True
                break
        timeout = 1800 if is_long else 120

        def run_bg(password=None):
            def _bg():
                # Log the command but DON'T force the panel open — the
                # operator opens the log themselves with the toggle when
                # they want it.  The command still shows in the status line.
                self.terminal_log(f"$ {command}", "cmd")
                r = tool_run_command(command, timeout=timeout,
                                     sudo_password=password)
                # Record to the evidence ledger (fail-safe: a ledger error must
                # never affect the command result the operator sees).
                try:
                    _led = get_ledger()
                    if _led is not None:
                        _led.record(command, reason, r)
                except Exception:
                    pass
                if r.get("ok"):
                    parts = [f"$ {command}", f"(rc={r['rc']})"]
                    if r["stdout"]:
                        # Stream stdout to terminal log line by line
                        for line in r["stdout"].splitlines()[:80]:
                            GLib.idle_add(lambda l=line: self.terminal_log(l, "stdout") or False)
                        parts.append(r["stdout"])
                    if r["stderr"]:
                        for line in r["stderr"].splitlines()[:20]:
                            GLib.idle_add(lambda l=line: self.terminal_log(l, "stderr") or False)
                        parts.append(f"stderr:\n{r['stderr']}")
                    if r.get("sudo_auth_failed"):
                        parts.append(
                            "\n[note] sudo could not authenticate "
                            "non-interactively. The password may have been "
                            "wrong, or sudo timed out its cached credential.")
                        self.terminal_log("✗ sudo auth failed", "error")
                    else:
                        self.terminal_log(f"✓ rc={r['rc']}", "ok" if r['rc'] == 0 else "error")
                    out = "\n".join(parts)
                else:
                    out = f"$ {command}\nerror: {r.get('error')}"
                    self.terminal_log(f"✗ {r.get('error')}", "error")
                GLib.idle_add(self._feed_tool_result, out)
            threading.Thread(target=_bg, daemon=True).start()

        def decide(allow, password=None):
            if not allow:
                self._feed_tool_result(f"operator declined: {command}")
                return
            run_bg(password)

        # The card click already counts as approval, so for an ordinary
        # command we just run.  We still surface the confirm dialog when
        # the command needs root (to collect the password), or — for a
        # model-initiated run — when the operator asked to confirm every
        # command.
        # (#9) If a root command is needed but sudo already has a cached
        # credential this session, skip the password prompt and run silently
        # (when auto_sudo_when_cached is on).  Approval gating is separate:
        # confirm_all_commands still shows the dialog for model-initiated runs.
        sudo_needed = command_needs_sudo(command)
        have_cached_sudo = (sudo_needed
                            and self.settings.get("auto_sudo_when_cached", True)
                            and sudo_cached())
        # Hard backstop: a system-destroying command (disk/fs wipe, recursive
        # root delete, fork bomb…) ALWAYS stops for an explicit confirm — even
        # in auto-run mode, even from a card.  This is the one gate a setting
        # can't switch off, because it's the one mistake that can't be undone.
        catastrophic = is_catastrophic_command(command)
        # Same treatment for a raw shell write to Kali's own source files: it
        # would bypass the guarded edit path (parse-check + immutable
        # guardrail), so it never auto-runs silently.
        tampers = command_tampers_self(command)
        reason_txt = reason or "no reason"
        if catastrophic:
            self.terminal_log("⚠ destructive command — forcing confirm", "error")
        elif tampers:
            self.terminal_log("• command writes to Kali's own source — "
                              "forcing confirm", "dim")
            reason_txt = ("This command writes to one of Kali's own source "
                          "files, which sidesteps the guarded edit path "
                          "(parse-check + immutable guardrail). Confirm to "
                          "allow.\n\n" + reason_txt)
        need_approval = (catastrophic or tampers
                         or (getattr(self, "_fs_force_confirm", False)
                             and not from_card)
                         or (self.settings.get("confirm_all_commands", True)
                             and not from_card))
        if need_approval or (sudo_needed and not have_cached_sudo):
            confirm_command_dialog(self, command, reason_txt, decide,
                                   catastrophic=catastrophic)
        else:
            if have_cached_sudo:
                self.terminal_log("• using cached sudo credential", "dim")
            run_bg(None)

    def _tool_audit(self):
        self._show_toast("Auditing…")
        def _bg():
            try:
                def _prog(title, done, total):
                    self.terminal_log(f"[{done}/{total}] {title}", "info")
                audit = run_security_audit(on_progress=_prog)
                text = format_audit_for_chat(audit)
                self.terminal_log(f"✓ audit complete — grade {audit['grade']}", "ok")
            except Exception as e:
                text = f"audit failed: {type(e).__name__}: {e}"
                self.terminal_log(f"✗ audit failed: {e}", "error")
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

    def _tool_scan_net(self, cidr=None):
        self._show_toast("Scanning network…")
        def _bg():
            try:
                def _prog(msg):
                    self.terminal_log(f"nmap: {msg}", "info")
                scan = run_network_scan(cidr, on_progress=_prog)
                text = format_scan_for_chat(scan)
                if scan.get("ok"):
                    self.terminal_log(f"✓ scan complete — {len(scan.get('hosts', []))} hosts", "ok")
                else:
                    self.terminal_log(f"✗ scan failed: {scan.get('error')}", "error")
            except Exception as e:
                text = f"scan failed: {type(e).__name__}: {e}"
                self.terminal_log(f"✗ {e}", "error")
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

    # ── user-initiated chip actions ─────────────────────────────

    def _is_busy(self) -> bool:
        """True when an assistant turn or tool call is in flight."""
        if self.streaming_thread and self.streaming_thread.is_alive():
            return True
        if self.streaming_msg_widget is not None:
            return True
        if self.streaming_chat_id is not None:
            return True
        return False

    def _begin_chip_action(self) -> bool:
        """Snapshot the current chat for an upcoming chip-triggered tool
        and switch the primary button to Stop.  Returns False if busy."""
        if self._is_busy():
            self._show_toast("Already busy — stop the current task first.")
            return False
        self._stop_requested = False
        # Capture the chat NOW so that when the async tool finishes and
        # _feed_tool_result fires (could be many seconds later), the
        # result lands in the chat the user clicked from, not whichever
        # they happen to be looking at when the result arrives.
        if self.current_chat_id is None:
            self._new_chat()
        self.streaming_chat_id = self.current_chat_id
        self._tool_chain_depth = 0
        self._set_working(True, "working…")
        self._set_send_mode(True)
        return True

    def _maybe_set_title_from_first(self, chat_id: int, first_text: str):
        """If this is the first user message in the chat, derive a title
        from it.  Called from both regular send and chip actions."""
        if self.store.count_messages_by_role(chat_id, "user") == 1:
            title = title_from_first_message(first_text)
            self.store.rename_chat(chat_id, title)
            if chat_id == self.current_chat_id:
                self.chat_title_lbl.set_text(title)
            self._refresh_sidebar()

    def _inject_user_request(self, text: str):
        if self.current_chat_id is None:
            self._new_chat()
        cid = self.current_chat_id
        self.store.add_message(cid, "user", text)
        self._append_message_widget("user", text)
        self._maybe_set_title_from_first(cid, text)

    def _user_action_audit(self):
        if not self._begin_chip_action(): return
        self._inject_user_request("Audit my system and tell me what to fix.")
        self._tool_audit()

    def _user_action_scan(self):
        if not self._begin_chip_action(): return
        self._inject_user_request("Scan the local network.")
        self._tool_scan_net()

    def _user_action_sysinfo(self):
        if not self._begin_chip_action(): return
        self._inject_user_request("Give me a system overview.")
        self._tool_simple(tool_system_info)

    def _user_action_updates(self):
        if not self._begin_chip_action(): return
        self._inject_user_request("What security updates are pending?")
        self._tool_simple(tool_check_updates)

    def _user_action_downloads(self):
        if not self._begin_chip_action(): return
        self._inject_user_request("What's in my Downloads recently?")
        self._tool_simple(lambda: tool_recent_downloads(20))

    def _user_action_camera(self):
        """Capture a photo off-thread, then drop it into the composer as an
        image so it renders and Kali can see it with analyze_image."""
        self._show_toast("Taking a photo…")

        def _bg():
            r = tool_capture_photo()
            GLib.idle_add(lambda: self._finish_camera(r) or False)
        threading.Thread(target=_bg, daemon=True).start()

    def _finish_camera(self, r):
        if not r.get("ok"):
            self._show_toast(r.get("error", "Camera failed"))
            return False
        path = r.get("path", "")
        buf = self.input_view.get_buffer()
        cur = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        ref = f"![photo](file://{path})"
        prompt = "What do you see in this photo?"
        new = (f"{cur}\n{ref}\n{prompt}" if cur.strip()
               else f"{ref}\n{prompt}")
        buf.set_text(new)
        self._show_toast("Photo captured")
        return False

    def _pick_attachment(self):
        # Gtk.FileDialog is GTK 4.10+.  On older Phosh/NetHunter GTK it doesn't
        # exist, so the attach button silently did nothing — fall back to
        # FileChooserNative there so attaching works on every device.
        if hasattr(Gtk, "FileDialog"):
            try:
                dlg = Gtk.FileDialog()
                dlg.set_title("Attach file or image")

                def _cb(d, res):
                    try:
                        f = d.open_finish(res)
                        if f:
                            self._attach_file(f.get_path())
                    except Exception:
                        pass
                dlg.open(self, None, _cb)
                return
            except Exception as e:
                log(f"FileDialog failed, falling back: {e}")
        try:
            chooser = Gtk.FileChooserNative.new(
                "Attach file or image", self,
                Gtk.FileChooserAction.OPEN, "Attach", "Cancel")

            def _resp(c, resp):
                try:
                    if resp == Gtk.ResponseType.ACCEPT:
                        f = c.get_file()
                        if f:
                            self._attach_file(f.get_path())
                finally:
                    c.destroy()
            chooser.connect("response", _resp)
            chooser.show()
        except Exception as e:
            self._show_toast(f"Could not open file picker: {e}")

    # image types Kali can SHOW inline (rendered by ImageWidget)
    _ATTACH_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp",
                          ".bmp", ".svg"}

    def _attach_file(self, path):
        if not path:
            self._show_toast("Could not get file path.")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext in self._ATTACH_IMAGE_EXTS:
            # Embed an image as markdown pointing at the local file, so it
            # renders inline in the chat (ImageWidget handles file:// URLs)
            # instead of being read as binary garbage.
            buf = self.input_view.get_buffer()
            cur = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            name = os.path.basename(path)
            ref = f"![{name}](file://{path})"
            buf.set_text(f"{cur}\n{ref}\n" if cur.strip() else f"{ref}\n")
            self._show_toast(f"Attached image: {name}")
            return
        # Text-like file: read its contents into the message.
        def _bg():
            r = tool_read_file(path, max_bytes=40_000)
            GLib.idle_add(self._finish_attach, path, r)
        threading.Thread(target=_bg, daemon=True).start()

    def _finish_attach(self, path, r):
        if not r.get("ok"):
            self._show_toast(f"Read error: {r.get('error')}")
            return False
        buf = self.input_view.get_buffer()
        cur = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        body = r["content"]
        new = (f"{cur}\n\n[attached: {path}]\n```\n{body}\n```\n"
               if cur else f"[attached: {path}]\n```\n{body}\n```\n")
        buf.set_text(new)
        return False

    # ── history ─────────────────────────────────────────────────

    def _trim_tool_result(self, content: str) -> str:
        """Shrink an older, already-consumed tool_result so a long research
        chat doesn't re-bill the full (sometimes huge) output every turn."""
        if len(content) <= HISTORY_TRIM_HEAD_CHARS + 200:
            return content
        head = content[:HISTORY_TRIM_HEAD_CHARS]
        return (head + f"\n…[earlier tool output trimmed to save tokens — "
                f"{len(content)} chars originally]\n</tool_result>")

    def _next_provider_with_key(self) -> Optional[str]:
        """Pick the next cloud provider (after the current active one) that
        has an API key set — for degraded-output fallback.  Returns None if
        no other configured provider is available."""
        cur = (self.settings.get("active_provider") or "").strip()
        keys = [p.key for p in PROVIDERS]
        if cur in keys:
            order = keys[keys.index(cur) + 1:] + keys[:keys.index(cur)]
        else:
            order = keys
        for k in order:
            if (self.settings.get(f"{k}_api_key") or "").strip():
                return k
        return None

    def _build_history_for_model(self, chat_id: Optional[int] = None):
        out = []
        msgs = self.store.list_messages(chat_id or self.current_chat_id)
        # Keep only the most recent few tool_result blocks at full length;
        # trim older ones (they've already been read and acted on).
        tr_idx = [i for i, m in enumerate(msgs)
                  if m.role == "user"
                  and (m.meta or {}).get("kind") == "tool_result"]
        keep_full = set(tr_idx[-HISTORY_KEEP_FULL_TOOL_RESULTS:]) \
            if HISTORY_KEEP_FULL_TOOL_RESULTS > 0 else set()
        for i, m in enumerate(msgs):
            kind = (m.meta or {}).get("kind")
            if m.role == "user":
                content = m.content
                if kind == "tool_result" and i not in keep_full:
                    content = self._trim_tool_result(content)
                out.append({"role": "user", "content": content})
            elif m.role == "assistant":
                # Don't replay the model's own chain-of-thought back to it —
                # reasoning belongs to the turn that produced it, can be huge,
                # and feeding it back wastes context and can derail the next
                # turn.  Tool tags stay (the model needs to see its prior
                # actions); only <think> blocks are removed.
                out.append({"role": "assistant",
                            "content": strip_think_blocks(m.content)})
            elif m.role == "tool":
                if kind == "result":
                    out.append({"role": "user", "content": m.content})
            elif m.role == "system":
                out.append({"role": "system", "content": m.content})
        return out

    # ── agent toggle ────────────────────────────────────────────

    def _on_agent_toggled(self, btn):
        self.current_agent_mode = btn.get_active()
        if btn.get_active():
            btn.add_css_class("toggled")
        else:
            btn.remove_css_class("toggled")
        if self.current_chat_id is not None:
            self.store.set_agent_mode(self.current_chat_id,
                                       self.current_agent_mode)
        self._refresh_subtitle()

    # ── menu ────────────────────────────────────────────────────

    def _open_settings(self):
        SettingsDialog(self).present(self)

    def _open_about(self):
        about = Adw.AboutDialog()
        about.set_application_name(APP_NAME)
        about.set_version(VERSION)
        about.set_developer_name("The Priest")
        about.set_comments(
            "Personal, loyal AI assistant.\n"
            "Multi-provider cloud AI · lives on your hardware.")
        about.set_license_type(Gtk.License.MIT_X11)
        about.present(self)

    def _rename_current_chat(self):
        if not self.current_chat_id:
            return
        chat = self.store.get_chat(self.current_chat_id)
        if not chat:
            return
        dlg = Adw.AlertDialog.new("Rename chat", "")
        entry = Gtk.Entry()
        entry.set_text(chat.title)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Rename")
        dlg.set_default_response("ok")
        def _cb(d, response):
            if response == "ok":
                new = entry.get_text().strip() or chat.title
                self.store.rename_chat(self.current_chat_id, new)
                self.chat_title_lbl.set_text(new)
                self._refresh_sidebar()
        dlg.connect("response", _cb)
        dlg.present(self)

    def _delete_current_chat(self):
        if not self.current_chat_id:
            return
        dlg = Adw.AlertDialog.new("Delete chat?", "Can't undo.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("delete", "Delete")
        dlg.set_response_appearance("delete",
                                     Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")

        def _cb(d, response):
            if response != "delete":
                return
            deleted_id = self.current_chat_id

            # If the chat being deleted has a turn in flight, cancel it
            # so it doesn't try to write to a now-gone chat row.
            if self.streaming_chat_id == deleted_id:
                if self.streaming_cancel:
                    self.streaming_cancel.set()
                self._stop_requested = True
                self.streaming_msg_widget = None
                self.streaming_msg_db_id = None
                self.streaming_chat_id = None
                self._tool_chain_depth = 0
                self._set_working(False)
                self._set_send_mode(False)

            self.store.delete_chat(deleted_id)
            self.current_chat_id = None

            # Pick the next-most-recent chat to display, if any.  Only
            # spawn a fresh one when there are literally no chats left.
            remaining = self.store.list_chats(limit=1)
            if remaining:
                self._load_chat(remaining[0].id)
            else:
                # No chats at all — clear the view and let the user
                # start fresh whenever they want via the + button.
                child = self.msg_box.get_first_child()
                while child is not None:
                    nxt = child.get_next_sibling()
                    self.msg_box.remove(child)
                    child = nxt
                self.chat_title_lbl.set_text("No chat")
                self.chat_subtitle_lbl.set_text("Tap + to start a new chat")
                self._show_empty_state()

            self._refresh_sidebar()

        dlg.connect("response", _cb)
        dlg.present(self)

    def _toggle_pin_current(self):
        if not self.current_chat_id:
            return
        chat = self.store.get_chat(self.current_chat_id)
        if not chat:
            return
        self.store.set_pinned(self.current_chat_id, not bool(chat.pinned))
        self._refresh_sidebar()

    # ── watcher event handler ──────────────────────────────────

    def _on_watcher_event(self, event):
        # banner appears at top of chat area
        def _ui():
            banner = Gtk.Label()
            banner.add_css_class("watcher-banner")
            banner.set_xalign(0.0)
            banner.set_wrap(True)
            # Escape user-controlled strings (filenames, journal lines)
            # before composing pango markup, or set_markup will reject
            # invalid input and the banner won't render.
            title = GLib.markup_escape_text(event.get("title", ""))
            detail = GLib.markup_escape_text(event.get("detail", ""))
            try:
                banner.set_markup(f"<b>{title}</b>\n{detail}")
            except Exception:
                # Final fallback if markup still fails for any reason
                banner.set_text(f"{event.get('title','')}\n{event.get('detail','')}")
            self.banner_box.append(banner)
            # auto-remove after 15s
            GLib.timeout_add_seconds(15,
                lambda: (self.banner_box.remove(banner)
                          if banner.get_parent() else None) or False)
            return False
        GLib.idle_add(_ui)

    # ── terminal log panel ──────────────────────────────────────

    def _toggle_terminal_panel(self, *_):
        self._terminal_visible = not self._terminal_visible
        self.terminal_panel.set_visible(self._terminal_visible)
        if self._terminal_visible:
            self.terminal_toggle_btn.add_css_class("active")
            GLib.idle_add(self._terminal_scroll_to_bottom)
        else:
            self.terminal_toggle_btn.remove_css_class("active")

    def _clear_terminal_log(self, *_):
        self.terminal_log_buf.set_text("")
        self.terminal_status_lbl.set_text("cleared")

    def _terminal_scroll_to_bottom(self):
        adj = self.terminal_log_view.get_parent()
        if adj is None:
            return False
        try:
            # Walk up to find the ScrolledWindow
            parent = self.terminal_log_view.get_parent()
            while parent and not isinstance(parent, Gtk.ScrolledWindow):
                parent = parent.get_parent()
            if parent:
                a = parent.get_vadjustment()
                if a:
                    a.set_value(a.get_upper())
        except Exception:
            pass
        return False

    def terminal_log(self, text: str, kind: str = "info"):
        """Append a line to the terminal log panel.  Thread-safe via GLib.idle_add."""
        def _ui():
            try:
                buf = self.terminal_log_buf
                end = buf.get_end_iter()
                buf.insert_with_tags_by_name(end, text + "\n", kind)
                self.terminal_status_lbl.set_text(text[:40].strip() or "…")
                GLib.idle_add(self._terminal_scroll_to_bottom)
            except Exception:
                pass
            return False
        GLib.idle_add(_ui)

    def terminal_log_and_show(self, text: str, kind: str = "cmd"):
        """Log and auto-reveal the panel so the operator can see live output."""
        if not self._terminal_visible:
            self._terminal_visible = True
            self.terminal_panel.set_visible(True)
            self.terminal_toggle_btn.add_css_class("active")
        self.terminal_log(text, kind)

    # ── toast ──────────────────────────────────────────────────

    def _show_toast(self, text, timeout=3):
        t = Adw.Toast.new(text)
        t.set_timeout(timeout)
        self.toast_overlay.add_toast(t)
        return False

    # ── shutdown ───────────────────────────────────────────────

    def shutdown(self):
        if self.streaming_cancel:
            self.streaming_cancel.set()
        if getattr(self, "tts", None):
            try:
                self.tts.stop()
            except Exception:
                pass
        if getattr(self, "stt", None):
            try:
                self.stt.cancel()
            except Exception:
                pass
        self.watcher.stop()
        # Bin the open chat if it was never written to.
        if (self.settings.get("discard_empty_chats", True)
                and self.current_chat_id is not None):
            try:
                if self.store.count_messages(self.current_chat_id) == 0:
                    self.store.delete_chat(self.current_chat_id)
            except Exception:
                pass
        try:
            self.store.close()
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════
# APPLICATION
# ═════════════════════════════════════════════════════════════════════

class KaliApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                          flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.win: Optional[MainWindow] = None
        # Hold the CSS provider so we can rebuild it live when the
        # user moves the UI-scale slider in Settings.  Without this
        # the user has to restart Kali to see scale changes.
        self.css_provider: Optional[Gtk.CssProvider] = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.css_provider = Gtk.CssProvider()
        global _UI_SCALE
        _UI_SCALE = _detect_ui_scale()
        # AFTER scale is set, derive viewport-dependent metrics.
        _compute_viewport_metrics()
        self.css_provider.load_from_data(_scale_css(CSS, _UI_SCALE))
        log(f"ui_scale = {_UI_SCALE:.2f}")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK)

    def reload_css(self, scale: float):
        """Apply a new UI scale without restart.  Called from the
        Settings UI-scale slider.  GTK4's CssProvider re-resolves
        styles on widgets when load_from_data is called again, so
        the change is visible immediately."""
        global _UI_SCALE
        if scale and 0.3 < scale < 3:
            _UI_SCALE = float(scale)
        else:
            # 0 (or out-of-range) means "use auto-detect"
            _UI_SCALE = _detect_ui_scale()
        try:
            self.css_provider.load_from_data(_scale_css(CSS, _UI_SCALE))
            log(f"ui_scale reloaded → {_UI_SCALE:.2f}")
        except Exception as e:
            log(f"reload_css failed: {e}")

    def do_activate(self):
        if not self.win:
            self.win = MainWindow(self)
        self.win.present()

    def do_shutdown(self):
        if self.win:
            self.win.shutdown()
        Adw.Application.do_shutdown(self)


def _default_window_size() -> tuple[int, int]:
    """Pick a sensible default window size for the screen we're on.

    The old code hardcoded 440x800 — a portrait phone shape.  On a
    desktop or laptop that opens as a cramped vertical sliver with the
    sidebar eating most of the width.  Instead: go portrait only on an
    actually-narrow screen (phone / Phosh), and open a comfortable
    landscape window on anything bigger, capped so we never exceed the
    monitor's work area.
    """
    # Conservative fallbacks if we can't read the monitor.
    phone = (440, 860)
    desktop = (1100, 760)
    try:
        display = Gdk.Display.get_default()
        if not display:
            return desktop
        monitors = display.get_monitors()
        if monitors is None or monitors.get_n_items() == 0:
            return desktop
        geo = monitors.get_item(0).get_geometry()
        sw, sh = int(geo.width), int(geo.height)
        if sw <= 0 or sh <= 0:
            return desktop

        # Narrow screen → portrait, sized to fit (phones, split panes).
        if sw < 720:
            return (min(sw, phone[0]), min(sh, phone[1]))

        # Desktop / laptop → landscape, but never larger than ~90% of
        # the work area so the window isn't clipped or off-screen.
        w = min(desktop[0], int(sw * 0.72))
        h = min(desktop[1], int(sh * 0.85))
        return (max(760, w), max(560, h))
    except Exception as e:
        log(f"default window size detection failed: {e}")
        return desktop


def _detect_ui_scale() -> float:
    """Pick a UI scale based on physical screen size, not pixel width.

    The old logic compared logical-pixel width to a threshold, but logical
    pixels vary wildly depending on whether the compositor reports device
    pixels (no HiDPI scaling) or scaled application pixels.  A phone with
    1080 device-pixels wide might report as 360 (Phosh, scale=3) OR 1080
    (no scaling).  Both are phones and both need the LARGE UI.

    Use physical mm via width_mm if available — that's the actual screen
    size and doesn't lie.  Fall back to monitor.get_scale_factor() (>1
    means HiDPI which is almost always a phone or tablet) when width_mm
    is 0 (some compositors don't report it).

    Phone (< 100 mm wide)            → 0.9   (slightly smaller than CSS base;
                                              the CSS sizes are already big
                                              enough on the OP6's narrow width)
    Tablet (100-200 mm)              → 1.0
    Laptop (200-350 mm)              → 0.85
    Desktop monitor (> 350 mm)       → 0.7
    """
    # Explicit override always wins
    try:
        s = load_settings().get("ui_scale", 0)
        if isinstance(s, (int, float)) and 0.3 < s < 3:
            log(f"ui_scale from settings: {s}")
            return float(s)
    except Exception:
        pass

    try:
        display = Gdk.Display.get_default()
        if not display:
            return 1.0
        monitors = display.get_monitors()
        if monitors is None or monitors.get_n_items() == 0:
            return 1.0
        monitor = monitors.get_item(0)

        # First try physical width (millimetres)
        try:
            width_mm = int(monitor.get_width_mm())
        except Exception:
            width_mm = 0

        if width_mm > 0:
            if width_mm < 100:
                bucket = "phone"; scale = 0.9
            elif width_mm < 200:
                bucket = "tablet"; scale = 1.0
            elif width_mm < 350:
                bucket = "laptop"; scale = 0.85
            else:
                bucket = "desktop"; scale = 0.7
            log(f"ui_scale: width_mm={width_mm} → {bucket} → {scale}")
            return scale

        # Fall back to scale_factor (HiDPI hint) + geometry
        try:
            sf = int(monitor.get_scale_factor())
        except Exception:
            sf = 1
        geo = monitor.get_geometry()
        # device pixels = logical pixels × scale_factor
        device_w = int(geo.width) * sf

        if sf >= 2 or device_w < 1280:
            # HiDPI compositors (Phosh on a phone) already enlarge text via
            # the scale factor.  Don't double up — use 1.0, let the user
            # dial in further via the Settings slider if they want.
            bucket = "phone/hidpi"; scale = 1.0
        elif device_w < 1920:
            bucket = "laptop"; scale = 0.85
        else:
            bucket = "desktop"; scale = 0.7
        log(f"ui_scale: sf={sf} device_w={device_w} → {bucket} → {scale}")
        return scale

    except Exception as e:
        log(f"ui_scale detection failed: {e} — defaulting to 1.0")
        return 1.0


# Cached UI scale.  Set once in do_startup so widgets created later (avatars,
# buttons) can apply the same scale to their programmatic sizes that the CSS
# uses for fonts/padding.
_UI_SCALE: float = 1.0

# Cached viewport width and derived max-chars for message bubbles.  Set
# from real Gdk geometry in do_startup, used by _make_wrap_label.
_VIEWPORT_WIDTH: int = 540   # OP6 portrait logical width
_MAX_BUBBLE_CHARS: int = 25  # conservative default; recomputed at startup


def _ui_scale() -> float:
    return _UI_SCALE


def _compute_viewport_metrics() -> None:
    """Pin down the actual logical viewport width via Gdk, then derive
    a max-width-chars cap for message labels.  Without a cap that's
    actually narrower than the viewport, Gtk.Label's natural width
    blows the chat bubble out past the right edge of the screen on
    the phone — see the message-bubble bug history."""
    global _VIEWPORT_WIDTH, _MAX_BUBBLE_CHARS
    try:
        display = Gdk.Display.get_default()
        if display:
            mons = display.get_monitors()
            if mons and mons.get_n_items() > 0:
                mon = mons.get_item(0)
                geo = mon.get_geometry()
                _VIEWPORT_WIDTH = max(300, geo.width)
                # Rough char width estimate.  The CSS default message
                # font is 30 px; with a phone UI scale of 0.9 that
                # renders ≈27 px, and avg glyph width is roughly
                # half that → 13-14 px per char.  Leave ~100 px for
                # avatar + margins.
                avail = max(200, _VIEWPORT_WIDTH - 100)
                char_w = max(8.0, 17.0 * _UI_SCALE)
                _MAX_BUBBLE_CHARS = max(15, min(60, int(avail / char_w)))
                log(f"viewport: {_VIEWPORT_WIDTH}px, scale={_UI_SCALE:.2f}"
                    f" → max bubble chars: {_MAX_BUBBLE_CHARS}")
                return
    except Exception as e:
        log(f"viewport detect failed: {e}")


def _scaled(n: int, floor: int = 1) -> int:
    return max(floor, int(round(n * _UI_SCALE)))


_PX_RE = re.compile(r'(\d+)px')


def _scale_css(css_bytes: bytes, scale: float) -> bytes:
    """Multiply every Npx in the CSS by `scale`, with a sane floor so
    border-widths and 1px lines don't disappear."""
    if abs(scale - 1.0) < 0.01:
        return css_bytes
    text = css_bytes.decode("utf-8")
    def repl(m):
        n = int(m.group(1))
        if n <= 2:
            return f"{n}px"   # don't scale 1px/2px borders
        scaled = max(1, int(round(n * scale)))
        return f"{scaled}px"
    return _PX_RE.sub(repl, text).encode("utf-8")


def main():
    try:
        return KaliApp().run(sys.argv)
    except KeyboardInterrupt:
        # Ctrl+C from the terminal: GTK/PyGObject re-raises SIGINT as a
        # KeyboardInterrupt while the main loop unwinds.  Swallow it and
        # exit cleanly — the window is already shutting down by here, so a
        # traceback would just be noise.
        return 0


if __name__ == "__main__":
    sys.exit(main())
