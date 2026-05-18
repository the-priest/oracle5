#!/usr/bin/env python3
"""
oracle — local AI assistant.  GTK4 + libadwaita UI.

Run:    python3 oracle.py
Or, after install:  oracle

Architecture lives in oracle_core.py and oracle_persona.py.
This file is UI only — windows, widgets, threading.

(File is named oracle.py historically; the visible app name is Oracle.
 Rename freely.)
"""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Adw, GLib, Gdk, Gio, Pango  # noqa: E402

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

from oracle_core import (
    OllamaManager, ChatStore, Chat, Message,
    load_settings, save_settings, log,
    tool_read_file, tool_list_dir, tool_run_command, tool_system_info,
    run_security_audit, format_audit_for_chat,
    run_network_scan, format_scan_for_chat,
    parse_tool_calls, strip_tool_calls, ToolCall,
    is_online, is_sensitive_path,
)
from oracle_persona import (
    build_system_prompt, assemble_messages, title_from_first_message,
)

APP_ID  = "org.thepriest.oracle"
APP_NAME = "Oracle"
VERSION = "0.1"


# ═════════════════════════════════════════════════════════════════════
# THEME — Catppuccin Mocha, same palette as NetStrike for consistency
# ═════════════════════════════════════════════════════════════════════

CSS = b"""
/* --- base --- */

window, .background {
    background-color: #1e1e2e;
    color: #cdd6f4;
}

headerbar {
    background-color: #181825;
    color: #cdd6f4;
    border-bottom: 1px solid #313244;
    min-height: 44px;
}

headerbar .title {
    color: #cdd6f4;
    font-weight: bold;
}

.sidebar {
    background-color: #181825;
    border-right: 1px solid #313244;
}

/* --- sidebar list --- */

.chat-row {
    background-color: transparent;
    border-radius: 8px;
    padding: 8px 10px;
    margin: 2px 4px;
}
.chat-row:hover {
    background-color: #313244;
}
.chat-row.selected, .chat-row:selected {
    background-color: #45475a;
}
.chat-row .title-line {
    color: #cdd6f4;
    font-weight: 600;
    font-size: 13px;
}
.chat-row .meta-line {
    color: #6c7086;
    font-size: 10px;
}
.chat-row .pin-icon {
    color: #f9e2af;
    font-size: 11px;
}

/* --- empty states --- */

.empty-state {
    color: #585b70;
    font-style: italic;
    padding: 40px 24px;
    font-size: 13px;
}

/* --- message bubbles --- */

.msg-user {
    background-color: #313244;
    color: #cdd6f4;
    border-radius: 14px 14px 4px 14px;
    padding: 10px 14px;
    margin: 4px 8px 4px 60px;
}

.msg-assistant {
    background-color: transparent;
    color: #cdd6f4;
    padding: 6px 12px;
    margin: 4px 8px;
}

.msg-tool-call {
    background-color: #11111b;
    border: 1px solid #313244;
    border-radius: 8px;
    padding: 8px 12px;
    margin: 4px 12px 4px 12px;
    color: #f5c2e7;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 11px;
}

.msg-tool-result {
    background-color: #11111b;
    border: 1px solid #313244;
    border-radius: 8px;
    padding: 8px 12px;
    margin: 4px 12px 8px 12px;
    color: #94e2d5;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 11px;
}

.msg-system-notice {
    color: #6c7086;
    font-style: italic;
    font-size: 11px;
    padding: 4px 12px;
    margin: 0 12px;
}

.role-label-user {
    color: #89b4fa;
    font-weight: bold;
    font-size: 10px;
    margin: 0 12px;
}
.role-label-assistant {
    color: #cba6f7;
    font-weight: bold;
    font-size: 10px;
    margin: 0 12px;
}

/* --- code blocks --- */

.code-block {
    background-color: #11111b;
    border: 1px solid #313244;
    border-radius: 8px;
    padding: 10px 12px;
    margin: 6px 8px;
}
.code-block textview {
    background-color: transparent;
    color: #f5e0dc;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 12px;
}
.code-block-header {
    color: #6c7086;
    font-size: 10px;
    font-family: 'JetBrains Mono', monospace;
    padding: 0 0 4px 0;
}

/* --- input area --- */

.input-area {
    background-color: #181825;
    border-top: 1px solid #313244;
    padding: 8px;
}

.input-frame {
    background-color: #313244;
    border-radius: 18px;
    padding: 4px 4px 4px 12px;
}

.input-frame textview {
    background-color: transparent;
    color: #cdd6f4;
    font-size: 14px;
    padding: 6px 0;
}

.send-button {
    background: linear-gradient(135deg, #89b4fa, #b4befe);
    color: #1e1e2e;
    border-radius: 16px;
    min-width: 32px;
    min-height: 32px;
    padding: 0;
    font-weight: bold;
}
.send-button:hover { opacity: 0.9; }
.send-button:disabled {
    background: #45475a;
    color: #6c7086;
}

.icon-button {
    background-color: transparent;
    color: #a6adc8;
    border-radius: 8px;
    padding: 6px;
    min-width: 32px;
    min-height: 32px;
}
.icon-button:hover {
    background-color: #45475a;
    color: #cdd6f4;
}
.icon-button:disabled {
    color: #45475a;
}
.icon-button.toggled {
    background-color: #cba6f7;
    color: #1e1e2e;
}

/* --- header pieces --- */

.status-pill {
    background-color: #313244;
    color: #a6adc8;
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 10px;
    font-weight: bold;
}
.status-pill.online {
    background-color: #a6e3a1;
    color: #1e1e2e;
}
.status-pill.offline {
    background-color: #45475a;
    color: #cdd6f4;
}
.status-pill.error {
    background-color: #f38ba8;
    color: #1e1e2e;
}

.app-title {
    font-size: 16px;
    font-weight: 900;
    color: #cdd6f4;
}
.app-subtitle {
    font-size: 10px;
    color: #6c7086;
}

/* --- settings --- */

.settings-section-title {
    color: #cba6f7;
    font-weight: bold;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 12px 4px 4px 4px;
}

/* --- danger button (delete chat) --- */

.danger {
    color: #f38ba8;
}
.danger:hover {
    background-color: rgba(243, 139, 168, 0.15);
}

/* --- search --- */

searchbar {
    background-color: #181825;
}
entry {
    background-color: #313244;
    color: #cdd6f4;
    border-radius: 8px;
    padding: 6px 10px;
    border: none;
}
entry:focus { outline: 2px solid #cba6f7; }

/* --- modal cards --- */

.confirm-card {
    background-color: #181825;
    border-radius: 12px;
    padding: 16px;
}
.confirm-cmd {
    background-color: #11111b;
    color: #f9e2af;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    padding: 10px;
    border-radius: 8px;
    margin: 8px 0;
}

/* --- scrollbar --- */

scrollbar slider {
    background-color: #45475a;
    border-radius: 4px;
    min-width: 6px;
}
scrollbar slider:hover { background-color: #585b70; }
"""


