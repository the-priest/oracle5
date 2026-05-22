#!/usr/bin/env python3
"""
kali — local AI assistant.  GTK4 + libadwaita UI.

Run:    python3 kali.py
Or, after install:  kali
"""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Adw, GLib, Gdk, Gio, Pango, GdkPixbuf, GObject  # noqa

import sys
import os
import re
import json
import time
import html
import threading
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from kali_core import (
    OllamaBackend, GroqBackend, BackendRouter, ChatStore, Chat, Message,
    load_settings, save_settings, log,
    tool_read_file, tool_list_dir, tool_run_command, tool_system_info,
    tool_write_file, make_edit_diff,
    tool_check_updates, tool_recent_downloads, tool_service_status,
    tool_journal_tail, tool_disk_usage, tool_processes,
    tool_network_status, tool_find_file,
    run_security_audit, format_audit_for_chat,
    run_network_scan, format_scan_for_chat,
    parse_tool_calls, strip_tool_calls, ToolCall,
    is_online, is_sensitive_path, command_needs_sudo, Watcher,
    DATA_DIR, GROQ_LIB_OK, OLLAMA_DEFAULT_MODEL, GROQ_DEFAULT_MODEL,
)
from kali_persona import (
    build_system_prompt, assemble_messages, title_from_first_message,
)

APP_ID  = "org.thepriest.kali"
APP_NAME = "Kali"
VERSION = "0.4.2"


# ═════════════════════════════════════════════════════════════════════
# THEME — Catppuccin Mocha, generously sized, cozy
# ═════════════════════════════════════════════════════════════════════

# Note: GTK CSS doesn't support CSS variables across rules.  We inline
# the palette by hand and use `font-size` numbers that are large enough
# to read on a phone screen without squinting.