# ═════════════════════════════════════════════════════════════════════
# MARKDOWN-ISH RENDERING — split text into prose + code blocks
# ═════════════════════════════════════════════════════════════════════

CODE_FENCE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n?(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")


def text_to_pango(text: str) -> str:
    """Convert a small subset of markdown to Pango markup (escaped)."""
    # Escape pango special chars FIRST
    safe = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))
    # Then apply markup on the escaped text
    safe = BOLD_RE.sub(r"<b>\1</b>", safe)
    safe = ITALIC_RE.sub(r"<i>\1</i>", safe)
    safe = INLINE_CODE_RE.sub(
        r'<span font_family="JetBrains Mono" '
        r'background="#11111b" foreground="#f5e0dc"> \1 </span>',
        safe)
    return safe


def split_message_into_blocks(text: str) -> List[Dict[str, str]]:
    """
    Returns list of dicts:
        {"kind": "text", "content": "..."}
        {"kind": "code", "lang": "python", "content": "..."}
    """
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
    """A styled monospace block with copy button."""

    def __init__(self, code: str, lang: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("code-block")
        self.code = code

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl = Gtk.Label(label=lang or "code", xalign=0.0, hexpand=True)
        lbl.add_css_class("code-block-header")
        header.append(lbl)

        copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_btn.add_css_class("icon-button")
        copy_btn.set_tooltip_text("Copy")
        copy_btn.connect("clicked", self._on_copy)
        header.append(copy_btn)
        self.append(header)

        # TextView — read-only, selectable
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
        clip = self.get_clipboard()
        clip.set(self.code)


class MessageWidget(Gtk.Box):
    """A single chat message (user / assistant / tool / notice)."""

    def __init__(self, role: str, content: str = "",
                 meta: Optional[Dict[str, Any]] = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.role = role
        self.meta = meta or {}
        self._content = ""
        self._blocks_container: Optional[Gtk.Box] = None
        self._streaming_label: Optional[Gtk.Label] = None
        self._build_shell()
        if content:
            self.set_content(content)

    def _build_shell(self):
        if self.role == "user":
            role_lbl = Gtk.Label(label="YOU", xalign=1.0)
            role_lbl.add_css_class("role-label-user")
            self.append(role_lbl)
            self._inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                  spacing=4)
            self._inner.add_css_class("msg-user")
            self._inner.set_halign(Gtk.Align.END)
            self.append(self._inner)
            self._blocks_container = self._inner

        elif self.role == "assistant":
            role_lbl = Gtk.Label(label="ORACLE", xalign=0.0)
            role_lbl.add_css_class("role-label-assistant")
            self.append(role_lbl)
            self._inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                  spacing=4)
            self._inner.add_css_class("msg-assistant")
            self.append(self._inner)
            self._blocks_container = self._inner

        elif self.role == "tool":
            # tool result / call display
            self._inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                  spacing=2)
            kind = self.meta.get("kind", "result")
            css = "msg-tool-call" if kind == "call" else "msg-tool-result"
            self._inner.add_css_class(css)
            self.append(self._inner)
            self._blocks_container = self._inner

        else:  # system / notice
            self._inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=4)
            self._inner.add_css_class("msg-system-notice")
            self.append(self._inner)
            self._blocks_container = self._inner

    def set_content(self, text: str):
        """Set / replace the content with full block rendering."""
        self._content = text
        # Clear existing children
        child = self._blocks_container.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._blocks_container.remove(child)
            child = nxt
        # Don't render tool tags as prose
        display_text = strip_tool_calls(text) if self.role == "assistant" else text
        if not display_text and self.role == "assistant":
            display_text = "_(tool call only)_"

        blocks = split_message_into_blocks(display_text)
        for b in blocks:
            if b["kind"] == "code":
                self._blocks_container.append(
                    CodeBlockWidget(b["content"], b["lang"]))
            else:
                lbl = Gtk.Label()
                lbl.set_wrap(True)
                lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                lbl.set_xalign(0.0)
                lbl.set_selectable(True)
                try:
                    lbl.set_markup(text_to_pango(b["content"]))
                except Exception:
                    lbl.set_text(b["content"])
                self._blocks_container.append(lbl)

    # -- streaming append: incremental update without rebuild ----

    def start_streaming(self):
        """Create one plain Label that we'll append tokens to."""
        child = self._blocks_container.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._blocks_container.remove(child)
            child = nxt
        self._streaming_label = Gtk.Label()
        self._streaming_label.set_wrap(True)
        self._streaming_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._streaming_label.set_xalign(0.0)
        self._streaming_label.set_selectable(True)
        self._streaming_label.set_text("")
        self._blocks_container.append(self._streaming_label)
        self._content = ""

    def append_streaming(self, token: str):
        if self._streaming_label is None:
            self.start_streaming()
        self._content += token
        # During streaming we just show plain text (no markdown parsing).
        # Final render happens in finish_streaming.
        display = strip_tool_calls(self._content)
        self._streaming_label.set_text(display)

    def finish_streaming(self) -> str:
        """Finalise: re-render with proper markdown/code-block parsing.
        Returns the full accumulated content (including any tool tags)."""
        final = self._content
        self._streaming_label = None
        self.set_content(final)
        return final


# ═════════════════════════════════════════════════════════════════════
# CHAT ROW (sidebar)
# ═════════════════════════════════════════════════════════════════════