CSS = b"""
/* ===== Base ===== */

window, .background {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Cantarell', 'Inter', 'SF Pro Text', sans-serif;
}

headerbar {
    background-color: #181825;
    color: #cdd6f4;
    border-bottom: 1px solid #313244;
    min-height: 56px;
    padding: 4px 8px;
}

.sidebar {
    background-color: #11111b;
    border-right: 1px solid #313244;
}

/* ===== App branding ===== */

.app-title {
    font-size: 28px;
    font-weight: 900;
    color: #cdd6f4;
    letter-spacing: 0.5px;
}
.app-subtitle {
    font-size: 16px;
    color: #6c7086;
    margin-top: 2px;
}

.chat-title {
    font-size: 24px;
    font-weight: 700;
    color: #cdd6f4;
}
.chat-subtitle {
    font-size: 16px;
    color: #7f849c;
}

/* ===== Sidebar chat list ===== */

.chat-row {
    background-color: transparent;
    border-radius: 14px;
    padding: 20px 22px;
    margin: 6px 8px;
    min-height: 76px;
}
.chat-row:hover {
    background-color: #1e1e2e;
}
.chat-row.selected, .chat-row:selected {
    background-color: #313244;
}
.chat-row .title-line {
    color: #cdd6f4;
    font-weight: 600;
    font-size: 22px;
}
.chat-row .meta-line {
    color: #7f849c;
    font-size: 17px;
    margin-top: 4px;
}
.chat-row .pin-icon {
    color: #f9e2af;
    font-size: 17px;
}

/* ===== Empty states ===== */

.empty-state {
    color: #585b70;
    padding: 60px 32px;
}
.empty-state-title {
    font-size: 34px;
    font-weight: 700;
    color: #cdd6f4;
    margin-bottom: 18px;
}
.empty-state-body {
    font-size: 22px;
    color: #7f849c;
    line-height: 1.55;
}

/* ===== Message bubbles ===== */

.msg-row {
    padding: 4px 0;
}

/* User: right-aligned bubble */
.msg-user {
    background-color: #45475a;
    color: #cdd6f4;
    border-radius: 22px 22px 8px 22px;
    padding: 18px 22px;
    margin: 8px 12px 8px 60px;
    font-size: 30px;
    line-height: 1.45;
}

/* Assistant: left-aligned, transparent, larger text */
.msg-assistant {
    background-color: transparent;
    color: #cdd6f4;
    padding: 12px 18px;
    margin: 8px 12px;
    font-size: 30px;
    line-height: 1.55;
}

/* Compact tool indicator (replaces visible JSON dump) */
.msg-tool-indicator {
    padding: 6px 16px 6px 70px;
    margin: 2px 12px;
}
.tool-indicator-label {
    color: #6c7086;
    font-size: 17px;
    font-style: italic;
    opacity: 0.85;
}

.msg-system-notice {
    color: #6c7086;
    font-style: italic;
    font-size: 18px;
    padding: 8px 16px;
    margin: 4px 16px;
}

/* Avatar dots */
.avatar {
    border-radius: 50%;
    min-width: 52px;
    min-height: 52px;
    background-color: #313244;
    font-weight: bold;
    font-size: 22px;
    color: #cdd6f4;
}
.avatar-user {
    background: linear-gradient(135deg, #89b4fa, #b4befe);
    color: #1e1e2e;
}
.avatar-kali {
    background: linear-gradient(135deg, #cba6f7, #f5c2e7);
    color: #1e1e2e;
}

.role-label {
    color: #7f849c;
    font-weight: 700;
    font-size: 17px;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    margin: 0 0 5px 0;
}
.role-label.user { color: #89b4fa; }
.role-label.kali { color: #cba6f7; }

/* ===== Code blocks ===== */

.code-block {
    background-color: #11111b;
    border: 1px solid #313244;
    border-radius: 10px;
    padding: 0;
    margin: 8px 4px;
}
.code-block-header {
    background-color: #181825;
    color: #7f849c;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
    padding: 6px 12px;
    border-bottom: 1px solid #313244;
    border-radius: 10px 10px 0 0;
}
.code-block textview {
    background-color: transparent;
    color: #f5e0dc;
    font-family: 'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', monospace;
    font-size: 22px;
    padding: 16px 18px;
}

/* ===== Input area ===== */

.input-area {
    background-color: #181825;
    border-top: 1px solid #313244;
    padding: 16px;
}

.input-frame {
    background-color: #313244;
    border-radius: 28px;
    padding: 10px 12px 10px 22px;
    min-height: 68px;
}

.input-frame textview {
    background-color: transparent;
    color: #cdd6f4;
    font-size: 30px;
    padding: 12px 0;
}

.send-button {
    background: linear-gradient(135deg, #cba6f7, #f5c2e7);
    color: #1e1e2e;
    border-radius: 22px;
    min-width: 52px;
    min-height: 52px;
    padding: 0;
    font-weight: bold;
}
.send-button:hover {
    background: linear-gradient(135deg, #b4befe, #cba6f7);
}
.send-button:disabled {
    background: #45475a;
    color: #6c7086;
}
/* Send button morphs into a stop button while Kali is working. */
.send-button.stopping {
    background: linear-gradient(135deg, #f38ba8, #eba0ac);
    color: #1e1e2e;
}
.send-button.stopping:hover {
    background: linear-gradient(135deg, #eba0ac, #f38ba8);
}

/* sudo password field inside the confirm dialog */
.sudo-pass {
    font-size: 20px;
    border-radius: 12px;
    margin-top: 4px;
}
.sudo-pass:focus-within { outline: 2px solid #f38ba8; }

.icon-button {
    background-color: transparent;
    color: #a6adc8;
    border-radius: 14px;
    padding: 12px;
    min-width: 56px;
    min-height: 56px;
}
.icon-button:hover {
    background-color: #313244;
    color: #cdd6f4;
}
.icon-button:disabled {
    color: #45475a;
}
.icon-button.toggled {
    background-color: #cba6f7;
    color: #1e1e2e;
}

/* ===== Status pills ===== */

.status-pill {
    background-color: #313244;
    color: #a6adc8;
    border-radius: 18px;
    padding: 8px 16px;
    font-size: 16px;
    font-weight: bold;
    letter-spacing: 0.5px;
}
.status-pill.online   { background-color: #a6e3a1; color: #1e1e2e; }
.status-pill.offline  { background-color: #45475a; color: #cdd6f4; }
.status-pill.error    { background-color: #f38ba8; color: #1e1e2e; }
.status-pill.groq     { background: linear-gradient(135deg, #cba6f7, #f5c2e7);
                        color: #1e1e2e; }
.status-pill.ollama   { background-color: #fab387; color: #1e1e2e; }

/* ===== Settings ===== */

.settings-section-title {
    color: #cba6f7;
    font-weight: bold;
    font-size: 17px;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 16px 4px 6px 4px;
}

/* ===== Confirm dialog ===== */

.confirm-cmd {
    background-color: #11111b;
    color: #f9e2af;
    font-family: 'JetBrains Mono', monospace;
    font-size: 20px;
    padding: 16px;
    border-radius: 12px;
    margin: 10px 0;
}

/* ===== Scrollbar -- wider for touch ===== */

scrollbar slider {
    background-color: #585b70;
    border-radius: 8px;
    min-width: 16px;
    min-height: 50px;
}
scrollbar slider:hover { background-color: #6c7086; }
scrollbar slider:active { background-color: #7f849c; }

/* ===== Entry ===== */

entry {
    background-color: #313244;
    color: #cdd6f4;
    border-radius: 12px;
    padding: 12px 16px;
    border: none;
    font-size: 20px;
}
entry:focus-within { outline: 2px solid #cba6f7; }

passwordentry {
    background-color: #313244;
    color: #cdd6f4;
    border-radius: 12px;
    padding: 12px 16px;
    border: none;
    font-size: 20px;
}

/* ===== Quick-action chips in empty state ===== */

.quick-chip {
    background-color: #313244;
    color: #cdd6f4;
    border-radius: 22px;
    padding: 14px 24px;
    font-size: 19px;
    min-height: 40px;
}
.quick-chip:hover {
    background-color: #45475a;
    color: #f5e0dc;
}

/* ===== Banner for watcher events ===== */

.watcher-banner {
    background-color: #11111b;
    border-left: 4px solid #f9e2af;
    border-radius: 10px;
    padding: 14px 18px;
    margin: 8px 16px;
    color: #f9e2af;
    font-size: 17px;
}

.working-row {
    background-color: rgba(203, 166, 247, 0.15);
    border-radius: 16px;
    padding: 10px 22px;
}
.working-label {
    color: #cba6f7;
    font-size: 18px;
    font-style: italic;
    font-weight: bold;
    letter-spacing: 0.5px;
}
.working-spinner {
    color: #cba6f7;
    min-width: 24px;
    min-height: 24px;
}

/* ===== Proposed-command card (advisory flow) ===== */

.cmd-card {
    background-color: #181825;
    border: 1px solid #313244;
    border-left: 4px solid #cba6f7;
    border-radius: 14px;
    padding: 14px 16px;
    margin: 8px 0;
}
.cmd-card-header {
    margin-bottom: 8px;
}
.cmd-card-title {
    color: #cba6f7;
    font-weight: bold;
    font-size: 15px;
    letter-spacing: 0.5px;
}
.risk-badge {
    border-radius: 12px;
    padding: 2px 12px;
    font-size: 13px;
    font-weight: bold;
    letter-spacing: 0.5px;
}
.risk-badge.low    { background-color: #a6e3a1; color: #1e1e2e; }
.risk-badge.medium { background-color: #f9e2af; color: #1e1e2e; }
.risk-badge.high   { background-color: #f38ba8; color: #1e1e2e; }
.cmd-text {
    background-color: #11111b;
    color: #f9e2af;
    font-family: 'JetBrains Mono', monospace;
    font-size: 18px;
    padding: 12px 14px;
    border-radius: 10px;
    margin-bottom: 8px;
}
.cmd-explain {
    color: #bac2de;
    font-size: 16px;
    margin-bottom: 12px;
}
.cmd-run-btn {
    background: linear-gradient(135deg, #a6e3a1, #94e2d5);
    color: #1e1e2e;
    border-radius: 12px;
    padding: 10px 22px;
    font-weight: bold;
    font-size: 16px;
}
.cmd-run-btn:hover { background: linear-gradient(135deg, #94e2d5, #a6e3a1); }
.cmd-run-btn:disabled { background: #45475a; color: #6c7086; }
.cmd-copy-btn {
    background-color: #313244;
    color: #cdd6f4;
    border-radius: 12px;
    padding: 10px 18px;
    font-size: 16px;
}
.cmd-copy-btn:hover { background-color: #45475a; }
"""