class ChatRow(Gtk.ListBoxRow):
    def __init__(self, chat: Chat):
        super().__init__()
        self.chat = chat
        self.add_css_class("chat-row")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        outer.set_margin_top(2)
        outer.set_margin_bottom(2)

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

        meta = self._format_meta(chat)
        meta_lbl = Gtk.Label(label=meta, xalign=0.0)
        meta_lbl.add_css_class("meta-line")
        meta_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        outer.append(meta_lbl)

        self.set_child(outer)

    @staticmethod
    def _format_meta(chat: Chat) -> str:
        try:
            dt = datetime.datetime.fromtimestamp(chat.updated_at)
            now = datetime.datetime.now()
            delta = now - dt
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
        model_short = (chat.model or "").split(":", 1)[0]
        if model_short and stamp:
            return f"{stamp} · {model_short}"
        return stamp or model_short or ""


# ═════════════════════════════════════════════════════════════════════
# CONFIRM DIALOG for shell commands
# ═════════════════════════════════════════════════════════════════════

def confirm_command_dialog(
    parent: Gtk.Window,
    command: str,
    reason: str,
    on_decision: Callable[[bool], None],
):
    """Show modal: Run / Cancel.  Calls on_decision(True/False)."""
    dlg = Adw.AlertDialog.new(
        "Run shell command?",
        f"{reason}\n\nThis runs as your user.  Output is fed back to "
        f"the assistant.",
    )
    # Show the actual command in a styled box
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    cmd_lbl = Gtk.Label(label=command, xalign=0.0)
    cmd_lbl.set_wrap(True)
    cmd_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    cmd_lbl.set_selectable(True)
    cmd_lbl.add_css_class("confirm-cmd")
    body.append(cmd_lbl)
    dlg.set_extra_child(body)

    dlg.add_response("cancel", "Cancel")
    dlg.add_response("run", "Run")
    dlg.set_response_appearance("run", Adw.ResponseAppearance.SUGGESTED)
    dlg.set_default_response("run")
    dlg.set_close_response("cancel")

    def _cb(_dlg, response):
        on_decision(response == "run")

    dlg.connect("response", _cb)
    dlg.present(parent)


def confirm_sensitive_read_dialog(
    parent: Gtk.Window,
    path: str,
    on_decision: Callable[[bool], None],
):
    dlg = Adw.AlertDialog.new(
        "Read sensitive file?",
        f"The assistant wants to read:\n\n{path}\n\nThis path is on the "
        f"sensitive-paths list (keys, secrets, system auth).",
    )
    dlg.add_response("cancel", "Deny")
    dlg.add_response("read", "Allow read")
    dlg.set_response_appearance("read",
                                Adw.ResponseAppearance.DESTRUCTIVE)
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

        page = Adw.PreferencesPage()
        page.set_title("General")
        page.set_icon_name("preferences-system-symbolic")

        # -- Model group ------------------------------------
        mg = Adw.PreferencesGroup()
        mg.set_title("Model")
        mg.set_description("Local Ollama models")

        self.model_row = Adw.ComboRow()
        self.model_row.set_title("Default model")
        self._populate_models()
        mg.add(self.model_row)

        temp_row = Adw.SpinRow.new_with_range(0.0, 2.0, 0.05)
        temp_row.set_title("Temperature")
        temp_row.set_subtitle("Higher = more creative, lower = more focused")
        temp_row.set_value(parent.settings["temperature"])
        temp_row.connect("changed", self._on_temp)
        self.temp_row = temp_row
        mg.add(temp_row)

        ctx_row = Adw.SpinRow.new_with_range(512, 32768, 512)
        ctx_row.set_title("Context window")
        ctx_row.set_subtitle("Bigger = remembers more, slower & more RAM")
        ctx_row.set_value(parent.settings["num_ctx"])
        ctx_row.connect("changed", self._on_ctx)
        self.ctx_row = ctx_row
        mg.add(ctx_row)

        page.add(mg)

        # -- Behaviour ------------------------------------
        bg = Adw.PreferencesGroup()
        bg.set_title("Behaviour")

        self.agent_default_row = Adw.SwitchRow()
        self.agent_default_row.set_title("Agent mode by default")
        self.agent_default_row.set_subtitle(
            "New chats start with system tools enabled")
        self.agent_default_row.set_active(parent.settings["agent_mode_default"])
        self.agent_default_row.connect("notify::active", self._on_agent_default)
        bg.add(self.agent_default_row)

        self.confirm_all_row = Adw.SwitchRow()
        self.confirm_all_row.set_title("Confirm every command")
        self.confirm_all_row.set_subtitle(
            "If off, only risky commands prompt for y/n")
        self.confirm_all_row.set_active(parent.settings["confirm_all_commands"])
        self.confirm_all_row.connect("notify::active", self._on_confirm_all)
        bg.add(self.confirm_all_row)

        page.add(bg)

        # -- Ollama -----------------------------------------
        og = Adw.PreferencesGroup()
        og.set_title("Ollama")

        self.autostart_row = Adw.SwitchRow()
        self.autostart_row.set_title("Auto-start ollama serve on launch")
        self.autostart_row.set_active(parent.settings["auto_start_ollama"])
        self.autostart_row.connect("notify::active", self._on_autostart)
        og.add(self.autostart_row)

        self.stop_on_quit_row = Adw.SwitchRow()
        self.stop_on_quit_row.set_title("Stop ollama serve on app quit")
        self.stop_on_quit_row.set_subtitle(
            "Off by default — leaves Ollama running for other tools")
        self.stop_on_quit_row.set_active(parent.settings["stop_ollama_on_quit"])
        self.stop_on_quit_row.connect("notify::active", self._on_stop_quit)
        og.add(self.stop_on_quit_row)

        page.add(og)

        # -- System prompt -----------------------------------
        pg = Adw.PreferencesGroup()
        pg.set_title("System prompt")
        pg.set_description("Appended to the built-in persona.  "
                           "Leave empty to use defaults only.")

        sp_card = Gtk.Frame()
        sp_card.set_margin_top(4)
        sp_card.set_margin_bottom(4)
        sp_card.set_margin_start(4)
        sp_card.set_margin_end(4)
        sp_sw = Gtk.ScrolledWindow()
        sp_sw.set_min_content_height(140)
        sp_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.sp_view = Gtk.TextView()
        self.sp_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.sp_view.get_buffer().set_text(parent.settings.get("system_prompt", ""))
        self.sp_view.get_buffer().connect("changed", self._on_sp_changed)
        sp_sw.set_child(self.sp_view)
        sp_card.set_child(sp_sw)
        pg.add(sp_card)
        page.add(pg)

        self.add(page)

    def _populate_models(self):
        models = self.win.ollama.list_models()
        names = [m["name"] for m in models] if models else []
        if not names:
            names = ["(no models installed)"]
        sl = Gtk.StringList.new(names)
        self.model_row.set_model(sl)
        current = self.win.settings.get("default_model") or ""
        if current in names:
            self.model_row.set_selected(names.index(current))
        self.model_row.connect("notify::selected", self._on_model)

    # -- handlers ------------------------------------------

    def _on_model(self, row, _ps):
        m = row.get_model()
        idx = row.get_selected()
        if m and idx < m.get_n_items():
            name = m.get_string(idx)
            if not name.startswith("("):
                self.win.settings["default_model"] = name
                save_settings(self.win.settings)
                self.win.update_status_pill()

    def _on_temp(self, row):
        self.win.settings["temperature"] = float(row.get_value())
        save_settings(self.win.settings)

    def _on_ctx(self, row):
        self.win.settings["num_ctx"] = int(row.get_value())
        save_settings(self.win.settings)

    def _on_agent_default(self, row, _ps):
        self.win.settings["agent_mode_default"] = row.get_active()
        save_settings(self.win.settings)

    def _on_confirm_all(self, row, _ps):
        self.win.settings["confirm_all_commands"] = row.get_active()
        save_settings(self.win.settings)

    def _on_autostart(self, row, _ps):
        self.win.settings["auto_start_ollama"] = row.get_active()
        save_settings(self.win.settings)

    def _on_stop_quit(self, row, _ps):
        self.win.settings["stop_ollama_on_quit"] = row.get_active()
        save_settings(self.win.settings)

    def _on_sp_changed(self, buf):
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self.win.settings["system_prompt"] = text
        save_settings(self.win.settings)


# ═════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ═════════════════════════════════════════════════════════════════════

class MainWindow(Adw.ApplicationWindow):

    def __init__(self, app: "OracleApp"):
        super().__init__(application=app)
        self.set_title(APP_NAME)
        self.set_default_size(1100, 720)
        self.app = app
        self.settings = load_settings()
        self.ollama = OllamaManager()
        self.store = ChatStore()

        self.current_chat_id: Optional[int] = None
        self.current_agent_mode: bool = bool(
            self.settings.get("agent_mode_default", False))
        self.streaming_thread: Optional[threading.Thread] = None
        self.streaming_cancel: Optional[threading.Event] = None
        self.streaming_msg_widget: Optional[MessageWidget] = None
        self.streaming_msg_db_id: Optional[int] = None

        self._build_ui()
        self._wire_actions()

        # Boot tasks
        self._boot()

        # Always start fresh — new chat on launch
        GLib.idle_add(self._new_chat)
        # Refresh sidebar
        GLib.idle_add(self._refresh_sidebar)

    # -- boot ----------------------------------------------------

    def _boot(self):
        # Start Ollama in background; the UI is usable while it warms up
        def _bg():
            if self.settings.get("auto_start_ollama", True):
                running = self.ollama.is_running()
                if not running:
                    log("Starting ollama serve...")
                    ok = self.ollama.start_serve()
                    log(f"ollama serve start: {'ok' if ok else 'FAILED'}")
            # Pick default model if none set
            if not self.settings.get("default_model"):
                models = self.ollama.list_models()
                if models:
                    self.settings["default_model"] = models[0]["name"]
                    save_settings(self.settings)
            GLib.idle_add(self.update_status_pill)
            GLib.idle_add(self._refresh_model_dropdown)
        threading.Thread(target=_bg, daemon=True).start()

    # -- UI construction -----------------------------------------

    def _build_ui(self):
        # Toast overlay wraps everything so we can pop short notices
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # Split view: sidebar | chat
        self.split = Adw.OverlaySplitView()
        self.split.set_min_sidebar_width(240)
        self.split.set_max_sidebar_width(340)
        self.split.set_sidebar_width_fraction(0.28)
        self.split.set_collapsed(False)
        self.toast_overlay.set_child(self.split)

        # -- SIDEBAR ---------------------------------------
        self.split.set_sidebar(self._build_sidebar())

        # -- MAIN ------------------------------------------
        self.split.set_content(self._build_main())

    def _build_sidebar(self) -> Gtk.Widget:
        sb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sb.add_css_class("sidebar")

        # Header: title + new chat button
        sb_header = Adw.HeaderBar()
        sb_header.set_show_end_title_buttons(False)
        sb_header.set_show_start_title_buttons(False)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        t = Gtk.Label(label=APP_NAME, xalign=0.0)
        t.add_css_class("app-title")
        st = Gtk.Label(label="local · offline · yours", xalign=0.0)
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
        sw_box.set_margin_start(8)
        sw_box.set_margin_end(8)
        sw_box.set_margin_top(4)
        sw_box.set_margin_bottom(4)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("search chats…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search)
        sw_box.append(self.search_entry)
        sb.append(sw_box)

        # Chat list
        self.chat_listbox = Gtk.ListBox()
        self.chat_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.chat_listbox.connect("row-activated", self._on_chat_selected)

        # Context menu for chats (right-click / long-press)
        gc = Gtk.GestureClick()
        gc.set_button(3)  # right click
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

    def _build_main(self) -> Gtk.Widget:
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header bar
        hb = Adw.HeaderBar()
        # Sidebar toggle (for collapsed/mobile)
        sb_toggle = Gtk.Button.new_from_icon_name("sidebar-show-symbolic")
        sb_toggle.add_css_class("icon-button")
        sb_toggle.set_tooltip_text("Toggle sidebar")
        sb_toggle.connect("clicked", lambda *_:
                          self.split.set_show_sidebar(
                              not self.split.get_show_sidebar()))
        hb.pack_start(sb_toggle)

        # Title widget: chat title + model
        self.title_widget_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                        spacing=0)
        self.chat_title_lbl = Gtk.Label(label="New chat", xalign=0.5)
        self.chat_title_lbl.add_css_class("app-title")
        self.chat_subtitle_lbl = Gtk.Label(label="", xalign=0.5)
        self.chat_subtitle_lbl.add_css_class("app-subtitle")
        self.title_widget_box.append(self.chat_title_lbl)
        self.title_widget_box.append(self.chat_subtitle_lbl)
        hb.set_title_widget(self.title_widget_box)

        # Right: status pill + model dropdown + menu
        self.status_pill = Gtk.Label(label="…")
        self.status_pill.add_css_class("status-pill")
        hb.pack_end(self.status_pill)

        self.model_dropdown = Gtk.DropDown.new(Gtk.StringList.new(["…"]), None)
        self.model_dropdown.set_tooltip_text("Model")
        self.model_dropdown.connect("notify::selected", self._on_model_picked)
        hb.pack_end(self.model_dropdown)

        # Menu
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.add_css_class("icon-button")
        menu = Gio.Menu()
        menu.append("Refresh models", "win.refresh-models")
        menu.append("Pin chat", "win.pin-chat")
        menu.append("Rename chat", "win.rename-chat")
        menu.append("Delete chat", "win.delete-chat")
        menu.append("Settings", "win.settings")
        menu.append("About", "win.about")
        menu_btn.set_menu_model(menu)
        hb.pack_end(menu_btn)

        main.append(hb)

        # Message area
        self.msg_scroll = Gtk.ScrolledWindow()
        self.msg_scroll.set_policy(Gtk.PolicyType.NEVER,
                                   Gtk.PolicyType.AUTOMATIC)
        self.msg_scroll.set_vexpand(True)
        self.msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.msg_box.set_margin_top(8)
        self.msg_box.set_margin_bottom(8)
        self.msg_box.set_margin_start(4)
        self.msg_box.set_margin_end(4)
        self.msg_scroll.set_child(self.msg_box)
        main.append(self.msg_scroll)

        # Input area
        input_area = self._build_input_area()
        main.append(input_area)

        return main

    def _build_input_area(self) -> Gtk.Widget:
        area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        area.add_css_class("input-area")

        # Top row: quick actions
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        actions.set_margin_start(6)
        actions.set_margin_end(6)

        self.agent_toggle = Gtk.ToggleButton()
        self.agent_toggle.set_icon_name("applications-system-symbolic")
        self.agent_toggle.add_css_class("icon-button")
        self.agent_toggle.set_tooltip_text("Agent mode (system tools)")
        self.agent_toggle.set_active(self.current_agent_mode)
        self.agent_toggle.connect("toggled", self._on_agent_toggled)
        actions.append(self.agent_toggle)

        audit_btn = Gtk.Button.new_from_icon_name("security-high-symbolic")
        audit_btn.add_css_class("icon-button")
        audit_btn.set_tooltip_text("Run security audit")
        audit_btn.connect("clicked", lambda *_: self._user_action_audit())
        actions.append(audit_btn)

        scan_btn = Gtk.Button.new_from_icon_name("network-wireless-symbolic")
        scan_btn.add_css_class("icon-button")
        scan_btn.set_tooltip_text("Scan local network")
        scan_btn.connect("clicked", lambda *_: self._user_action_scan())
        actions.append(scan_btn)

        attach_btn = Gtk.Button.new_from_icon_name("mail-attachment-symbolic")
        attach_btn.add_css_class("icon-button")
        attach_btn.set_tooltip_text("Attach a file to the next message")
        attach_btn.connect("clicked", lambda *_: self._pick_attachment())
        actions.append(attach_btn)

        sysinfo_btn = Gtk.Button.new_from_icon_name(
            "computer-symbolic")
        sysinfo_btn.add_css_class("icon-button")
        sysinfo_btn.set_tooltip_text("Inject system info into chat")
        sysinfo_btn.connect("clicked", lambda *_: self._user_action_sysinfo())
        actions.append(sysinfo_btn)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        actions.append(spacer)

        self.online_pill = Gtk.Label(label="OFFLINE")
        self.online_pill.add_css_class("status-pill")
        self.online_pill.add_css_class("offline")
        actions.append(self.online_pill)

        area.append(actions)

        # Input box itself
        ibox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        ibox.add_css_class("input-frame")
        ibox.set_margin_start(8)
        ibox.set_margin_end(8)
        ibox.set_margin_bottom(4)

        in_scroll = Gtk.ScrolledWindow()
        in_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        in_scroll.set_min_content_height(40)
        in_scroll.set_max_content_height(180)
        in_scroll.set_propagate_natural_height(True)
        in_scroll.set_hexpand(True)

        self.input_view = Gtk.TextView()
        self.input_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.input_view.set_top_margin(4)
        self.input_view.set_bottom_margin(4)
        in_scroll.set_child(self.input_view)
        ibox.append(in_scroll)

        # Enter to send, Shift+Enter for newline
        kc = Gtk.EventControllerKey()
        kc.connect("key-pressed", self._on_input_key)
        self.input_view.add_controller(kc)

        self.send_btn = Gtk.Button()
        self.send_btn.set_icon_name("send-to-symbolic")
        self.send_btn.add_css_class("send-button")
        self.send_btn.set_valign(Gtk.Align.END)
        self.send_btn.connect("clicked", lambda *_: self._send_user_message())
        ibox.append(self.send_btn)

        area.append(ibox)
        return area

    # -- actions / accelerators ----------------------------------

    def _wire_actions(self):
        def _add(name, cb):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_: cb())
            self.add_action(a)
        _add("settings", self._open_settings)
        _add("about", self._open_about)
        _add("refresh-models", self._refresh_model_dropdown)
        _add("rename-chat", self._rename_current_chat)
        _add("delete-chat", self._delete_current_chat)
        _add("pin-chat", self._toggle_pin_current)

        # Online status poll every 8s
        GLib.timeout_add_seconds(8, self._poll_online)
        self._poll_online()

    # -- status / online ----------------------------------------

    def _poll_online(self):
        def _bg():
            on = is_online(timeout=0.8)
            GLib.idle_add(self._set_online_indicator, on)
        threading.Thread(target=_bg, daemon=True).start()
        return True  # keep polling

    def _set_online_indicator(self, online: bool):
        if online:
            self.online_pill.set_text("ONLINE")
            self.online_pill.remove_css_class("offline")
            self.online_pill.add_css_class("online")
        else:
            self.online_pill.set_text("OFFLINE")
            self.online_pill.remove_css_class("online")
            self.online_pill.add_css_class("offline")
        return False

    def update_status_pill(self):
        if self.ollama.is_running():
            ver = self.ollama.version() or "?"
            self.status_pill.set_text(f"OLLAMA {ver}")
            self.status_pill.remove_css_class("offline")
            self.status_pill.remove_css_class("error")
            self.status_pill.add_css_class("online")
        else:
            self.status_pill.set_text("OLLAMA OFF")
            self.status_pill.remove_css_class("online")
            self.status_pill.add_css_class("error")
        return False

    def _refresh_model_dropdown(self):
        models = self.ollama.list_models()
        names = [m["name"] for m in models] if models else []
        if not names:
            names = ["(no models)"]
        sl = Gtk.StringList.new(names)
        self.model_dropdown.set_model(sl)
        cur = self.settings.get("default_model") or ""
        if cur in names:
            self.model_dropdown.set_selected(names.index(cur))
        return False

    def _on_model_picked(self, dd, _ps):
        m = dd.get_model()
        idx = dd.get_selected()
        if m and idx < m.get_n_items():
            name = m.get_string(idx)
            if not name.startswith("("):
                self.settings["default_model"] = name
                save_settings(self.settings)
                self._refresh_subtitle()

    # -- chat list / sidebar -------------------------------------

    def _refresh_sidebar(self, query: str = ""):
        # clear
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
            empty = Gtk.Label(label="No chats yet.\nStart talking.")
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
        if not isinstance(row, ChatRow):
            return
        if row.chat.id == self.current_chat_id:
            return
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

    def _show_chat_context_menu(self, row: ChatRow, x: float, y: float):
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

    # -- chat loading / new --------------------------------------

    def _new_chat(self):
        # Pick model
        model = self.settings.get("default_model") or ""
        cid = self.store.create_chat(
            title="New chat",
            model=model,
            agent_mode=self.settings.get("agent_mode_default", False),
        )
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
        self.chat_title_lbl.set_text(chat.title)
        self._refresh_subtitle()

        # Clear msg area
        child = self.msg_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.msg_box.remove(child)
            child = nxt

        # Empty state
        msgs = self.store.list_messages(chat_id)
        if not msgs:
            empty = Gtk.Label()
            empty.set_markup(
                "<span size='14pt' weight='bold' color='#cdd6f4'>"
                f"Hello, Priest.</span>\n\n"
                "<span size='10pt' color='#6c7086'>"
                "Ask me something.  Or hit the gear to flip agent mode "
                "and let me actually do work on this machine.</span>")
            empty.set_justify(Gtk.Justification.CENTER)
            empty.set_margin_top(80)
            self.msg_box.append(empty)
        else:
            for m in msgs:
                self._append_message_widget(m.role, m.content, m.meta)

        # Scroll to bottom
        GLib.idle_add(self._scroll_to_bottom)

    def _refresh_subtitle(self):
        chat = self.store.get_chat(self.current_chat_id) if self.current_chat_id else None
        bits = []
        if chat and chat.model:
            bits.append(chat.model)
        if self.current_agent_mode:
            bits.append("agent")
        self.chat_subtitle_lbl.set_text(" · ".join(bits) if bits else "")

    # -- messages ------------------------------------------------

    def _append_message_widget(self, role: str, content: str,
                               meta: Optional[Dict[str, Any]] = None
                               ) -> MessageWidget:
        # Remove empty-state placeholder if present
        first = self.msg_box.get_first_child()
        if first is not None and not isinstance(first, MessageWidget):
            self.msg_box.remove(first)
        w = MessageWidget(role, content, meta)
        self.msg_box.append(w)
        GLib.idle_add(self._scroll_to_bottom)
        return w

    def _scroll_to_bottom(self):
        adj = self.msg_scroll.get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    # -- sending -------------------------------------------------

    def _on_input_key(self, controller, keyval, keycode, state):
        # Enter sends; Shift+Enter inserts newline
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
            if not shift:
                self._send_user_message()
                return True
        return False

    def _send_user_message(self):
        if self.streaming_thread and self.streaming_thread.is_alive():
            self._show_toast("Already replying — wait or hit cancel.")
            return
        buf = self.input_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(),
                            False).strip()
        if not text:
            return
        buf.set_text("")

        if self.current_chat_id is None:
            self._new_chat()

        # Persist user message
        self.store.add_message(self.current_chat_id, "user", text)
        self._append_message_widget("user", text)

        # If this is the first user msg, derive title
        msgs = self.store.list_messages(self.current_chat_id)
        if sum(1 for m in msgs if m.role == "user") == 1:
            title = title_from_first_message(text)
            self.store.rename_chat(self.current_chat_id, title)
            self.chat_title_lbl.set_text(title)
            self._refresh_sidebar()

        self._kick_assistant_turn()

    def _kick_assistant_turn(self):
        """Build messages, fire streaming thread."""
        model = self.settings.get("default_model")
        if not model:
            self._show_toast("No model selected.  Open settings.")
            return
        if not self.ollama.is_running():
            self._show_toast(
                "Ollama isn't running.  Trying to start it…")
            threading.Thread(target=self._restart_ollama,
                             daemon=True).start()
            return

        history = self._build_history_for_model()
        sysprompt = build_system_prompt(
            agent_mode=self.current_agent_mode,
            custom_addendum=self.settings.get("system_prompt", ""),
        )
        full = assemble_messages(sysprompt, history)

        # Insert assistant placeholder widget
        self.streaming_msg_widget = self._append_message_widget("assistant", "")
        self.streaming_msg_widget.start_streaming()
        self.streaming_msg_db_id = self.store.add_message(
            self.current_chat_id, "assistant", "")

        self.streaming_cancel = threading.Event()
        opts = {
            "temperature": self.settings.get("temperature", 0.7),
            "top_p": self.settings.get("top_p", 0.9),
            "num_ctx": self.settings.get("num_ctx", 4096),
        }

        def _on_tok(tok):
            GLib.idle_add(self._on_stream_token, tok)

        def _on_done(meta):
            GLib.idle_add(self._on_stream_done, meta)

        def _on_err(err):
            GLib.idle_add(self._on_stream_error, err)

        def _bg():
            self.ollama.stream_chat(
                model=model,
                messages=full,
                on_token=_on_tok,
                on_done=_on_done,
                on_error=_on_err,
                options=opts,
                cancel_event=self.streaming_cancel,
            )

        self.streaming_thread = threading.Thread(target=_bg, daemon=True)
        self.streaming_thread.start()
        self.send_btn.set_sensitive(False)

    def _restart_ollama(self):
        ok = self.ollama.start_serve()
        GLib.idle_add(self.update_status_pill)
        if ok:
            GLib.idle_add(self._show_toast, "Ollama started — retry.")
        else:
            GLib.idle_add(self._show_toast,
                          "Couldn't start ollama.  Is it installed?")

    def _on_stream_token(self, tok: str):
        if self.streaming_msg_widget:
            self.streaming_msg_widget.append_streaming(tok)
            self._scroll_to_bottom()
        return False

    def _on_stream_done(self, meta: Dict[str, Any]):
        self.send_btn.set_sensitive(True)
        if not self.streaming_msg_widget:
            return False
        final = self.streaming_msg_widget.finish_streaming()
        if self.streaming_msg_db_id:
            self.store.update_message(self.streaming_msg_db_id, final)

        # Check for tool calls in the assistant message
        calls = parse_tool_calls(final)
        if calls and not meta.get("cancelled"):
            self._execute_tool_calls(calls)
        else:
            self.streaming_msg_widget = None
            self.streaming_msg_db_id = None
        return False

    def _on_stream_error(self, err: str):
        self.send_btn.set_sensitive(True)
        if self.streaming_msg_widget:
            self.streaming_msg_widget.set_content(f"_(error: {err})_")
            if self.streaming_msg_db_id:
                self.store.update_message(self.streaming_msg_db_id,
                                          f"_(error: {err})_")
        self._show_toast(f"Stream error: {err}")
        self.streaming_msg_widget = None
        self.streaming_msg_db_id = None
        return False

    # -- tool execution loop -------------------------------------

    def _execute_tool_calls(self, calls: List[ToolCall]):
        """Run the (first) tool call, append result, kick another turn."""
        call = calls[0]   # one at a time

        # Render the tool call inline
        call_text = f"⚙ tool: {call.name}({json.dumps(call.args)})"
        self._append_message_widget("tool", call_text, meta={"kind": "call"})
        self.store.add_message(self.current_chat_id, "tool", call_text,
                               meta={"kind": "call"})

        # Dispatch
        if call.name == "read_file":
            self._tool_read_file(call.args.get("path", ""))
        elif call.name == "list_dir":
            self._tool_list_dir(call.args.get("path", "."))
        elif call.name == "system_info":
            self._tool_system_info()
        elif call.name == "run":
            self._tool_run(call.args.get("command", ""),
                           call.args.get("reason", ""))
        elif call.name == "audit":
            self._tool_audit()
        elif call.name == "scan_net":
            self._tool_scan_net(call.args.get("cidr"))
        else:
            self._feed_tool_result(
                f"Unknown tool '{call.name}'.  "
                f"Valid: read_file, list_dir, system_info, run, "
                f"audit, scan_net.")

    def _feed_tool_result(self, result_text: str,
                          display_text: Optional[str] = None):
        """Append a tool result and trigger another assistant turn."""
        # Show in chat
        shown = display_text if display_text is not None else result_text
        self._append_message_widget("tool", shown, meta={"kind": "result"})
        # Persist as a user-role message (so the model sees it) — but tag meta
        self.store.add_message(self.current_chat_id, "user",
                               f"<tool_result>\n{result_text}\n</tool_result>",
                               meta={"kind": "tool_result"})
        # Continue the conversation
        self.streaming_msg_widget = None
        self.streaming_msg_db_id = None
        self._kick_assistant_turn()

    # -- individual tools ----------------------------------------

    def _tool_read_file(self, path: str):
        if not path:
            self._feed_tool_result("error: no path provided")
            return
        if is_sensitive_path(path):
            def decide(allow):
                if allow:
                    r = tool_read_file(path)
                    self._render_read_result(r)
                else:
                    self._feed_tool_result(f"denied: operator refused read of {path}")
            confirm_sensitive_read_dialog(self, path, decide)
        else:
            r = tool_read_file(path)
            self._render_read_result(r)

    def _render_read_result(self, r: Dict[str, Any]):
        if not r.get("ok"):
            self._feed_tool_result(f"read_file error: {r.get('error')}")
            return
        body = r["content"]
        header = (f"file: {r['path']}  ({r['size']} bytes"
                  f"{' truncated' if r['truncated'] else ''})")
        display = f"{header}\n\n{body[:2000]}"
        result_for_model = f"{header}\n\n{body}"
        self._feed_tool_result(result_for_model, display)

    def _tool_list_dir(self, path: str):
        r = tool_list_dir(path)
        if not r.get("ok"):
            self._feed_tool_result(f"list_dir error: {r.get('error')}")
            return
        lines = [f"dir: {r['path']}", ""]
        for e in r["entries"]:
            sz = "" if e["is_dir"] else f"  ({e['size']}B)"
            lines.append(f"  {e['name']}{sz}")
        out = "\n".join(lines)
        self._feed_tool_result(out)

    def _tool_system_info(self):
        info = tool_system_info()
        out = "\n".join(f"{k}: {v}" for k, v in info.items())
        self._feed_tool_result(out)

    def _tool_run(self, command: str, reason: str):
        if not command:
            self._feed_tool_result("error: no command provided")
            return

        def decide(allow):
            if not allow:
                self._feed_tool_result(
                    f"operator declined to run: {command}")
                return
            # Run in background so UI stays responsive
            def _bg():
                r = tool_run_command(command, timeout=60)
                if r.get("ok"):
                    parts = [f"$ {command}", f"(rc={r['rc']})"]
                    if r["stdout"]:
                        parts.append(r["stdout"])
                    if r["stderr"]:
                        parts.append(f"stderr:\n{r['stderr']}")
                    out = "\n".join(parts)
                else:
                    out = f"$ {command}\nerror: {r.get('error')}"
                GLib.idle_add(self._feed_tool_result, out)
            threading.Thread(target=_bg, daemon=True).start()

        confirm_command_dialog(self, command, reason or "no reason given",
                               decide)

    def _tool_audit(self):
        self._show_toast("Running audit…")
        def _bg():
            audit = run_security_audit()
            text = format_audit_for_chat(audit)
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

    def _tool_scan_net(self, cidr=None):
        self._show_toast("Scanning network…")
        def _bg():
            scan = run_network_scan(cidr)
            text = format_scan_for_chat(scan)
            GLib.idle_add(self._feed_tool_result, text)
        threading.Thread(target=_bg, daemon=True).start()

    # -- user-initiated tool buttons -----------------------------

    def _user_action_audit(self):
        if self.current_chat_id is None:
            self._new_chat()
        # Insert a user-prompt-style message asking the model to use audit
        self.store.add_message(self.current_chat_id, "user",
                               "Run a security audit on this system and "
                               "tell me what to worry about.")
        self._append_message_widget("user",
                                    "Run a security audit on this system "
                                    "and tell me what to worry about.")
        # Force agent mode for this turn
        was_agent = self.current_agent_mode
        self.current_agent_mode = True
        self._tool_audit()
        # restore mode visibility
        self.current_agent_mode = was_agent
        self.agent_toggle.set_active(was_agent)

    def _user_action_scan(self):
        if self.current_chat_id is None:
            self._new_chat()
        self.store.add_message(self.current_chat_id, "user",
                               "Scan the local network and summarise the hosts.")
        self._append_message_widget("user",
                                    "Scan the local network and summarise "
                                    "the hosts.")
        self._tool_scan_net()

    def _user_action_sysinfo(self):
        if self.current_chat_id is None:
            self._new_chat()
        self.store.add_message(self.current_chat_id, "user",
                               "Give me a quick read of this system "
                               "(uname, RAM, uptime, IPs).")
        self._append_message_widget("user",
                                    "Give me a quick read of this system "
                                    "(uname, RAM, uptime, IPs).")
        self._tool_system_info()

    def _pick_attachment(self):
        dlg = Gtk.FileDialog()
        dlg.set_title("Attach a file")
        def _cb(d, res):
            try:
                f = d.open_finish(res)
                if f:
                    path = f.get_path()
                    self._attach_file_into_input(path)
            except Exception:
                pass
        dlg.open(self, None, _cb)

    def _attach_file_into_input(self, path: str):
        r = tool_read_file(path, max_bytes=40_000)
        if not r.get("ok"):
            self._show_toast(f"Read error: {r.get('error')}")
            return
        buf = self.input_view.get_buffer()
        current = buf.get_text(buf.get_start_iter(), buf.get_end_iter(),
                               False)
        body = r["content"]
        addition = (f"{current}\n\n[attached: {path}]\n```\n{body}\n```\n"
                    if current else
                    f"[attached: {path}]\n```\n{body}\n```\n")
        buf.set_text(addition)

    # -- history → ollama messages -------------------------------

    def _build_history_for_model(self) -> List[Dict[str, str]]:
        """Pull messages from DB and shape them for Ollama's /api/chat.
        We map tool calls/results into user-role messages with tags so even
        small models without function-calling can follow."""
        out: List[Dict[str, str]] = []
        msgs = self.store.list_messages(self.current_chat_id)
        for m in msgs:
            kind = (m.meta or {}).get("kind")
            if m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                out.append({"role": "assistant", "content": m.content})
            elif m.role == "tool":
                # tool calls already appear inside the assistant message;
                # tool results are stored under role='user' with meta.
                if kind == "result":
                    out.append({"role": "user", "content": m.content})
            elif m.role == "system":
                # operator-injected system note
                out.append({"role": "system", "content": m.content})
        return out

    # -- agent toggle --------------------------------------------

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

    # -- menu actions --------------------------------------------

    def _open_settings(self):
        SettingsDialog(self).present(self)

    def _open_about(self):
        about = Adw.AboutDialog()
        about.set_application_name(APP_NAME)
        about.set_version(VERSION)
        about.set_developer_name("The Priest")
        about.set_comments("Local, loyal, offline AI assistant.\n"
                           "Built on Ollama.  Lives on your hardware.")
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
        dlg = Adw.AlertDialog.new("Delete this chat?",
                                  "This can't be undone.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("delete", "Delete")
        dlg.set_response_appearance("delete",
                                    Adw.ResponseAppearance.DESTRUCTIVE)
        def _cb(d, response):
            if response == "delete":
                self.store.delete_chat(self.current_chat_id)
                self.current_chat_id = None
                self._new_chat()
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

    # -- toast ----------------------------------------------------

    def _show_toast(self, text: str, timeout: int = 3):
        t = Adw.Toast.new(text)
        t.set_timeout(timeout)
        self.toast_overlay.add_toast(t)
        return False

    # -- shutdown -------------------------------------------------

    def shutdown(self):
        if self.streaming_cancel:
            self.streaming_cancel.set()
        if self.settings.get("stop_ollama_on_quit", False):
            self.ollama.stop_serve()


# ═════════════════════════════════════════════════════════════════════
# APPLICATION
# ═════════════════════════════════════════════════════════════════════

class OracleApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.win: Optional[MainWindow] = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        # Install CSS
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        # Force dark scheme — Catppuccin Mocha is dark
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK)

    def do_activate(self):
        if not self.win:
            self.win = MainWindow(self)
        self.win.present()

    def do_shutdown(self):
        if self.win:
            self.win.shutdown()
        Adw.Application.do_shutdown(self)


def main():
    app = OracleApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