# ═════════════════════════════════════════════════════════════════════
# MARKDOWN-LITE RENDERING
# ═════════════════════════════════════════════════════════════════════

CODE_FENCE_RE  = re.compile(r"```([a-zA-Z0-9_+-]*)\n?(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
BOLD_RE        = re.compile(r"\*\*([^*\n]+)\*\*")
ITALIC_RE      = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")


def text_to_pango(text: str) -> str:
    safe = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))
    safe = BOLD_RE.sub(r"<b>\1</b>", safe)
    safe = ITALIC_RE.sub(r"<i>\1</i>", safe)
    safe = INLINE_CODE_RE.sub(
        r'<span font_family="JetBrains Mono" '
        r'background="#11111b" foreground="#f5e0dc"> \1 </span>',
        safe)
    return safe


def split_message_into_blocks(text: str) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    last = 0
    for m in CODE_FENCE_RE.finditer(text):
        if m.start() > last:
            pre = text[last:m.start()].strip("\n")
            if pre:
                blocks.append({"kind": "text", "content": pre})
        lang = m.group(1) or "text"
        code = m.group(2).rstrip("\n")
        blocks.append({"kind": "code", "lang": lang, "content": code})
        last = m.end()
    tail = text[last:].strip("\n")
    if tail:
        blocks.append({"kind": "text", "content": tail})
    if not blocks:
        blocks.append({"kind": "text", "content": text})
    return blocks


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
            t_add = buf.create_tag("add", foreground="#a6e3a1")
            t_del = buf.create_tag("del", foreground="#f38ba8")
            t_hdr = buf.create_tag("hdr", foreground="#89b4fa")
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


class Avatar(Gtk.Label):
    """A small circular avatar with initials or symbol."""
    def __init__(self, kind: str = "user"):
        super().__init__()
        self.add_css_class("avatar")
        if kind == "user":
            self.set_text("L")
            self.add_css_class("avatar-user")
        else:
            self.set_text("K")
            self.add_css_class("avatar-kali")
        self.set_valign(Gtk.Align.START)
        size = _scaled(52, floor=28)
        self.set_size_request(size, size)


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
                 on_run_command: Optional[Callable[[str, str], None]] = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.role = role
        self.meta = meta or {}
        self._content = content or ""
        self._on_run_command = on_run_command
        self._blocks_container: Optional[Gtk.Box] = None
        self._streaming_label: Optional[Gtk.Label] = None
        self.add_css_class("msg-row")
        self._build_shell()
        if content and role != "tool":
            self.set_content(content)

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
            label = Gtk.Label(label="KALI", xalign=0.0)
            label.add_css_class("role-label")
            label.add_css_class("kali")
            content_box.append(label)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            inner.add_css_class("msg-assistant")
            content_box.append(inner)
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
        display_text = (strip_tool_calls(text)
                        if self.role == "assistant" else text)
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
                    if call.name == "propose":
                        cmd = (call.args.get("command")
                               or call.args.get("cmd") or "").strip()
                        if not cmd:
                            continue
                        self._blocks_container.append(ProposedCommandWidget(
                            cmd,
                            explanation=str(call.args.get("explanation", "")),
                            risk=str(call.args.get("risk", "medium")),
                            on_run=self._on_run_command))
                    elif call.name in ("propose_edit", "write_file"):
                        # An edit proposal renders as a diff card.  It NEVER
                        # writes on its own — the operator's Apply click is
                        # the approval, and tool_write_file still enforces
                        # the parse-check + backup + immutable-guardrail net.
                        epath = (call.args.get("path") or "").strip()
                        econtent = call.args.get("content")
                        if not epath or econtent is None:
                            continue
                        econtent = str(econtent)
                        try:
                            d = make_edit_diff(epath, econtent)
                        except Exception:
                            d = {"ok": False}
                        self._blocks_container.append(ProposedEditWidget(
                            epath, econtent,
                            diff_lines=d.get("diff") if d.get("ok") else None,
                            added=d.get("added", 0), removed=d.get("removed", 0),
                            is_new=d.get("is_new", False),
                            truncated=d.get("truncated", False),
                            explanation=str(call.args.get("explanation", "")),
                            on_apply=self._run_proposed_edit))
            except Exception as e:
                log(f"propose render failed: {e}")

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
        display = strip_tool_calls(self._content)
        self._streaming_label.set_text(display)

    def finish_streaming(self) -> str:
        final = self._content
        self._streaming_label = None
        self.set_content(final)
        return final


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
                            on_decision: Callable[[bool, Optional[str]], None]):
    """Confirm a shell command.  If it needs sudo, show an inline
    password field so the operator can authenticate in one step.

    on_decision(allow: bool, password: Optional[str]) — password is the
    typed sudo password when the command needs sudo and the operator
    approved; otherwise None.
    """
    needs_sudo = command_needs_sudo(command)
    subtitle = (f"{reason}\n\nRuns as your user.  Output goes back to Kali."
                if not needs_sudo else
                f"{reason}\n\nThis needs root.  Enter your sudo password to "
                f"let it through — Kali never stores or sees it.")
    dlg = Adw.AlertDialog.new("Run shell command?", subtitle)
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
    dlg.add_response("run", "Run" if not needs_sudo else "Authenticate & run")
    dlg.set_response_appearance("run", Adw.ResponseAppearance.SUGGESTED)
    dlg.set_default_response("run")
    dlg.set_close_response("cancel")

    def _cb(_dlg, response):
        allow = (response == "run")
        pw = pw_entry.get_text() if (allow and pw_entry is not None) else None
        on_decision(allow, pw)
    dlg.connect("response", _cb)

    # Pressing Enter in the password field activates the run response.
    if pw_entry is not None:
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

        gg = Adw.PreferencesGroup()
        gg.set_title("Groq (cloud, primary)")
        gg.set_description(
            "Used when online + API key set.  Get a free key at "
            "console.groq.com.")

        self.groq_key_row = Adw.PasswordEntryRow()
        self.groq_key_row.set_title("API key")
        self.groq_key_row.set_text(parent.settings.get("groq_api_key", ""))
        self.groq_key_row.connect("changed", self._on_groq_key)
        gg.add(self.groq_key_row)

        self.groq_model_row = Adw.EntryRow()
        self.groq_model_row.set_title("Default model")
        self.groq_model_row.set_text(parent.settings.get("groq_model",
                                                          GROQ_DEFAULT_MODEL))
        self.groq_model_row.connect("changed", self._on_groq_model)
        gg.add(self.groq_model_row)

        self.prefer_groq_row = Adw.SwitchRow()
        self.prefer_groq_row.set_title("Prefer Groq over Ollama")
        self.prefer_groq_row.set_subtitle(
            "When online with a key.  Off = always use local.")
        self.prefer_groq_row.set_active(parent.settings.get("prefer_groq", True))
        self.prefer_groq_row.connect("notify::active", self._on_prefer_groq)
        gg.add(self.prefer_groq_row)
        page.add(gg)

        og = Adw.PreferencesGroup()
        og.set_title("Ollama (local, fallback)")

        self.ollama_model_row = Adw.ComboRow()
        self.ollama_model_row.set_title("Fallback model")
        self._populate_ollama_models()
        og.add(self.ollama_model_row)

        self.autostart_row = Adw.SwitchRow()
        self.autostart_row.set_title("Auto-start ollama serve")
        self.autostart_row.set_active(parent.settings["auto_start_ollama"])
        self.autostart_row.connect("notify::active", self._on_autostart)
        og.add(self.autostart_row)

        self.stop_on_quit_row = Adw.SwitchRow()
        self.stop_on_quit_row.set_title("Stop ollama on app quit")
        self.stop_on_quit_row.set_active(parent.settings["stop_ollama_on_quit"])
        self.stop_on_quit_row.connect("notify::active", self._on_stop_quit)
        og.add(self.stop_on_quit_row)
        page.add(og)

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

        ctx_row = Adw.SpinRow.new_with_range(512, 32768, 512)
        ctx_row.set_title("Local context window")
        ctx_row.set_subtitle("For the Ollama backend only.")
        ctx_row.set_value(parent.settings["num_ctx"])
        ctx_row.connect("notify::value", self._on_ctx)
        gen_g.add(ctx_row)

        max_row = Adw.SpinRow.new_with_range(256, 8192, 128)
        max_row.set_title("Max response tokens")
        max_row.set_value(parent.settings["max_tokens"])
        max_row.connect("notify::value", self._on_max)
        gen_g.add(max_row)

        gen_page.add(gen_g)
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
            "Off = only risky commands prompt.")
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
        self.add(b_page)

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

    def _set(self, key, value):
        self.win.settings[key] = value
        save_settings(self.win.settings)

    def _populate_ollama_models(self):
        models = self.win.ollama.list_models()
        names = [m["name"] for m in models] if models else []
        if not names:
            names = ["(no models — pull one with: ollama pull llama3.2:1b)"]
        sl = Gtk.StringList.new(names)
        self.ollama_model_row.set_model(sl)
        current = self.win.settings.get("ollama_model", "")
        if current in names:
            self.ollama_model_row.set_selected(names.index(current))
        self.ollama_model_row.connect("notify::selected", self._on_ollama_model)

    def _on_groq_key(self, row):
        self.win.settings["groq_api_key"] = row.get_text()
        save_settings(self.win.settings)
        self.win.groq.set_api_key(row.get_text())
        self.win.update_status_pills()

    def _on_groq_model(self, row):
        self.win.settings["groq_model"] = row.get_text()
        save_settings(self.win.settings)

    def _on_prefer_groq(self, row, _ps):
        self.win.settings["prefer_groq"] = row.get_active()
        save_settings(self.win.settings)
        self.win.update_status_pills()

    def _on_ollama_model(self, row, _ps):
        m = row.get_model()
        idx = row.get_selected()
        if m and idx < m.get_n_items():
            name = m.get_string(idx)
            if not name.startswith("("):
                self.win.settings["ollama_model"] = name
                save_settings(self.win.settings)

    def _on_temp(self, row, *args):
        self._set("temperature", float(row.get_value()))

    def _on_ctx(self, row, *args):
        self._set("num_ctx", int(row.get_value()))

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

    def _on_autostart(self, row, _ps):
        self._set("auto_start_ollama", row.get_active())

    def _on_stop_quit(self, row, _ps):
        self._set("stop_ollama_on_quit", row.get_active())

    def _on_watcher_enable(self, row, _ps):
        self._set("watcher_enabled", row.get_active())
        if row.get_active():
            self.win.watcher.start()
        else:
            self.win.watcher.stop()

    def _on_sp_changed(self, buf):
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self._set("system_prompt", text)


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
        self.ollama = OllamaBackend()
        self.groq = GroqBackend(self.settings.get("groq_api_key", ""))
        self.router = BackendRouter(self.groq, self.ollama, self.settings)
        self.store = ChatStore()
        self.watcher = Watcher(self.settings, self._on_watcher_event)

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
        # Set when the operator hits the stop button.  Halts the current
        # stream AND prevents the tool chain from kicking another turn.
        self._stop_requested: bool = False

        self._build_ui()
        self._wire_actions()
        self._boot()
        GLib.idle_add(self._initial_chat_load)
        GLib.idle_add(self._refresh_sidebar)

    def _initial_chat_load(self):
        """At launch, open the most recent chat if any exist; otherwise
        start with a fresh one.  Previously we always called _new_chat
        which spawned an empty 'New chat' every single launch — the
        sidebar filled up with placeholders over time."""
        chats = self.store.list_chats(limit=1)
        if chats:
            self._load_chat(chats[0].id)
        else:
            self._new_chat()
        return False

    # ── boot ────────────────────────────────────────────────────

    def _boot(self):
        def _bg():
            if self.settings.get("auto_start_ollama", True):
                if not self.ollama.is_running():
                    log("Starting ollama serve...")
                    self.ollama.start_serve()
            GLib.idle_add(self.update_status_pills)
            if self.settings.get("watcher_enabled"):
                self.watcher.start()
        threading.Thread(target=_bg, daemon=True).start()

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
                Adw.BreakpointCondition.parse("max-width: 600px"))
            bp.add_setter(self.split, "collapsed", True)
            self.add_breakpoint(bp)
        except Exception as e:
            log(f"breakpoint unavailable, using static collapse: {e}")
            # Detect narrow screen via Gdk directly so we don't depend on
            # UI scale (which is about font sizes, not screen geometry).
            try:
                display = Gdk.Display.get_default()
                mon = display.get_monitors().get_item(0) if display else None
                if mon:
                    geo = mon.get_geometry()
                    if geo.width < 700:
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

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        t = Gtk.Label(label=APP_NAME, xalign=0.0)
        t.add_css_class("app-title")
        st = Gtk.Label(label="local · loyal · yours", xalign=0.0)
        st.add_css_class("app-subtitle")
        title_box.append(t)
        title_box.append(st)
        sb_header.set_title_widget(title_box)

        new_btn = Gtk.Button.new_from_icon_name("document-new-symbolic")
        new_btn.set_tooltip_text("New chat")
        new_btn.add_css_class("icon-button")
        new_btn.connect("clicked", lambda *_: self._new_chat())
        sb_header.pack_end(new_btn)
        sb.append(sb_header)

        # Search
        sw_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        sw_box.set_margin_start(12)
        sw_box.set_margin_end(12)
        sw_box.set_margin_top(8)
        sw_box.set_margin_bottom(8)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("search chats…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search)
        sw_box.append(self.search_entry)
        sb.append(sw_box)

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
        sb_toggle.add_css_class("icon-button")
        sb_toggle.set_tooltip_text("Toggle sidebar")
        sb_toggle.connect("clicked", lambda *_:
                          self.split.set_show_sidebar(
                              not self.split.get_show_sidebar()))
        hb.pack_start(sb_toggle)

        self.title_widget_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                         spacing=0)
        self.chat_title_lbl = Gtk.Label(label="New chat", xalign=0.5)
        self.chat_title_lbl.add_css_class("chat-title")
        self.chat_subtitle_lbl = Gtk.Label(label="", xalign=0.5)
        self.chat_subtitle_lbl.add_css_class("chat-subtitle")
        self.title_widget_box.append(self.chat_title_lbl)
        self.title_widget_box.append(self.chat_subtitle_lbl)
        hb.set_title_widget(self.title_widget_box)

        # Status pills
        pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.provider_pill = Gtk.Label(label="…")
        self.provider_pill.add_css_class("status-pill")
        pill_box.append(self.provider_pill)
        self.online_pill = Gtk.Label(label="…")
        self.online_pill.add_css_class("status-pill")
        pill_box.append(self.online_pill)
        hb.pack_end(pill_box)

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
        main.append(self.msg_scroll)

        main.append(self._build_input_area())
        return main

    def _build_input_area(self):
        area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        area.add_css_class("input-area")

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
        ]:
            btn = Gtk.Button.new_from_icon_name(icon)
            btn.add_css_class("icon-button")
            btn.set_tooltip_text(tip)
            btn.connect("clicked", lambda *_, c=cb: c())
            actions.append(btn)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        actions.append(spacer)

        area.append(actions)

        # Input
        ibox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ibox.add_css_class("input-frame")
        ibox.set_margin_start(4)
        ibox.set_margin_end(4)

        in_scroll = Gtk.ScrolledWindow()
        in_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        in_scroll.set_min_content_height(_scaled(40, floor=28))
        in_scroll.set_max_content_height(_scaled(220, floor=120))
        in_scroll.set_propagate_natural_height(True)
        in_scroll.set_hexpand(True)

        self.input_view = Gtk.TextView()
        self.input_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.input_view.set_top_margin(6)
        self.input_view.set_bottom_margin(6)
        in_scroll.set_child(self.input_view)
        ibox.append(in_scroll)

        kc = Gtk.EventControllerKey()
        kc.connect("key-pressed", self._on_input_key)
        self.input_view.add_controller(kc)

        self.send_btn = Gtk.Button()
        self.send_btn.set_icon_name("send-to-symbolic")
        self.send_btn.add_css_class("send-button")
        self.send_btn.set_valign(Gtk.Align.END)
        self.send_btn.set_tooltip_text("Send")
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
        # Provider pill
        if self.groq.is_available() and self.settings.get("prefer_groq", True):
            self.provider_pill.set_text("GROQ")
            for c in ("ollama", "offline", "error"):
                self.provider_pill.remove_css_class(c)
            self.provider_pill.add_css_class("groq")
        elif self.ollama.is_running():
            self.provider_pill.set_text("LOCAL")
            for c in ("groq", "offline", "error"):
                self.provider_pill.remove_css_class(c)
            self.provider_pill.add_css_class("ollama")
        else:
            self.provider_pill.set_text("NO BACKEND")
            for c in ("groq", "ollama", "offline"):
                self.provider_pill.remove_css_class(c)
            self.provider_pill.add_css_class("error")

        # Online pill
        if online is None:
            online = is_online(max_age=15)
        if online:
            self.online_pill.set_text("ONLINE")
            self.online_pill.remove_css_class("offline")
            self.online_pill.add_css_class("online")
        else:
            self.online_pill.set_text("OFFLINE")
            self.online_pill.remove_css_class("online")
            self.online_pill.add_css_class("offline")
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
        popover.set_parent(row)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.popup()

    # ── chat load / new ─────────────────────────────────────────

    def _new_chat(self):
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
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        wrap.set_halign(Gtk.Align.CENTER)
        wrap.set_valign(Gtk.Align.CENTER)
        wrap.set_margin_top(80)
        wrap.set_margin_bottom(40)
        wrap.set_margin_start(24)
        wrap.set_margin_end(24)

        title = Gtk.Label(label=f"Hello, Priest.")
        title.add_css_class("empty-state-title")
        wrap.append(title)

        body = Gtk.Label()
        body.set_markup(
            "Ask me something.  Or hit a button below to put me to work.\n\n"
            "Try: <i>audit my system</i>, <i>what's in my Downloads</i>, "
            "<i>any security updates</i>")
        body.add_css_class("empty-state-body")
        body.set_justify(Gtk.Justification.CENTER)
        body.set_wrap(True)
        body.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        body.set_max_width_chars(50)
        wrap.append(body)

        chips_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        chips_row.set_halign(Gtk.Align.CENTER)
        for label, cb in [
            ("Audit my system", self._user_action_audit),
            ("Recent downloads", self._user_action_downloads),
            ("Pending updates", self._user_action_updates),
        ]:
            chip = Gtk.Button(label=label)
            chip.add_css_class("quick-chip")
            chip.connect("clicked", lambda *_, c=cb: c())
            chips_row.append(chip)
        wrap.append(chips_row)

        self.msg_box.append(wrap)

    def _refresh_subtitle(self):
        bits = []
        backend, model = self.router.pick()
        bits.append(f"{backend.name}: {model.split('/')[-1]}")
        if self.current_agent_mode:
            bits.append("agent")
        self.chat_subtitle_lbl.set_text("   ·   ".join(bits))

    # ── messages ────────────────────────────────────────────────

    def _append_message_widget(self, role, content, meta=None):
        # Clear empty state if present
        first = self.msg_box.get_first_child()
        if first is not None and not isinstance(first, MessageWidget):
            self.msg_box.remove(first)
        w = MessageWidget(role, content, meta,
                          on_run_command=self._run_proposed_command)
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
        """Morph the primary button between Send and Stop."""
        if working:
            self.send_btn.set_icon_name("media-playback-stop-symbolic")
            self.send_btn.set_tooltip_text("Stop")
            self.send_btn.add_css_class("stopping")
        else:
            self.send_btn.set_icon_name("send-to-symbolic")
            self.send_btn.set_tooltip_text("Send")
            self.send_btn.remove_css_class("stopping")
        self.send_btn.set_sensitive(True)

    def _request_stop(self):
        """Operator pressed Stop.  Cancel the in-flight stream and make
        sure the tool chain doesn't kick another turn behind our back."""
        self._stop_requested = True
        if self.streaming_cancel:
            self.streaming_cancel.set()
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
        self._set_working(False)
        self._set_send_mode(False)

    def _send_user_message(self):
        if self._is_busy():
            self._show_toast("Already replying — hit stop first.")
            return
        # Fresh turn — clear any leftover stop flag.
        self._stop_requested = False
        buf = self.input_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(),
                            False).strip()
        if not text:
            return
        buf.set_text("")

        if self.current_chat_id is None:
            self._new_chat()
        cid = self.current_chat_id
        self.store.add_message(cid, "user", text)
        self._append_message_widget("user", text)
        self._maybe_set_title_from_first(cid, text)

        self._kick_assistant_turn()

    def _set_working(self, working: bool, label: str = "working…"):
        """Show or hide the 'working' spinner banner.  Called from the
        UI thread."""
        if working:
            self.working_label.set_text(label)
            self.working_spinner.start()
            self.working_row.set_visible(True)
        else:
            self.working_spinner.stop()
            self.working_row.set_visible(False)

    def _kick_assistant_turn(self):
        # If the operator hit stop between tool turns, don't start another.
        if self._stop_requested:
            self._finish_turn_cleanup()
            return

        if not self.ollama.is_running() and not self.groq.is_available():
            self._show_toast(
                "No backend.  Set a Groq key in Settings, or start Ollama.")
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

        # Safety: limit how many tool calls can chain in a row to keep a
        # buggy model from spinning forever.
        self._tool_chain_depth += 1
        if self._tool_chain_depth > 8:
            self._show_toast("Tool chain too long — stopping.")
            self.streaming_chat_id = None
            self._tool_chain_depth = 0
            self._set_working(False)
            self._set_send_mode(False)
            return

        chat_id = self.streaming_chat_id

        history = self._build_history_for_model(chat_id)
        sysprompt = build_system_prompt(
            agent_mode=self.current_agent_mode,
            custom_addendum=self.settings.get("system_prompt", ""))
        full = assemble_messages(sysprompt, history)

        # Only show the streaming widget if user is looking at this chat
        if chat_id == self.current_chat_id:
            self.streaming_msg_widget = self._append_message_widget(
                "assistant", "")
            self.streaming_msg_widget.start_streaming()
        else:
            # User has navigated away.  We still need a widget to buffer
            # tokens for finish_streaming, but don't attach it to msg_box.
            self.streaming_msg_widget = MessageWidget(
                "assistant", "", on_run_command=self._run_proposed_command)
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

        def _bg():
            self.router.stream_chat(full, _on_tok, _on_done, _on_err,
                                    self.streaming_cancel)

        self.streaming_thread = threading.Thread(target=_bg, daemon=True)
        self.streaming_thread.start()
        self._set_send_mode(True)
        self._set_working(True, "thinking…")

    def _on_stream_token(self, tok):
        if self.streaming_msg_widget:
            self.streaming_msg_widget.append_streaming(tok)
            # Only scroll if user is on the chat that owns this stream
            if self.streaming_chat_id == self.current_chat_id:
                self._scroll_to_bottom()
        return False

    def _on_stream_done(self, meta):
        if not self.streaming_msg_widget:
            self._finish_turn_cleanup()
            return False
        final = self.streaming_msg_widget.finish_streaming()
        if self.streaming_msg_db_id:
            self.store.update_message(self.streaming_msg_db_id, final)
        calls = parse_tool_calls(final)
        cancelled = meta.get("cancelled") or self._stop_requested
        # `propose` is advisory — it renders a command card (already done by
        # finish_streaming → set_content) and must NOT execute.  Only the
        # sensing/run tools are executable here.
        executable = [c for c in calls if c.name != "propose"]
        # Honour the agent-mode toggle and the stop button.  If the user
        # turned agent mode off or hit stop, don't execute even if the
        # model emitted a tool tag.
        if executable and not cancelled and self.current_agent_mode:
            # Tool will fire — keep banner, change label to "running"
            self._set_working(True, "running tool…")
            self._execute_tool_calls(executable)
        else:
            self._finish_turn_cleanup()
        return False

    def _on_stream_error(self, err):
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
        self._set_working(False)
        self._set_send_mode(False)
        return False

    # ── tool execution ──────────────────────────────────────────

    def _execute_tool_calls(self, calls):
        call = calls[0]
        # `propose` and `propose_edit` are advisory — the card (command or
        # diff) already rendered and carries its own Run/Apply button.
        # They never execute here; if one slips through, end the turn so
        # the card stands on its own.
        if call.name in ("propose", "propose_edit", "write_file"):
            self._finish_turn_cleanup()
            return
        # Always write to the chat this turn was started in, not whichever
        # one the user might have navigated to.
        chat_id = self.streaming_chat_id or self.current_chat_id

        # Update the working banner with the specific tool name so user
        # knows what's happening.  Hidden tool indicators in the message
        # stream stay hidden — they're noisy.
        self._set_working(True, f"running {call.name}…")

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
                a.get("pattern", "*"), a.get("search_path", "~")),
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
        }
        fn = dispatch.get(call.name)
        if fn:
            fn(call.args)
        else:
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

    def _tool_simple(self, fn):
        def _bg():
            try:
                result = fn()
                text = json.dumps(result, indent=2, default=str)
            except Exception as e:
                text = f"error: {e}"
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

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
            r = tool_list_dir(path)
            if not r.get("ok"):
                text = f"list_dir error: {r.get('error')}"
            else:
                lines = [f"dir: {r['path']}", ""]
                for e in r["entries"]:
                    sz = "" if e["is_dir"] else f"  ({e['size']}B)"
                    lines.append(f"  {e['name']}{sz}")
                text = "\n".join(lines)
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

    def _tool_find_file(self, pattern, search_path):
        def _bg():
            r = tool_find_file(pattern, search_path)
            if r.get("ok"):
                text = (f"find {pattern} in {r['search_path']}: "
                        f"{r['count']} hit(s)\n" + "\n".join(r["found"]))
            else:
                text = f"find_file error: {r.get('error')}"
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

    def _tool_run(self, command, reason):
        # Reached only when the model emits <tool name="run"> after the
        # operator approved.  Goes through the same gate as the card.
        self._execute_command(command, reason)

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
                    parts.append("Python syntax was checked before writing. "
                                 "If this was a core Kali file, relaunch to "
                                 "load the new code.")
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
                r = tool_run_command(command, timeout=timeout,
                                     sudo_password=password)
                if r.get("ok"):
                    parts = [f"$ {command}", f"(rc={r['rc']})"]
                    if r["stdout"]:
                        parts.append(r["stdout"])
                    if r["stderr"]:
                        parts.append(f"stderr:\n{r['stderr']}")
                    if r.get("sudo_auth_failed"):
                        parts.append(
                            "\n[note] sudo could not authenticate "
                            "non-interactively. The password may have been "
                            "wrong, or sudo timed out its cached credential.")
                    out = "\n".join(parts)
                else:
                    out = f"$ {command}\nerror: {r.get('error')}"
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
        needs_confirm = command_needs_sudo(command) or (
            self.settings.get("confirm_all_commands", True) and not from_card)
        if needs_confirm:
            confirm_command_dialog(self, command, reason or "no reason", decide)
        else:
            run_bg(None)

    def _tool_audit(self):
        self._show_toast("Auditing…")
        def _bg():
            try:
                audit = run_security_audit()
                text = format_audit_for_chat(audit)
            except Exception as e:
                text = f"audit failed: {type(e).__name__}: {e}"
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

    def _tool_scan_net(self, cidr=None):
        self._show_toast("Scanning network…")
        def _bg():
            try:
                scan = run_network_scan(cidr)
                text = format_scan_for_chat(scan)
            except Exception as e:
                text = f"scan failed: {type(e).__name__}: {e}"
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

    def _pick_attachment(self):
        dlg = Gtk.FileDialog()
        dlg.set_title("Attach file")
        def _cb(d, res):
            try:
                f = d.open_finish(res)
                if f:
                    self._attach_file(f.get_path())
            except Exception:
                pass
        dlg.open(self, None, _cb)

    def _attach_file(self, path):
        if not path:
            self._show_toast("Could not get file path.")
            return
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

    def _build_history_for_model(self, chat_id: Optional[int] = None):
        out = []
        msgs = self.store.list_messages(chat_id or self.current_chat_id)
        for m in msgs:
            kind = (m.meta or {}).get("kind")
            if m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                out.append({"role": "assistant", "content": m.content})
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
            "Local, loyal AI assistant.\n"
            "Groq primary · Ollama fallback · lives on your hardware.")
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
        self.watcher.stop()
        if self.settings.get("stop_ollama_on_quit", True):
            self.ollama.stop_serve()
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
    return KaliApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
