"""The interactive prompt loop (`un chat`), contributed as a `command:` service. Writes nothing.

Input is a `prompt_toolkit` line on a terminal, otherwise `session.stream` or stdin. Ctrl-C, or ESC on an empty line, ends the turn, not the loop; ESC twice clears a non-empty line. Stdout carries only answers.

An interactive session owns the screen: `Surface` uses the alternate buffer, holds the conversation as blocks and repaints the visible tail, so collapsed results can expand in place; the wheel scrolls via `?1007h` without capturing the mouse, and `stop` writes the conversation to scrollback on exit. The screen is taken only for an interactive session, the reply is painted only when stdout is that screen, and the loop's own output goes through `Surface.note` so a repaint does not erase it.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import itertools
import os
import re
import select
import signal
import sys
import termios
import textwrap
import threading
import time
import tomllib
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import ALL_KEYS, KEY_ALIASES, Keys
from prompt_toolkit.data_structures import Size
from prompt_toolkit.layout import (BufferControl, Float, FloatContainer,
                                   FormattedTextControl, HSplit, Layout, VSplit,
                                   Window)
from prompt_toolkit.layout.margins import Margin
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.output import create_output
from rich.console import Console
from rich.errors import StyleSyntaxError
from rich.markdown import Markdown
from rich.style import Style
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from un import (EXIT_OK, EXIT_USAGE, NoSuchCommand, Quit, RunPrompt, Session, end_session,
                hook, new_session, run_terminal, service, session_file, slash, use, variants)

from un import core
from un.plugins.stock import curation

VERSION = metadata.version("unstable-number")
# Marks a tool result under its call. Not skinnable: it carries meaning, not style.
BRANCH = "⎿"

# The pulse animation; eight frames so a stall shows as a frozen shape.
FRAMES = ("✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳")
INTERVAL = 0.25

INTERRUPTED = "Interrupted by the user"

# Why Ctrl-T declined, said aloud so it is not mistaken for an undelivered key.
NO_RECORD = "no session record yet - {key} shows it once this session has run a turn"
NO_READER = "no session record reader - the session_view plugin is disabled"

# Skinnable characters: the shared box rules, the divider fill, and the prose and operator marks. A skin's `[glyphs]` overrides per key.
GLYPHS = {"top_left": "╭", "top_right": "╮",
          "bottom_left": "╰", "bottom_right": "╯",
          "horizontal": "─", "vertical": "│", "inner_divider": "─",
          "bullet": "⏺", "user": ">"}

# Optional screen elements: each value is the role it is painted in, and "" turns it off. `status_bar_text` is instead the bar's format string over `{version}`, `{session}` and `{project}`. Overridden per key.
DECORATORS = {"status_bar": "", "inner_divider": "",
              "status_bar_text": " {version}  {session}  {project} "}

# Name shown before the main agent's tool calls; "" shows none.
LABELS = {"main": core.MAIN}

# The `[<agent>] ` prefixes `Session.say` adds per nesting level; the innermost is the caller.
AGENT_TAG = re.compile(r"^(?:\[([a-z0-9-]+)\] )+")

# Spacing: off puts a blank line before each entry except a tool result.
LAYOUT = {"condensed": "false"}

# Skin values arrive as strings, so TOML `true` is "True".
TRUTHY = ("true", "1", "yes")

# Below this many conversation rows, decorators are dropped entirely.
CONVERSATION_FLOOR = 3

TOP_LEFT, TOP_RIGHT = GLYPHS["top_left"], GLYPHS["top_right"]
BOTTOM_LEFT, BOTTOM_RIGHT = GLYPHS["bottom_left"], GLYPHS["bottom_right"]
HORIZONTAL, VERTICAL = GLYPHS["horizontal"], GLYPHS["vertical"]
BULLET = GLYPHS["bullet"]

# Floor for the reported width: the side rules take 6 columns.
MIN_WIDTH = 8
# Preferred welcome box width; narrower panes get the pane width.
BANNER_WIDTH = 50

# Completion menu rows drawn at once; the list scrolls beyond it.
MENU_HEIGHT = 5

# Each frame starts with exactly one CURSOR_HOME, which is what separates frames in the byte stream (and in tests).
ALT_ON, ALT_OFF = "\x1b[?1049h", "\x1b[?1049l"
# Wheel as arrow keys, so scrolling works without capturing the mouse.
WHEEL_ON, WHEEL_OFF = "\x1b[?1007h", "\x1b[?1007l"
CURSOR_HOME, ERASE_LINE = "\x1b[H", "\x1b[K"
# A paint behind the live input box saves and restores the cursor, since prompt_toolkit redraws by relative moves.
SAVE_CURSOR, RESTORE_CURSOR = "\x1b7", "\x1b8"

# Map Shift-Enter's CSI-u and modifyOtherKeys sequences to Alt-Enter, so `compose` answers them instead of submitting.
# rat-tail: mutates a prompt_toolkit global at import; a `Vt100Parser` subclass is the upgrade.
for _shift_enter in ("\x1b[13;2u", "\x1b[27;2;13~"):
    ANSI_SEQUENCES[_shift_enter] = (Keys.Escape, Keys.ControlM)

# Rows reserved for the collapsed footer, the same between and during turns so nothing moves when a turn starts. A queued line or an expanded caption adds rows; draw paths use `len(_rows())`.
FOOTER_ROWS = 5

# rat-tail: bounded in blocks (one per emission); a paged deque of lines is the upgrade.
MAX_BLOCKS = 2000

# Channels drawn as blocks; everything else (text deltas) is not rendered here.
PAINTED = frozenset({"reply", "error", "interrupted", "tool", "tool_result",
                     "echo", "note", "banner"})

# Tool results are cut to this many lines on screen; the whole result stays one key away.
RESULT_LINES = 5
EXPAND_HINT = "… +{n} lines ({key} to expand)"

# Gutter indent steps for tool calls and their results. Not screen columns: see `_gutter`.
TOOL_INDENT, RESULT_INDENT = 1, 3

# figlet `smslant`, one word per render, stacked.
WORDMARK = (
    '                __       __   __',
    ' __ _____  ___ / /____ _/ /  / /__',
    '/ // / _ \\(_-</ __/ _ `/ _ \\/ / -_)',
    '\\_,_/_//_/___/\\__/\\_,_/_.__/_/\\__/',
    '                   __',
    '  ___  __ ____ _  / /  ___ ____',
    " / _ \\/ // /  ' \\/ _ \\/ -_) __/",
    '/_//_/\\_,_/_/_/_/_.__/\\__/_/',
)

# The fallback, for a box too narrow for the full name.
MONOGRAM = (
    ' __ _____',
    '/ // / _ \\',
    '\\_,_/_//_/',
)

# The input frame when there is no `Surface` (output redirected, stdin a terminal). Every key `_layout` reads must be present.
_BARE = {"top": "", "marker": "> ", "under": "", "edge": "", "bottom": "",
         "caption": "", "more": [], "user_pt": "", "margin": 4}


class _Reply(Markdown):
    """Markdown that keeps single newlines as line breaks, by rewriting softbreak tokens (markdown-it's `breaks` option does not reach rich)."""

    def __init__(self, markup: str, **kwargs) -> None:
        super().__init__(markup, **kwargs)
        for token in self.parsed:
            for child in token.children or ():
                if child.type == "softbreak":
                    child.type = "hardbreak"


def _collapse(text: str, key: str) -> str:
    """`text` cut to `RESULT_LINES` lines plus a hint naming the operator's expand key; unchanged when it fits."""
    lines = text.split("\n")
    if len(lines) <= RESULT_LINES:
        return text
    return "\n".join(lines[:RESULT_LINES]
                     + [EXPAND_HINT.format(n=len(lines) - RESULT_LINES,
                                           key=_spell(key))])


def _tokens(n: int) -> str:
    """`820`, `12.3k`, `1.2M`. Width matters more than precision in a prompt."""
    for limit, suffix in ((1_000_000, "M"), (1_000, "k")):
        if n >= limit:
            return f"{n / limit:.1f}{suffix}"
    return str(n)


def _figures(meter) -> list[str]:
    """`["42%", "$0.83"]`, dropping whichever figure is unknown. Zero is shown, not dropped."""
    shown = []
    if meter.fullness is not None:
        shown.append(f"{meter.fullness:.0%}")
    if meter.cost is not None:
        shown.append(f"${meter.cost:,.2f}")
    return shown


def _read_meter(session):
    """`context:meter` for `session`, or None without the context plugin."""
    try:
        return use("context", "meter")(session)
    except LookupError:
        return None


def _head(model: str, meter) -> str:
    """`<model> 42% $0.83`, main's entry in every caption; the model alone when `meter` is None (no context plugin)."""
    return " ".join([model, *(_figures(meter) if meter is not None else [])])


def _elapsed(clock: str, meter) -> str:
    """`00:04:21 • $1.20`, the session clock and its whole cost; the clock alone when the cost is unknown or `meter` is None (no context plugin)."""
    return f"{clock} • ${meter.total:,.2f}" if meter is not None and meter.total is not None else clock


def _minutes(elapsed: float) -> str:
    """The session clock, `hh:mm:ss`."""
    mins, secs = divmod(int(elapsed), 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


def _caption(model: str, meter, clock: str, width: int) -> tuple[str, str, list[str]]:
    """The footer caption at `width` as (collapsed row, expanded first row, expanded continuation rows); `meter` is None without the context plugin.

    The clock heads the row, then the session total when known, then main, then agent entries alphabetically, stopping at the first whole entry that does not fit beside the `+N` it would leave; no later, shorter name is pulled forward. Expanded keeps exactly the collapsed row's entries, so the toggle moves nothing, and packs the rest whole onto continuation rows.
    rat-tail: a row still wider than `width` (a very narrow terminal, one very long name) is cut at `width`; eliding inside an entry is the upgrade.
    """
    sep = " | "
    head = [f"  {_elapsed(clock, meter)}", _head(model, meter)]
    entries = ([" ".join([name, *_figures(meter.agents[name])]) for name in sorted(meter.agents)]
               if meter is not None else [])
    kept: list[str] = []
    for index, entry in enumerate(entries):
        # The last entry leaves nothing out, so it reserves no `+N`.
        left = len(entries) - index - 1
        if len(sep.join([*head, *kept, entry, *([f"+{left}"] if left else [])])) > width:
            break
        kept.append(entry)
    rest = entries[len(kept):]
    collapsed = sep.join([*head, *kept, *([f"+{len(rest)}"] if rest else [])])
    first = sep.join([*head, *kept])
    rows: list[list[str]] = []
    for entry in rest:
        if rows and len("  " + sep.join([*rows[-1], entry])) <= width:
            rows[-1].append(entry)
        else:
            rows.append([entry])
    return collapsed[:width], first[:width], [("  " + sep.join(row))[:width] for row in rows]


def _shown(session: Session) -> str:
    """The session's name when it has one, else its id.

    rat-tail: reads the name map on every paint; an mtime-keyed cache would lift that.
    """
    try:
        return use("session", "names")(session.root).get(session.id, session.id)
    except (LookupError, ValueError):
        # With the transcript plugin off or the map unreadable, the id still identifies it.
        return session.id


def _fill(glyph: str, width: int) -> str:
    """`glyph` tiled to exactly `width` columns; "" for a non-positive width or an empty glyph."""
    if width <= 0 or not glyph:
        return ""
    return (glyph * (width // len(glyph) + 1))[:width]


def _theme(roles: dict) -> tuple[Theme, list[str]]:
    """A `rich` Theme from a role table, plus a finding per invalid style. Bad roles become unstyled rather than failing the whole skin."""
    styles, findings = {}, []
    for role, style in roles.items():
        if role == "code" or role.startswith(("glyphs.", "decorators.", "layout.", "labels.")):
            # Not styles.
            continue
        try:
            Style.parse(style)
        except StyleSyntaxError as exc:
            findings.append(f"{role}: {exc}")
            styles[role] = "none"
        else:
            styles[role] = style
    return Theme(styles), findings


def _pt_style(style: str) -> str:
    """A rich style string, parsed by rich, as a `prompt_toolkit` style for the input buffer it redraws itself. "" when invalid.

    rat-tail: prompt_toolkit has no `dim`, so it is dropped.
    """
    try:
        parsed = Style.parse(style)
    except StyleSyntaxError:
        return ""
    out = [name for name in ("bold", "italic", "underline", "reverse") if getattr(parsed, name)]
    if (colour := parsed.color) and colour.name != "default":
        # A bare colour would be read as a class name.
        out.append(f"fg:{colour.triplet.hex if colour.triplet else colour.name}")
    return " ".join(out)


class _Fields(dict):
    """`status_bar_text` fields; an unknown `{name}` is echoed back rather than raising."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class _Waiting(threading.Thread):
    """The `✻ Thinking…` footer pulse, on a clock-driven daemon thread so a hung provider shows as a frozen count."""

    def __init__(self, surface: "Surface", session) -> None:
        super().__init__(daemon=True)
        self._surface = surface
        self._session = session
        self._done = threading.Event()
        # Not `_started`, which `threading.Thread` uses.
        self._since = time.monotonic()

    def line(self, frame: str) -> str:
        """`✻ Thinking… (12s · ↑ 1.2k tokens)`."""
        secs = int(time.monotonic() - self._since)
        return f"{frame} Thinking… ({secs}s · ↑ {_tokens(self._session.tokens)} tokens)"

    def run(self) -> None:
        for frame in itertools.cycle(FRAMES):
            self._surface.refresh()
            self._surface.pulse(self.line(frame))
            if self._done.wait(INTERVAL):
                return

    def stop(self) -> None:
        self._done.set()
        self.join()
        self._surface.pulse("")


# Scroll distances in lines; `_END` reaches either end of any conversation.
_PAGE, _LINE, _END = 20, 3, 10 ** 9

# Mid-turn actions: scroll distances, and the surface method each press calls.
_MID_SCROLL = {"scroll_up": _LINE, "scroll_down": -_LINE,
               "page_up": _PAGE, "page_down": -_PAGE}
_MID_PRESS = {"expand": "toggle", "transcript": "transcript", "agents": "agents"}


def _recall_or(surface: "Surface", fallback):
    """Up during a turn: recall the newest queued line, else do what Up already did (scroll, which the wheel also sends)."""
    def move() -> None:
        if not surface.recall() and fallback is not None:
            fallback()
    return move


class _Typing(threading.Thread):
    """Reads the keyboard during a turn (daemon thread), feeding the footer so typing survives repaints.

    A finished line is queued as the next prompt. A lone ESC goes to `Surface.escape`, which can end the turn; a read of exactly two ESCs goes to `Surface.escape_twice`, which clears a non-empty line and never ends it.

    rat-tail: minimal editing; running `_Line` during the turn is the upgrade.
    """

    BACKSPACE = (b"\x7f", b"\x08")

    # Left/Right in normal and application cursor mode. Not rebindable.
    CURSOR = {b"\x1b[D": -1, b"\x1bOD": -1, b"\x1b[C": 1, b"\x1bOC": 1}


    def __init__(self, surface: "Surface", fd: int,
                 keys: dict[str, str] | None = None) -> None:
        super().__init__(daemon=True)
        self._surface = surface
        self._fd = fd
        self._done = threading.Event()
        keys = keys or defaults()
        # Byte sequence -> action, matched whole at the head of each read, so multi-byte keys work.
        # rat-tail: a table, not a parser; unknown escape sequences are dropped in `_one`.
        mid = {_sequence(keys[action]): getattr(surface, method)
               for action, method in _MID_PRESS.items()}
        for action, amount in _MID_SCROLL.items():
            mid[_sequence(keys[action])] = lambda amount=amount: surface.scroll(amount)
        for sequence, step in self.CURSOR.items():
            mid.setdefault(sequence, lambda step=step: surface.move(step))
        mid[_MID_KEYS["up"]] = _recall_or(surface, mid.get(_MID_KEYS["up"]))
        # Longest first, so a short key cannot shadow a longer sequence.
        self._mid = dict(sorted(mid.items(), key=lambda entry: -len(entry[0])))

    def run(self) -> None:
        while not self._done.is_set():
            try:
                ready, _, _ = select.select([self._fd], [], [], INTERVAL)
            except (OSError, ValueError):
                return
            if not ready:
                continue
            try:
                data = os.read(self._fd, 1024)
            except OSError:
                return
            if not data:
                return
            self._feed(data)

    def _feed(self, data: bytes) -> None:
        """One read's worth of keys, applied to the line being typed."""
        if data == b"\x1b\x1b":
            # A fast double tap arrives as one read; only this exact read counts, so Alt sequences behind an ESC still match below.
            self._surface.escape_twice()
            return
        index = 0
        while index < len(data):
            # Any key but a lone ESC disarms a pending ESC, including keys dropped below.
            if data[index:] != b"\x1b":
                self._surface.disarm()
            for sequence, act in self._mid.items():
                if data[index:index + len(sequence)] == sequence:
                    act()
                    index += len(sequence)
                    break
            else:
                if not self._one(data, index):
                    return
                index += 1

    def _one(self, data: bytes, index: int) -> bool:
        """One byte of a read that matched no key sequence. False means drop the rest of the read. These keys are reserved from rebinding."""
        byte = data[index:index + 1]
        if byte in (b"\r", b"\n"):
            self._surface.submit()
        elif byte in self.BACKSPACE:
            self._surface.rubout()
        elif byte == b"\x1b":
            # An ESC that ends the read is a press; otherwise it starts an unknown sequence, dropped with the rest of the read.
            # rat-tail: a sequence split across reads arrives as a press; a short timer would fix it.
            if index == len(data) - 1:
                self._surface.escape()
            return False
        elif byte >= b" ":
            self._surface.keypress(byte.decode("utf-8", "replace"))
        return True

    def stop(self) -> None:
        self._done.set()
        self.join()


def _clock(at: datetime | None = None) -> str:
    """`at` - now when omitted - as HH:MM:SS in the operator's local zone. The screen stores UTC and converts only here."""
    return (at or datetime.now(timezone.utc)).astimezone().strftime("%H:%M:%S")


class _Block:
    """One emission and its rendered ANSI lines, cached per (width, expanded) so a repaint is a list concatenation. `at` is UTC."""

    __slots__ = ("channel", "text", "at", "_lines", "_key")

    def __init__(self, channel: str, text: str) -> None:
        self.channel, self.text = channel, text
        self.at = datetime.now(timezone.utc)
        self._lines, self._key = [], None

    def lines(self, surface: "Surface", width: int, expanded: bool = False) -> list[str]:
        # rat-tail: the local clock is baked into cached lines, so a TZ change shows only after a re-render.
        key = (width, expanded)
        if self._key != key:
            rendered = surface.render(self, width, expanded)
            # The separator belongs to the block so `_append`'s scroll arithmetic counts it; a tool result never gets one.
            spaced = not surface.condensed and self.channel != "tool_result"
            self._lines = [""] + rendered if spaced else rendered
            self._key = key
        return self._lines


class Surface:
    """Renders one session's output with `rich`; the only holder of rich types. Two consoles: stdout for the answer, stderr for everything else."""

    def __init__(self, roles: dict, *, markdown: bool, headless: bool = True,
                 keys: dict[str, str] | None = None) -> None:
        self._keys = keys or defaults()
        # A pygments theme name, not a style.
        self.code = roles["code"]
        self._user_pt = _pt_style(roles["user_text"])
        # Public: `ask:repl` builds its modal from outside this class.
        self.ask_pt = _pt_style(roles["ask"])
        self.glyphs = GLYPHS | {k[len("glyphs."):]: v
                                for k, v in roles.items() if k.startswith("glyphs.")}
        # The wider of the two marks, so every body starts in the same column.
        self._mark_cell = max(len(self.glyphs["bullet"]), len(self.glyphs["user"]))
        self._decorators = DECORATORS | {k[len("decorators."):]: v
                                         for k, v in roles.items()
                                         if k.startswith("decorators.")}
        self._labels = LABELS | {k[len("labels."):]: v
                                 for k, v in roles.items() if k.startswith("labels.")}
        layout = LAYOUT | {k[len("layout."):]: v
                           for k, v in roles.items() if k.startswith("layout.")}
        self.condensed = layout["condensed"].strip().lower() in TRUTHY
        theme, self.findings = _theme(roles)
        # Whether the answer is rendered as markdown, decided by stdout alone.
        self.markdown = markdown
        # No auto-highlighting; only the skin decides colour.
        self.out = Console(file=sys.stdout, theme=theme, highlight=False)
        self.err = Console(file=sys.stderr, theme=theme, highlight=False)
        self._waiting: _Waiting | None = None
        # The footer for the whole turn, or None when nothing is drawn.
        self._footer: dict | None = None
        self._pulse = ""
        # Rows the last draw laid down, for the next to erase.
        self._laid = 0
        # The pulse thread and `emit` both draw; reentrant because `emit` clears and redraws under one hold.
        self._lock = threading.RLock()
        # Answers how many rows lie below the cursor, which rich cannot.
        self._probe = create_output(stdout=sys.stderr)
        # The stdin terminal being typed at, or None for piped runs and test streams.
        try:
            self._tty = sys.stdin.fileno() if sys.stdin.isatty() else None
        except (AttributeError, OSError, ValueError):
            self._tty = None
        # The session clock `open` was given, so `reading` can restore the footer.
        self._elapsed = 0.0
        # A blocking read (e.g. a `_Menu`) owns the terminal; background writes must wait.
        self._held = False
        # Mid-turn typing and queued lines, drawn by the footer and handed to `_Line` when the turn ends.
        self._typed = ""
        # Insertion index into `_typed`, shared by `_typed_cell` and `_park`.
        self._caret = 0
        self._queued: list[str] = []
        # One ESC seen against a non-empty line mid-turn, awaiting a second; the prompt's arm is the module's `_escaped`.
        self._armed = False
        # SIGINT goes to this thread explicitly; a process-directed one might land on the reader thread.
        self._main = threading.main_thread().ident
        self._typing: _Typing | None = None
        # The original tty settings, restored exactly; None while unchanged.
        self._saved: list | None = None
        # --- the viewport -------------------------------------------------------------
        # Own the screen only for an interactive session on a terminal.
        self._viewport = sys.stderr.isatty() and not headless
        # Stderr rows are clock-stamped only on a real terminal descriptor.
        self._err_tty = sys.stderr.isatty()
        # Whether stdout is this same terminal; `sameopenfile`, since both can be different terminals.
        try:
            self._own_stdout = (sys.stdout.isatty() and sys.stderr.isatty()
                                and os.path.sameopenfile(sys.stdout.fileno(),
                                                         sys.stderr.fileno()))
        except (AttributeError, OSError, ValueError):
            self._own_stdout = False
        self._blocks: list[_Block] = []
        # Tool results shown whole, for the whole session.
        self._expanded = False
        # Every subagent entry in the caption (Alt-O), for the whole session.
        self._all_agents = False
        # (model, meter, elapsed) as `frame` last read them, so a toggle re-lays them without reading the records.
        self._captured = ("", None, 0.0)
        # A reply has been recorded since the meter was last read; the pulse thread re-reads it.
        self._stale = False
        # The session whose record Ctrl-T shows, and whether it is showing; inert with no session.
        self.session = None
        self._record: Path | None = None
        self._transcript = False
        # The record's painted lines cached per width, since painting it per frame is too slow.
        self._painted: list[str] = []
        self._painted_for: tuple[int, Path | None] | None = None
        # Lines scrolled back from the bottom; 0 follows the live end.
        self._offset = 0
        self._ceiling = 0
        self._painted_width = 0
        # Rows kept clear at the foot for the input box, or it would scroll the alternate buffer.
        self._reserved = 0
        # The prompt_toolkit Application drawing in those rows, whose contents a paint leaves alone.
        self.app = None
        self._entered = False
        # Renders to a string at an explicit width, for block caching.
        self._pen = Console(file=io.StringIO(), theme=theme, highlight=False,
                            force_terminal=True, width=MIN_WIDTH)

    def _gutter(self, mark: str, mark_style: str, body, body_style: str, indent: int = 0,
                label: str = "", clock: str = ""):
        """A gutter row as a grid: optional clock, indent, the mark in a `_mark_cell`-wide column, optional `label:`, then the body, which wraps under itself.

        A `str` body becomes `Text`, never markup, or bracketed names like `[dev-flow-builder]` vanish.
        """
        grid = Table.grid(padding=(0, 1))
        cells = []
        if clock:
            grid.add_column(width=len(clock), no_wrap=True, style="time")
            cells.append(Text(clock))
        if indent:
            grid.add_column(width=indent)
            cells.append("")
        grid.add_column(width=self._mark_cell, style=mark_style)
        cells.append(mark)
        if label:
            grid.add_column(style="agent", no_wrap=True)
            cells.append(Text(f"{label}:"))
        grid.add_column(overflow="fold", style=body_style)
        cells.append(Text(body) if isinstance(body, str) else body)
        grid.add_row(*cells)
        return grid

    def _speaker(self, text: str) -> tuple[str, str]:
        """(speaking agent, line without its tag); untagged is the main label, and an empty line gets no name."""
        tagged = AGENT_TAG.match(text)
        name, text = (tagged.group(1), text[tagged.end():]) if tagged else (self._labels["main"], text)
        return (name if text.strip() else ""), text

    @staticmethod
    def _result(text: str) -> str:
        """A tool result without the agent tag: it sits under the call that already names it."""
        tagged = AGENT_TAG.match(text)
        return text[tagged.end():] if tagged else text

    # --- the footer: a live region at the foot of the screen ----------------------
    #
    # Drawn by hand during a turn; between turns the input line draws its own box, and `close` hands over.

    def _rows_below(self) -> int:
        """Rows between the cursor and the foot of the screen, asked of the terminal; 0 when it will not answer."""
        try:
            return self._probe.get_rows_below_cursor_position()
        except Exception:
            return 0

    def _rows(self) -> list[str]:
        """The footer's lines, top to bottom. The pulse row is always present, so the box does not move."""
        frame, width = self._footer, self._width()
        return [
            self._paint(self._pulse, "waiting"),
            # Queued lines, oldest first, cut to the width so none wraps.
            *(self._paint(f'{self.glyphs["user"]} {line}'[:width], "pending")
              for line in self._queued),
            frame["top"],
            frame["marker"] + self._typed_cell(width)
            + self._paint(self.glyphs["vertical"], "border"),
            frame["bottom"],
            frame["caption"],
            *frame["more"],
        ]

    def _status_bar(self, width: int) -> str:
        """The status bar row, exactly `width` wide. Read per paint, since `/resume` changes the session id."""
        session = self.session
        fields = _Fields(version=f"un v{VERSION}",
                         session=f"session {_shown(session)}" if session is not None else "",
                         project=str(session.cwd) if session is not None else "")
        try:
            text = self._decorators["status_bar_text"].format_map(fields)
        except (ValueError, IndexError):
            # A malformed template is drawn as written.
            text = self._decorators["status_bar_text"]
        return self._paint(text[:width].ljust(width), self._decorators["status_bar"])

    def _inner_divider(self, width: int) -> str:
        """A full-width divider rule, in the role the skin named it with."""
        return self._paint(_fill(self.glyphs["inner_divider"], width),
                           self._decorators["inner_divider"])

    def _decorator_rows(self, width: int) -> tuple[list[str], list[str]]:
        """The skin's decorator rows above and below the conversation."""
        top = []
        if self._decorators["status_bar"]:
            top.append(self._status_bar(width))
        if self._decorators["inner_divider"]:
            top.append(self._inner_divider(width))
        return top, [self._inner_divider(width)] if self._decorators["inner_divider"] else []

    @property
    def _margin(self) -> int:
        """Columns before the input text: edge, space, marker, space. Shared by `_inner`, `_park`, `frame` and `_Line`."""
        return len(self.glyphs["vertical"]) + len(self.glyphs["user"]) + 2

    def _inner(self, width: int) -> int:
        """Columns the input row has for text."""
        return max(0, width - (self._margin + len(self.glyphs["vertical"])))

    def _window(self, inner: int) -> int:
        """Index of the first visible character of `_typed`, so the view ends at the caret.

        rat-tail: scrolls one column at a time; a held window would move only when the caret leaves it.
        """
        return max(0, self._caret - inner + 1)

    def _typed_cell(self, width: int) -> str:
        """The input row's body: the visible window of `_typed`, padded on plain text before styling."""
        inner = self._inner(width)
        if not inner:
            return ""
        start = self._window(inner)
        return self._paint(self._typed[start:start + inner].ljust(inner), "user")

    def keypress(self, char: str) -> None:
        """Insert a character at the caret. Called from `_Typing`'s thread."""
        with self._lock:
            self._typed = self._typed[:self._caret] + char + self._typed[self._caret:]
            self._caret += len(char)
            self._repaint()

    def rubout(self) -> None:
        """Delete the character before the caret. The guard stops `[:-1]` eating from the end at caret 0."""
        with self._lock:
            if self._caret:
                self._typed = self._typed[:self._caret - 1] + self._typed[self._caret:]
                self._caret -= 1
            self._repaint()

    def submit(self) -> None:
        """Enter: queue the line as a later prompt; the running turn is not redirected."""
        with self._lock:
            if self._typed.strip():
                self._queued.append(self._typed)
            self._typed, self._caret = "", 0
            self._repaint()

    def move(self, step: int) -> None:
        """Move the caret, clamped to the line; repaint only if it moved."""
        with self._lock:
            caret = min(max(self._caret + step, 0), len(self._typed))
            if caret != self._caret:
                self._caret = caret
                self._repaint()

    def disarm(self) -> None:
        """Forget a pending ESC. Called from `_Typing`'s thread for every other key."""
        with self._lock:
            self._armed = False

    def escape_twice(self) -> None:
        """Two ESCs in one read: clear a non-empty line, never end the turn. Checked and cleared under one lock so `take_partial` cannot empty the line in between."""
        with self._lock:
            self._armed = False
            if self._typed:
                self._typed, self._caret = "", 0
                self._repaint()

    def escape(self) -> None:
        """One ESC during a turn: two presses clear a non-empty line; against an empty line it ends the turn. Queued lines are untouched; a double tap in one read is `escape_twice`, and the prompt has its own arm (`_escape`)."""
        with self._lock:
            if self._typed:
                # The second press clears exactly as a double tap does; the lock is reentrant.
                if self._armed:
                    self.escape_twice()
                else:
                    self._armed = True
                return
            self._armed = False
        # Outside the lock, or the signal could deadlock against `emit` holding it.
        signal.pthread_kill(self._main, signal.SIGINT)

    def _repaint(self) -> None:
        """Redraw the footer in place. The caller holds the lock."""
        if self._viewport:
            self._paint_screen()
        elif self._footer is not None:
            self._erase()
            self._draw()

    def recall(self) -> bool:
        """Move the newest queued line back into the input, replacing what was typed. False when nothing was queued."""
        with self._lock:
            if not self._queued:
                return False
            self._typed = self._queued.pop()
            self._caret = len(self._typed)
            self._repaint()
            return True

    def take_queued(self) -> list[str]:
        """The finished lines, in the order they were typed. Emptied by the taking."""
        with self._lock:
            lines, self._queued = self._queued, []
            return lines

    def take_partial(self) -> str:
        """The unfinished line, handed to `_Line` rather than sent. Emptied by the taking."""
        with self._lock:
            partial, self._typed, self._caret = self._typed, "", 0
            return partial

    def put_partial(self, text: str) -> None:
        """Hand an unfinished line back, caret at its end, for the next read to open with."""
        with self._lock:
            self._typed, self._caret = text, len(text)

    def _draw(self) -> None:
        """Draw the footer at the foot of the screen and park the cursor on its first row, so `_erase` can reclaim it."""
        rows = self._rows()
        pad = max(0, self._rows_below() - len(rows))
        out = self.err.file
        out.write("\n" * pad + "\n".join(rows))
        out.write(f"\r\x1b[{pad + len(rows) - 1}A" if pad + len(rows) > 1 else "\r")
        out.flush()
        self._laid = pad + len(rows)

    def _erase(self) -> None:
        """Clear from the parked cursor (the footer's first row) to the end of the screen."""
        if self._laid:
            self.err.file.write("\x1b[J")
            self.err.file.flush()
            self._laid = 0

    def _capture(self, on: bool) -> None:
        """Turn off ECHO and ICANON for the turn so keys arrive unechoed and unbuffered, or restore the saved settings exactly. ISIG stays on for Ctrl-C."""
        if self._tty is None:
            return
        try:
            if on:
                if self._saved is None:
                    self._saved = termios.tcgetattr(self._tty)
                attrs = termios.tcgetattr(self._tty)
                attrs[3] &= ~(termios.ECHO | termios.ICANON)
                attrs[6][termios.VMIN] = 1
                attrs[6][termios.VTIME] = 0
                termios.tcsetattr(self._tty, termios.TCSANOW, attrs)
            elif self._saved is not None:
                termios.tcsetattr(self._tty, termios.TCSANOW, self._saved)
                self._saved = None
        except termios.error:
            return

    def _flush_input(self) -> None:
        """Discard buffered keystrokes before a question, so a stray "y" cannot answer an unseen prompt."""
        if self._tty is None:
            return
        try:
            termios.tcflush(self._tty, termios.TCIFLUSH)
        except termios.error:
            return

    @property
    def held(self) -> bool:
        """Whether a blocking read owns the terminal; background writers check this before painting."""
        return self._held

    @contextlib.contextmanager
    def reading(self, session):
        """Stop the pulse, take the footer down and restore echo for a blocking read, then put everything back."""
        self.settle()
        self.close()
        self._flush_input()
        self._held = True
        try:
            yield
        finally:
            # The figures the turn started with, not a fresh read of the records.
            self.open(session, self._elapsed, fresh=False)
            self.wait(session)
            # Cleared last, so the hold covers the restore too.
            self._held = False

    def open(self, session, elapsed: float, fresh: bool = True) -> None:
        """Put the footer on screen for the turn. Never off a terminal. `fresh` as for `frame`."""
        if not sys.stderr.isatty():
            return
        with self._lock:
            self._elapsed = elapsed
            self._footer = self.frame(session, elapsed, fresh)
            self._pulse = ""
            if self._viewport:
                self._reserved = 0
                self._paint_screen()
            else:
                self._draw()
        # After the draw, and outside the lock.
        self._capture(True)

    def close(self, more: int = 0) -> None:
        """Take the footer down and give back the keyboard. Idempotent; every path out of a footer goes through here. `more` is the expanded caption rows the coming input box draws."""
        self.settle()
        with self._lock:
            if self._viewport:
                # Reserve the footer's rows for the input box.
                self._reserved = FOOTER_ROWS + more
                self._footer = None
                self._pulse = ""
                self._paint_screen()
            elif self._footer is not None:
                self._erase()
                self._footer = None
                self._pulse = ""
        self._capture(False)

    def pulse(self, text: str) -> None:
        """Advance the animation row. Called from `_Waiting`\'s thread."""
        with self._lock:
            if self._footer is None:
                return
            self._pulse = text
            if self._viewport:
                self._paint_screen()
            else:
                self._erase()
                self._draw()

    def banner(self, session) -> None:
        """Draw the welcome box, at most `BANNER_WIDTH + 2` wide, with the first art that fits."""
        total = min(BANNER_WIDTH + 2, self._width())
        interior = total - 2 * len(self.glyphs["vertical"])
        # The operator's `.un/banner.txt`, then the wordmark, then the monogram.
        art = ()
        for candidate in (self._art(session.root), WORDMARK, MONOGRAM):
            if candidate and interior >= max(len(row) for row in candidate) + 2:
                art = candidate
                break
        rows = [self.banner_line(self.glyphs["top_left"], self.glyphs["top_right"], total)]
        rows += [self._row(row, "banner_art", total) for row in art]
        rows += [self._row("", "banner_text", total)] if art else []
        rows += [self._row(text, "banner_text", total)
                 for text in (f"   {self.glyphs['bullet']} v{VERSION} - session: {session.id}",
                              f"   {self.glyphs['bullet']} {session.cwd}")]
        rows.append(self.banner_line(self.glyphs["bottom_left"],
                                    self.glyphs["bottom_right"], total))
        if self._viewport:
            with self._lock:
                self._append("banner", "\n".join(rows))
                self._paint_screen()
            return
        # Not through rich, which would count the escape bytes toward the width.
        self.err.file.write("\n".join(rows) + "\n")
        self.err.file.flush()

    @staticmethod
    def _art(cwd) -> tuple:
        """`.un/banner.txt` as lines with blank edges trimmed, or () when unreadable."""
        try:
            text = (core.un_dir(cwd, "banner.txt")).read_text(encoding="utf-8")
        except OSError:
            return ()
        lines = [line.rstrip("\n") for line in text.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return tuple(lines)

    def _row(self, text: str, style: str, total: int) -> str:
        """One banner row exactly `total` wide, padded or truncated (never wrapped) on the plain text."""
        edge = self._paint(self.glyphs["vertical"], "border")
        inner = max(0, total - 2 * len(self.glyphs["vertical"]))
        return f"{edge}{self._paint(f' {text} '[:inner].ljust(inner), style)}{edge}"

    # --- the viewport: the conversation as blocks, repainted whole ---------------------

    def render(self, block: _Block, width: int, expanded: bool = False) -> list[str]:
        """One block's ANSI lines at `width`. Called by `_Block` on a cache miss."""
        if block.channel == "banner":
            # Already painted; rich would miscount its escapes.
            return block.text.split("\n")
        self._pen.width = width
        with self._pen.capture() as captured:
            self._pen.print(self._renderable(block, expanded))
        return captured.get().rstrip("\n").split("\n")

    def _renderable(self, block: _Block, expanded: bool = False):
        """The block as a renderable, matching what `_write` prints (except that `_write` shows the clock only on a terminal)."""
        channel, text, clock = block.channel, block.text, _clock(block.at)
        if channel == "reply":
            name, text = self._speaker(text)
            return self._gutter(self.glyphs["bullet"], "bullet",
                                _Reply(text, code_theme=self.code), "assistant", label=name,
                                clock=clock)
        if channel == "tool_result":
            text = self._result(text)
            body = text if expanded else _collapse(text, self._keys["expand"])
            return self._gutter(BRANCH, "bullet", body, "tool_result", indent=RESULT_INDENT,
                                clock=clock)
        if channel == "tool":
            name, text = self._speaker(text)
            return self._gutter(self.glyphs["bullet"], "bullet", text, "tool",
                                indent=TOOL_INDENT, label=name, clock=clock)
        if channel == "echo":
            return self._gutter(self.glyphs["user"], "user", text, "user_text", clock=clock)
        if channel == "note":
            # No glyph: a mark would suggest the model is speaking.
            return self._gutter(" ", "bullet", text, "note", clock=clock)
        mark_style = {"error": "error", "interrupted": "interrupted"}.get(channel, "bullet")
        return self._gutter(self.glyphs["bullet"], mark_style, text, channel, clock=clock)

    def _size(self) -> tuple[int, int]:
        """The screen as (`_width()`, height); height guarded against a pty that reports 0 rows."""
        try:
            lines = os.get_terminal_size(sys.stderr.fileno()).lines
        except OSError:
            lines = 0
        if lines <= 0:
            lines = self.err.size.height
        # A floor deep enough for the footer plus something to look at.
        return self._width(), max(len(FRAMES) + 2, lines)

    def _paint_screen(self) -> None:
        """Repaint the whole screen (conversation window, then footer); the caller holds the lock.

        One `CURSOR_HOME`, then one row per terminal row, each cleared to its end, with no clear-first (which would flicker). Rows owned by a live input box are walked through uncleared and the cursor is restored for prompt_toolkit; otherwise `_park` places it. Resizes are picked up here, without a SIGWINCH handler.
        """
        if not self._viewport:
            return
        width, height = self._size()
        self._painted_width = width
        body = self._body(width)
        foot = self._rows() if self._footer is not None else []
        top, bottom = self._decorator_rows(width)
        room = height - len(foot) - self._reserved - len(top) - len(bottom)
        if room < CONVERSATION_FLOOR:
            # Decorators come off entirely rather than crowd out the conversation.
            top, bottom = [], []
            room = height - len(foot) - self._reserved
        room = max(1, room)
        self._ceiling = max(0, len(body) - room)
        self._offset = min(self._offset, self._ceiling)
        start = self._ceiling - self._offset
        view = body[start:start + room]
        view += [""] * (room - len(view))
        rows = top + view + bottom + foot + [""] * self._reserved
        # Clearing a live input box's rows would erase a box prompt_toolkit thinks is still drawn.
        live = self.app is not None and self._reserved > 0
        cleared = len(rows) - self._reserved if live else len(rows)
        out = self.err.file
        # No newline after the last row, or the alternate buffer scrolls on every repaint.
        body = "\r\n".join(f"{row}{ERASE_LINE}" if n < cleared else row
                           for n, row in enumerate(rows))
        if live:
            out.write(SAVE_CURSOR + CURSOR_HOME + body + RESTORE_CURSOR)
        else:
            out.write(CURSOR_HOME + body + self._park(width, height))
        out.flush()

    def _park(self, width: int, height: int) -> str:
        """The cursor move ending a frame: at the caret in the footer's input row during a turn, at the first reserved row between turns, else ""."""
        if self._footer is not None:
            # The input row sits above the bottom rule, the caption and any expanded caption rows.
            column = self._margin + self._caret - self._window(self._inner(width))
            return f"\x1b[{height - 2 - len(self._footer['more'])};{column + 1}H"
        if self._reserved:
            return f"\x1b[{height - self._reserved + 1};1H"
        return ""

    def _body(self, width: int) -> list[str]:
        """What the screen shows as lines: the session record under Ctrl-T, else the conversation. Scrolling works the same on either."""
        return self._tailed(width) if self._transcript else self._conversation(width)

    def _conversation(self, width: int) -> list[str]:
        """The conversation as lines."""
        return [line for block in self._blocks
                for line in block.lines(self, width, self._expanded)]

    @staticmethod
    def _view():
        """`view:transcript`, or None when the session_view plugin is disabled."""
        try:
            return use("view", "transcript")
        except LookupError:
            return None

    @property
    def record(self) -> Path | None:
        """This session's record path, resolved per read because `/resume` changes the id."""
        if self.session is not None:
            return session_file(self.session.root, self.session.id)
        return self._record

    @record.setter
    def record(self, path: Path | None) -> None:
        self._record = path

    def _record_pairs(self, width: int) -> list[tuple[str, str]]:
        """The record as (role, line) pairs at `width`. Empty when there is none to read."""
        view = self._view()
        record = self.record
        if view is None or record is None:
            return []
        return view(record, width)

    def _tailed(self, width: int) -> list[str]:
        """The record's painted lines, painting only new ones (the record is append-only). The cache resets on a width or record change."""
        pairs = self._record_pairs(width)
        if self._painted_for != (width, self.record):
            self._painted, self._painted_for = [], (width, self.record)
        self._painted += [self._paint(line, role)
                          for role, line in pairs[len(self._painted):]]
        return self._painted

    def _append(self, channel: str, text: str) -> None:
        """Add a block, keeping the view where the operator put it. Caller holds the lock."""
        block = _Block(channel, text)
        self._blocks.append(block)
        del self._blocks[:-MAX_BLOCKS]
        if self._offset:
            # Scrolled back: grow the offset so the same lines stay in view.
            width = self._painted_width or self._size()[0]
            self._offset += len(block.lines(self, width, self._expanded))

    def toggle(self) -> None:
        """Ctrl-O: expand or collapse every tool result, as a repaint."""
        with self._lock:
            self._expanded = not self._expanded
            self._paint_screen()

    def mark_stale(self) -> None:
        """A reply was recorded somewhere in this session. Called from any agent's thread."""
        self._stale = True

    def refresh(self) -> None:
        """Re-read the meter if a reply landed since the last read, and re-lay the footer from it; the next paint shows it. Called from `_Waiting`'s thread."""
        if not self._stale or self.session is None:
            return
        # Cleared before the read, so a reply landing during it marks the figures stale again.
        self._stale = False
        meter = _read_meter(self.session)
        with self._lock:
            if self._footer is None:
                return
            model, _, elapsed = self._captured
            self._captured = (model, meter, elapsed)
            self._footer = self._lay()

    def agents(self) -> None:
        """Alt-O: every subagent entry in the caption, or only those that fit. Mid-turn the footer is re-laid from the figures already read; between turns `_turns` re-enters the read."""
        with self._lock:
            self._all_agents = not self._all_agents
            if self._footer is not None:
                self._footer = self._lay()
                self._repaint()

    def transcript(self) -> None:
        """Ctrl-T: switch between the session record and the conversation. With nothing to show, a note says why instead; switching back always works."""
        if not self._viewport:
            return
        if not self._transcript and not self._record_pairs(self._width()):
            self.note(NO_READER if self._view() is None
                      else NO_RECORD.format(key=_spell(self._keys["transcript"])))
            return
        with self._lock:
            self._transcript = not self._transcript
            # The two bodies' line counts are unrelated, so return to the live end.
            self._offset = 0
            self._paint_screen()

    def hold(self, rows: int, app) -> None:
        """Reserve `rows` at the foot for `app` and park the cursor on the first of them, so a repaint scrolls the conversation above it and leaves it drawn."""
        with self._lock:
            if self._viewport:
                # rat-tail: a box taller than the screen still overflows it, leaving nothing to scroll.
                self._reserved = max(1, min(rows, self._size()[1] - 1))
                # Painted before `app` is set, so this frame parks the cursor where the box starts.
                self._paint_screen()
            self.app = app

    def scroll(self, lines: int) -> None:
        """Move the window; positive is back through the conversation, clamped to its ends."""
        with self._lock:
            if not self._viewport:
                return
            self._offset = max(0, min(self._ceiling, self._offset + lines))
            self._paint_screen()

    def note(self, text: str) -> None:
        """Something the loop says rather than the model, such as a slash result."""
        self.emit("note", text)

    def start(self) -> None:
        """Enter the alternate screen and turn on wheel-as-arrows. Once per session."""
        if not self._viewport or self._entered:
            return
        self._entered = True
        self.err.file.write(ALT_ON + WHEEL_ON)
        self.err.file.flush()

    def stop(self) -> None:
        """Leave the alternate screen, then write the conversation into real scrollback. Called from `loop`'s `finally`."""
        if not self._viewport or not self._entered:
            return
        self._entered = False
        out = self.err.file
        out.write(WHEEL_OFF + ALT_OFF)
        # The conversation, even if Ctrl-T was showing the record.
        out.write("\n".join(self._conversation(self._size()[0])) + "\n")
        out.flush()

    def emit(self, channel: str, text: str) -> None:
        """The sink `core` writes to. Only `reply` goes to stdout. Text deltas are dropped; the answer renders once from `reply` (D15).

        Under a viewport, the reply is painted if stdout is this screen, else written to stdout plain.
        """
        with self._lock:
            if self._viewport:
                if channel not in PAINTED:
                    return
                if channel == "reply" and not self._own_stdout:
                    self._write(channel, text)
                    return
                self._append(channel, text)
                self._paint_screen()
                return
            # Erase and redraw the footer around the write, all under the lock, so output lands above it.
            self._erase()
            self._write(channel, text)
            if self._footer is not None:
                self._draw()

    def _write(self, channel: str, text: str) -> None:
        """One channel\'s line, with no footer bookkeeping. `emit` owns that."""
        if channel == "reply":
            if not self.markdown:
                # Redirected stdout gets plain text (A9).
                print(self._result(text))
                return
            name, text = self._speaker(text)
            self.out.print(self._gutter(self.glyphs["bullet"], "bullet",
                                        _Reply(text, code_theme=self.code),
                                        "assistant", label=name, clock=_clock()))
            return
        clock = _clock() if self._err_tty else ""
        if channel == "error":
            self.err.print(self._gutter(self.glyphs["bullet"], "error", text, "error",
                                        clock=clock))
        elif channel == "interrupted":
            self.err.print(self._gutter(self.glyphs["bullet"], "interrupted", text,
                                        "interrupted", clock=clock))
        elif channel == "note":
            # No glyph: a mark would suggest the model is speaking.
            self.err.print(self._gutter(" ", "bullet", text, "note", clock=clock))
        elif channel == "tool":
            name, text = self._speaker(text)
            self.err.print(self._gutter(self.glyphs["bullet"], "bullet", text, "tool",
                                        indent=TOOL_INDENT, label=name, clock=clock))
        elif channel == "tool_result":
            self.err.print(self._gutter(BRANCH, "bullet", self._result(text), "tool_result",
                                        indent=RESULT_INDENT, clock=clock))

    def wait(self, session) -> None:
        """Start the pulse and the mid-turn key reader, when there is a footer."""
        if self._footer is None:
            return
        self._waiting = _Waiting(self, session)
        self._waiting.start()
        # Started together with the pulse so `settle` ends both.
        if self._tty is not None:
            self._typing = _Typing(self, self._tty, self._keys)
            self._typing.start()

    def settle(self) -> None:
        """Stop the pulse and join the key reader (two stdin readers would lose keystrokes). Idempotent; the footer stays."""
        if self._waiting is not None:
            self._waiting.stop()
            self._waiting = None
        if self._typing is not None:
            self._typing.stop()
            self._typing = None

    def interrupted(self) -> None:
        """Stop the pulse, then say the operator ended the turn (a live pulse would draw over it)."""
        self.settle()
        self.emit("interrupted", INTERRUPTED)

    def _status(self, session, elapsed: float) -> str:
        """The caption under the input box: session clock, session total, then model and meter."""
        meter = _read_meter(session)
        return "  " + " | ".join([_elapsed(_minutes(elapsed), meter), _head(session.model, meter)])

    def _paint(self, text: str, style: str) -> str:
        """`text` in the skin's `style`, captured as a string; plain when stderr is not a terminal. `markup=False` so brackets survive."""
        with self.err.capture() as captured:
            self.err.print(text, style=style, end="", markup=False)
        return captured.get()

    def _width(self) -> int:
        """The frame width from the terminal device (as prompt_toolkit measures it, not rich's `COLUMNS`), one short of the edge so rules do not wrap."""
        try:
            width = os.get_terminal_size(sys.stderr.fileno()).columns
        except OSError:
            width = 0
        if width <= 0:
            width = self.err.width
        return max(MIN_WIDTH, width - 1)

    def rule(self, left: str, right: str) -> str:
        """A painted box rule at the screen's width, ending in the given corners."""
        return self.banner_line(left, right, self._width())

    def banner_line(self, left: str, right: str, total: int) -> str:
        """A painted box rule exactly `total` columns wide including its corners."""
        return self._paint(
            f"{left}{_fill(self.glyphs['horizontal'], total - len(left) - len(right))}{right}",
            "border")

    def frame(self, session, elapsed: float, fresh: bool = True) -> dict:
        """The input box as painted pieces, for the input line to assemble around its own region. Settles the pulse first, then reads the meter, unless `fresh` is False, which keeps the figures last read."""
        self.settle()
        meter = _read_meter(session) if fresh else self._captured[1]
        self._captured = (session.model, meter, elapsed)
        return self._lay()

    def _lay(self) -> dict:
        """The frame from the captured figures, with the caption collapsed or expanded as toggled. Reads nothing and settles nothing."""
        model, meter, elapsed = self._captured
        collapsed, first, more = _caption(model, meter, _minutes(elapsed), self._width())
        rule = self._paint(f'{self.glyphs["vertical"]} ', "border")
        return {
            "top": self.rule(self.glyphs["top_left"], self.glyphs["top_right"]),
            "marker": rule + self._paint(f'{self.glyphs["user"]} ', "user"),
            # The margin beside a wrapped row: the rule without the marker, same width.
            "under": rule + " " * (len(self.glyphs["user"]) + 1),
            "edge": rule,
            "bottom": self.rule(self.glyphs["bottom_left"], self.glyphs["bottom_right"]),
            # Columns, since the painted strings' lengths include escapes.
            "margin": self._margin,
            "caption": self._paint(first if self._all_agents else collapsed, "status"),
            # The expanded caption's further rows, one painted row each; empty when collapsed.
            "more": [self._paint(row, "status") for row in more] if self._all_agents else [],
            # A prompt_toolkit style, not painted bytes.
            "user_pt": self._user_pt,
        }

    def echo(self, line: str) -> None:
        """Leave the submitted line in the conversation, since the input box is erased on submit."""
        if self._viewport:
            with self._lock:
                self._append("echo", line)
                self._paint_screen()
            return
        self.err.print(self._gutter(self.glyphs["user"], "user", line, "user_text",
                                    clock=_clock() if self._err_tty else ""))

    def prompt(self, session, elapsed: float) -> None:
        """The unboxed prompt for a supplied stream, where the terminal does its own echo."""
        self.settle()
        self.err.print(self._status(session, elapsed).strip(),
                       style="status", markup=False)
        self.err.print(f'{self.glyphs["user"]} ', style="user", end="", markup=False)


class _Commands(Completer):
    """Complete `/name` at column 0 from the live registry, and an `@` that starts a word to a project path. Both match substrings.

    Slash names are read per keystroke, so `/reload` additions appear. The path walk is cached per read (`refresh`), and inserts a bare root-relative path.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._paths: list[tuple[str, str]] | None = None

    def refresh(self) -> None:
        """Drop the cached walk. `_Line.read` calls it once per read."""
        self._paths = None

    def _candidates(self) -> list[tuple[str, str]]:
        """Each candidate as (shown, inserted); they differ only for `@project_root`, which inserts `.`. Cached until `refresh`."""
        if self._paths is None:
            self._paths = [("@project_root", ".")]
            self._paths += [(path.as_posix(),) * 2 for path in core.walk(self.root)]
        return self._paths

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            name = text[1:]
            if not (" " in name or "\n" in name):
                for candidate in sorted(set(variants("slash")) | core.QUIT):
                    if name in candidate:
                        yield Completion(candidate, start_position=-len(name))
                return
            # In a command's argument, `@` completes paths too.
        at = text.rfind("@")
        if at < 0 or (at and not text[at - 1].isspace()):
            # An `@` inside a word (an email address) is prose.
            return
        typed = text[at + 1:]
        if any(char.isspace() for char in typed):
            return
        for shown, insert in self._candidates():
            if typed in shown:
                # Replaces the `@` too.
                yield Completion(insert, start_position=-(len(typed) + 1), display=shown)


# The section of `.un/config.toml` an operator moves a key in.
SECTION = "keys"

# Rebindable action -> (default key, whether it also works mid-turn and so needs a byte sequence). Enter, Ctrl-C and Ctrl-D are not rebindable.
ACTIONS = {
    "expand":      ("c-o", True),
    "transcript":  ("c-t", True),
    # Show every subagent's figures in the caption, or only those that fit.
    "agents":      ("escape o", True),
    "editor":      ("c-x c-e", False),
    "compose":     ("escape enter", False),
    "scroll_up":   ("up", True),
    "scroll_down": ("down", True),
    "page_up":     ("pageup", True),
    "page_down":   ("pagedown", True),
    "top":         ("home", False),
    "bottom":      ("end", False),
    # Scroll the conversation while an AskUser menu is open, where Up and Down move its focus.
    "menu_scroll_up":   ("c-up", False),
    "menu_scroll_down": ("c-down", False),
}

# Keys no action may take: the three conventions, plus bytes `_Typing._one` handles itself.
RESERVED = {
    "c-m": "submit",            # Enter
    "c-c": "cancel",
    "c-d": "end",
    "c-j": "submit",            # the other newline byte `_Typing` answers as Enter
    "c-h": "rubout",            # backspace
    "escape": "the escape arm",
}


# Named keys the mid-turn reader understands, as tty bytes; the arrows are also the wheel.
_MID_KEYS = {"up": b"\x1b[A", "down": b"\x1b[B",
             "pageup": b"\x1b[5~", "pagedown": b"\x1b[6~"}


def defaults() -> dict[str, str]:
    """Every action at the key it ships with. What an absent `[keys]` means."""
    return {name: key for name, (key, _) in ACTIONS.items()}


# Operator-facing modifier spellings; config accepts these and prompt_toolkit's `c-x`. Alt is an ESC prefix.
CTRL, ALT = "ctrl-", "alt-"


def _fold(token: str) -> list[str]:
    """One written token as prompt_toolkit tokens: `alt-` becomes a leading `escape`, `ctrl-` becomes `c-`, in either order.

    A bare prefix is left whole so validation refuses it, rather than becoming a bare `escape`.
    """
    if token.startswith(ALT) and token[len(ALT):]:
        return ["escape", *_fold(token[len(ALT):])]
    if token.startswith(CTRL) and token[len(CTRL):].startswith(ALT):
        return _fold(ALT + CTRL + token[len(CTRL) + len(ALT):])
    if token.startswith(CTRL):
        return [f"c-{token[len(CTRL):]}"]
    return [token]


def _normalise(key: str) -> str:
    """`key` in one canonical spelling (`enter` is `c-m`, ...) so collisions are visible. Prefixes fold before aliases apply."""
    folded = [part for token in key.split() for part in _fold(token)]
    return " ".join(KEY_ALIASES.get(token, token) for token in folded)


def _spell(key: str) -> str:
    """`key` in the operator's spelling (`ctrl-`, `alt-`), for messages. The inverse of `_fold`."""
    tokens, out = key.split(), []
    while tokens:
        token = tokens.pop(0)
        prefix = ""
        if token == "escape" and tokens:
            prefix, token = ALT, tokens.pop(0)
        out.append(f"{CTRL}{prefix}{token[2:]}" if token.startswith("c-")
                   else f"{prefix}{token}")
    return " ".join(out)


def _sequence(key: str) -> bytes | None:
    """The bytes a tty sends for `key`, or None.

    rat-tail: only control letters, Alt combinations and `_MID_KEYS`; prompt_toolkit's key processor is the upgrade.
    """
    head, _, rest = key.partition(" ")
    if head == "escape" and rest:
        # A printable character is allowed only behind Alt; bare, it would eat typed letters.
        tail = _sequence(rest) or (rest.encode() if len(rest) == 1 else None)
        return b"\x1b" + tail if tail else None
    if key in _MID_KEYS:
        return _MID_KEYS[key]
    if len(key) == 3 and key.startswith("c-") and key[2].isalpha():
        return bytes([ord(key[2].lower()) - 96])
    return None


def keymap(root: Path) -> dict[str, str]:
    """`[keys]` from `root`'s config merged over the defaults; every action is present. ValueError (-> EXIT_USAGE) when malformed; absent means defaults."""
    resolved = defaults()
    path = Path(root) / core.CONFIG
    if not path.is_file():
        return resolved
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    table = raw.get(SECTION)
    if table is None:
        return resolved
    if not isinstance(table, dict):
        raise ValueError(
            f"{path}: [{SECTION}] must be a table of <action> = \"<key>\" lines, one per "
            f"action - the actions are {', '.join(sorted(ACTIONS))}")
    for name, value in table.items():
        if name not in ACTIONS:
            raise ValueError(
                f"{path}: [{SECTION}] has unknown action {name!r}; the actions are "
                f"{', '.join(sorted(ACTIONS))}")
        if type(value) is not str:
            raise ValueError(
                f"{path}: [{SECTION}].{name} must be str, not {type(value).__name__}")
        resolved[name] = _validated(path, name, value)
    _distinct(path, resolved)
    return resolved


def _validated(path: Path, name: str, value: str) -> str:
    """`value` normalised, or a ValueError saying why this action cannot take it."""
    key = _normalise(value)
    if not key:
        raise ValueError(f"{path}: [{SECTION}].{name} must name a key")
    unknown = [token for token in key.split()
               if token not in ALL_KEYS and len(token) != 1]
    if unknown:
        raise ValueError(
            f"{path}: [{SECTION}].{name} = {value!r} is not a key un can bind; "
            f"{unknown[0]!r} names nothing")
    # Two ESCs in a row are the escape arm's double tap (`escape_twice`, `_escape`), so no key may open with them.
    held = RESERVED["escape"] if key.split()[:2] == ["escape", "escape"] else RESERVED.get(key)
    if held:
        raise ValueError(
            f"{path}: [{SECTION}].{name} = {value!r} is held by {held} and "
            "cannot be moved")
    if ACTIONS[name][1] and _sequence(key) is None:
        # Mid-turn actions need a key whose bytes the reader can match.
        raise ValueError(
            f"{path}: [{SECTION}].{name} = {value!r} works at the prompt but not while a "
            f"turn is running, and {name} needs both; use {CTRL}<letter>, {ALT}<key>, "
            f"{', '.join(sorted(_MID_KEYS))}")
    return key


def _distinct(path: Path, resolved: dict[str, str]) -> None:
    """Refuse two actions on one key, checked normalised on the merged map so an override colliding with a default is caught."""
    resolved = {name: _normalise(key) for name, key in resolved.items()}
    for name, key in resolved.items():
        clash = sorted(other for other, value in resolved.items()
                       if value == key and other != name)
        if clash:
            raise ValueError(
                f"{path}: [{SECTION}] binds {key!r} to both {sorted([name, *clash])[0]} "
                f"and {sorted([name, *clash])[1]}; a key does one thing")


def _submit(event) -> None:
    """Enter submits: the buffer is multiline, and the read's result is the line."""
    event.app.exit(result=event.current_buffer.text)


def _cancel(event) -> None:
    """Ctrl-C abandons the line; `loop` handles the KeyboardInterrupt."""
    event.app.exit(exception=KeyboardInterrupt, style="class:aborting")


def _end(event) -> None:
    """Ctrl-D ends the session, but only on an empty line."""
    if not event.current_buffer.text:
        event.app.exit(exception=EOFError, style="class:exiting")


def _escape(event) -> None:
    """ESC at the prompt: the first press against a non-empty box arms, the second clears it; an empty box has no turn to end."""
    global _escaped
    buffer = event.current_buffer
    if buffer.text and _escaped is not event.app:
        _escaped = event.app
        return
    _escaped = None
    if buffer.text:
        # Setting the text, not `reset()`, keeps history and lets Ctrl-_ undo the clear.
        buffer.text = ""


def _unarm(processor) -> None:
    """After every prompt key press, disarm an armed ESC, unless the press left a lone ESC pending as a possible Alt prefix: that is the second tap, which `_escape` answers on its flush."""
    global _escaped
    if [press.key for press in processor.key_buffer] != [Keys.Escape]:
        _escaped = None


def _editor(event) -> None:
    """Edit the buffer in `$EDITOR`."""
    event.current_buffer.open_in_editor()


def _scroll(amount: int):
    """A binding that scrolls the surface, or does nothing when none is rendering."""
    def move(event) -> None:
        if _surface is not None:
            _surface.scroll(amount)
    return move


def _scroll_or_edit(amount: int, fallback: str):
    """Scroll when the input line is empty (the wheel arrives as arrows), otherwise edit or browse history as usual."""
    def move(event) -> None:
        if event.current_buffer.text or _surface is None:
            getattr(event.current_buffer, fallback)()
            return
        _surface.scroll(amount)
    return move


def _expand(event) -> None:
    """Ctrl-O: expand or collapse tool results."""
    if _surface is not None:
        _surface.toggle()


def _record(event) -> None:
    """Ctrl-T: switch between the conversation and the session record."""
    if _surface is not None:
        _surface.transcript()


class _Toggled(Exception):
    """Raised out of the input line by Alt-O, so `_turns` re-enters the read at the caption's new height."""


def _agents(event) -> None:
    """Alt-O: hand the typed line back and leave the box, which cannot grow in place.

    rat-tail: the caret comes back at the line's end; carrying its position too is the upgrade.
    """
    if _surface is not None:
        _surface.agents()
        _surface.put_partial(event.current_buffer.text)
        event.app.exit(exception=_Toggled())


def _compose(event) -> None:
    """Alt-Enter inserts a newline; Enter still submits."""
    event.current_buffer.insert_text("\n")


def _bindings(keys: dict[str, str]) -> KeyBindings:
    """The prompt's key bindings for one keymap. Enter, Ctrl-C, Ctrl-D and ESC are fixed."""
    bindings = KeyBindings()
    bindings.add("enter")(_submit)
    bindings.add("c-c")(_cancel)
    bindings.add("c-d")(_end)
    bindings.add("escape")(_escape)
    for action, handler in (("editor", _editor), ("compose", _compose),
                            ("expand", _expand), ("transcript", _record),
                            ("agents", _agents)):
        # A key may be several presses, like `c-x c-e`.
        bindings.add(*keys[action].split())(handler)
    for action, amount in (("page_up", _PAGE), ("page_down", -_PAGE),
                           ("top", _END), ("bottom", -_END)):
        bindings.add(*keys[action].split())(_scroll(amount))
    for action, amount, fallback in (("scroll_up", _LINE, "auto_up"),
                                     ("scroll_down", -_LINE, "auto_down")):
        # Only Up/Down double as editing keys; any other chosen key just scrolls.
        key = keys[action]
        bindings.add(*key.split())(_scroll_or_edit(amount, fallback)
                                   if key in ("up", "down") else _scroll(amount))
    return bindings


# The default keymap's bindings, built once.
_BINDINGS = _bindings(defaults())


class _Rule(Margin):
    """One side of the input box, as a margin so it covers every wrapped row. `first` is beside the first row (with the `>`), `rest` beside continuations."""

    def __init__(self, first: str, rest: str, width: int) -> None:
        self._first, self._rest, self._width = first, rest, width

    def get_width(self, get_ui_content) -> int:
        return self._width

    def create_margin(self, window_render_info, width: int, height: int):
        """`height` rows of rule."""
        out = []
        for row in range(height):
            out += to_formatted_text(ANSI(self._first if row == 0 else self._rest))
            out.append(("", "\n"))
        return out


class _Line:
    """The terminal input line; the only holder of prompt_toolkit types.

    An `Application` (not `PromptSession`) so the box stays closed while typing, with `full_screen=False` inside the rows `Surface` reserves. Output goes to stderr, keeping redraws out of redirected stdout; `input`/`output` let tests drive it.
    """

    def __init__(self, root: Path, *, input=None, output=None,
                 keys: dict[str, str] | None = None) -> None:
        self._input = input
        self._output = output or create_output(stdout=sys.stderr)
        self._bindings = _BINDINGS if keys is None else _bindings(keys)
        # Kept so `read` can drop its cached project walk each time.
        self._completer = _Commands(root)
        # Outlives each read, so history carries across turns.
        self._buffer = Buffer(completer=self._completer, complete_while_typing=True,
                              history=InMemoryHistory(), multiline=True)

    def _layout(self, frame: dict) -> Layout:
        """The input box: top rule, buffer with side-rule margins, bottom rule, caption, and a floating completion menu that does not resize the box."""
        body = HSplit([
            # Flexible filler down to the box, sized by prompt_toolkit's own cursor query.
            Window(),
            Window(height=1, content=FormattedTextControl(ANSI(frame["top"]))),
            Window(content=BufferControl(buffer=self._buffer), wrap_lines=True,
                   style=frame["user_pt"],
                   left_margins=[_Rule(frame["marker"], frame["under"], frame["margin"])],
                   right_margins=[_Rule(frame["edge"], frame["edge"], 2)]),
            Window(height=1, content=FormattedTextControl(ANSI(frame["bottom"]))),
            Window(height=1, content=FormattedTextControl(ANSI(frame["caption"]))),
            # One window per expanded caption row, matching the rows `Surface.close` reserved for them.
            *(Window(height=1, content=FormattedTextControl(ANSI(row))) for row in frame["more"]),
        ])
        return Layout(FloatContainer(body, floats=[
            # Arrows show that the list scrolls past `MENU_HEIGHT`.
            Float(xcursor=True, ycursor=True,
                  content=CompletionsMenu(max_height=MENU_HEIGHT, display_arrows=True))
        ]), focused_element=body)

    def read(self, frame: dict, opening: str = "") -> str:
        """Read one line, starting from `opening` (text typed mid-turn without Enter).

        Stdout is redirected to stderr because prompt_toolkit's crash handler uses the builtin `print`. Each read starts with no ESC armed.
        """
        global _escaped
        _escaped = None
        self._completer.refresh()
        # A Document, so the cursor lands after `opening`.
        self._buffer.reset(Document(opening, len(opening)))
        app = Application(
            layout=self._layout(frame),
            key_bindings=self._bindings,
            input=self._input,
            output=self._output,
            full_screen=False,
            # `Surface.echo` records the submitted line instead.
            erase_when_done=True,
        )
        app.key_processor.after_key_press += _unarm
        with contextlib.redirect_stdout(sys.stderr):
            # Tell the surface not to paint over this box, and always clear it after.
            if _surface is not None:
                _surface.app = app
            try:
                return app.run()
            finally:
                if _surface is not None:
                    _surface.app = None


# rat-tail: duplicates `ask_user.OTHER`; importing it would register that plugin. A test pins the two together.
OTHER = "Other (answer in your own words)"


def _wrap(text: str, width: int, first: str = "", rest: str = "") -> list[str]:
    """Wrap prose to `width` with `first`/`rest` indents, keeping existing newlines; unwrapped when too narrow for the indent."""
    lines = text.splitlines() or [""]
    if width <= len(first) or width <= len(rest):
        return [first + lines[0], *(rest + line for line in lines[1:])]
    rows: list[str] = []
    for index, line in enumerate(lines):
        rows.extend(textwrap.wrap(line, width, initial_indent=first if index == 0 else rest,
                                  subsequent_indent=rest) or [""])
    return rows


class _Menu:
    """The AskUser modal: a question, its options, and the focused option's preview in a side pane (below it on narrow terminals). Drawn inline in the rows `Surface` reserves."""

    # Narrower terminals put the preview under the focused option.
    NARROW = 80
    # The pane's share of the width.
    PANE = 0.5
    # Blank columns between the options and the pane.
    GUTTER = 2

    def __init__(self, question: str, details: str, options: tuple[dict, ...],
                 multi: bool = False, *, style: str = "", glyphs: dict | None = None,
                 input=None, output=None) -> None:
        # From `Surface.ask_pt`; "" uses the terminal's colours.
        self._style = style
        # From `Surface.glyphs`, so the modal matches the skinned input box.
        self._glyphs = glyphs or GLYPHS
        self._question = question
        self._details = details
        self._options = options
        self._multi = multi
        self._input = input
        self._output = output or create_output(stdout=sys.stderr)
        # Index into the options plus one trailing OTHER row.
        self._focus = 0
        # Ticked indices; the answer is returned in option order.
        self._marked: set[int] = set()
        # The OTHER row's editor; Enter commits here rather than inserting.
        self._answer = Buffer(multiline=False)
        # Set by `_layout`.
        self._wide = True
        self._pane_width = 0
        self._rows_width = 0
        # The mounted surface's keymap, so a moved scroll key moves here too.
        self._keymap = _surface._keys if _surface is not None else defaults()

    @property
    def _other(self) -> int:
        """The focus index of the OTHER row: one past the last option, always last."""
        return len(self._options)

    def _mark(self, index: int) -> str:
        """The cursor and, in multi-select, the tick box for one row."""
        cursor = "❯" if index == self._focus else " "
        if not self._multi or index == self._other:
            return f"{cursor} "
        return f"{cursor} [{'x' if index in self._marked else ' '}] "

    def _rows(self) -> list[str]:
        """The option rows, wrapped (never clipped), each with its description; on a narrow terminal the focused option's preview follows it."""
        rows: list[str] = []
        for index, option in enumerate(self._options):
            mark = self._mark(index)
            rows.extend(_wrap(option["label"], self._rows_width, mark, " " * len(mark)))
            if option["description"]:
                rows.extend(_wrap(option["description"], self._rows_width, "    ", "    "))
            if not self._wide and index == self._focus:
                rows.extend(f"    {line}" for line in self._pane(self._pane_width, 0))
        return rows

    def _pane(self, width: int, height: int) -> list[str]:
        """The focused option's preview, clipped and never reflowed (reflowing would silently alter code). Height 0 means unlimited."""
        if self._focus >= self._other:
            return []
        lines = self._options[self._focus]["preview"].splitlines()
        if height:
            lines = lines[:height]
        return [line[:width] for line in lines]

    def _text(self) -> str:
        return "\n".join(self._rows())

    def _pane_text(self) -> str:
        return "\n".join(self._pane(self._pane_width, 0))

    def _caption(self) -> str:
        up, down = (_spell(self._keymap[action]) for action in ("menu_scroll_up", "menu_scroll_down"))
        keys = ["↑↓ move", "↵ select", "esc cancel", f"{up}/{down} scroll"]
        if self._multi:
            keys.insert(1, "space tick")
        return "  ".join(keys)

    def _boxed(self, body, width: int):
        """`body` boxed with this module's glyphs (not `widgets.Frame`), `width` columns wide, the whole box in the `ask` style.

        Horizontal rules are `_fill` strings so multi-character glyphs tile; verticals are one fill window per glyph character, since the height is unknown here.
        """
        glyphs = self._glyphs

        def rule(left: str, right: str):
            fill = _fill(glyphs["horizontal"], width - len(left) - len(right))
            return Window(height=1, content=FormattedTextControl(f"{left}{fill}{right}"))

        def side():
            return VSplit([Window(width=1, char=char) for char in glyphs["vertical"]])

        return HSplit([
            rule(glyphs["top_left"], glyphs["top_right"]),
            VSplit([side(), body, side()]),
            rule(glyphs["bottom_left"], glyphs["bottom_right"]),
        ], style=self._style)

    def _layout(self, size: Size) -> Layout:
        """The modal's layout for this terminal size: options beside the pane, or one column under `NARROW`. Contents are callables, so focus moves repaint without a rebuild.

        rat-tail: decided once, so a mid-question resize does not reflow.
        """
        self._wide = size.columns >= self.NARROW
        inner = max(size.columns - 2 * len(self._glyphs["vertical"]), 1)
        self._pane_width = int(inner * self.PANE) if self._wide else max(inner - 4, 1)
        self._rows_width = (max(inner - self._pane_width - self.GUTTER, 1) if self._wide
                            else inner)

        # Plain strings, never ANSI: previews are arbitrary content. Column widths are exact and sum to `inner`.
        listing = Window(content=FormattedTextControl(self._text), dont_extend_height=True,
                         width=self._rows_width + self.GUTTER if self._wide else None)
        # The OTHER row spans the full width, its marker beside the editor.
        hatch = VSplit([
            # Two-column marker plus ": " after the label.
            Window(width=len(OTHER) + 4, height=1,
                   content=FormattedTextControl(lambda: f"{self._mark(self._other)}{OTHER}: ")),
            Window(height=1, content=BufferControl(buffer=self._answer)),
        ])
        pane = Window(content=FormattedTextControl(self._pane_text),
                      width=self._pane_width)

        # The question and details wrap across the full width with as many rows as needed.
        lines = _wrap(self._question, inner)
        if self._details:
            lines += _wrap(self._details, inner)
        head = [Window(height=len(lines), dont_extend_height=True,
                       content=FormattedTextControl("\n".join(lines)))]
        body = HSplit([
            *head,
            VSplit([listing, pane]) if self._wide else listing,
            hatch,
            Window(height=1, content=FormattedTextControl(self._caption)),
        ])
        # The editor keeps focus; menu keys are eager bindings, so focus never decides them.
        return Layout(self._boxed(body, size.columns), focused_element=hatch)

    def _keys(self) -> KeyBindings:
        """up/down move focus, space toggles when multi, enter commits, escape dismisses."""
        keys = KeyBindings()

        @keys.add("up", eager=True)
        def _up(event) -> None:
            # Clamped: a negative index would wrap to the OTHER row.
            self._focus = max(self._focus - 1, 0)

        @keys.add("down", eager=True)
        def _down(event) -> None:
            self._focus = min(self._focus + 1, self._other)

        @keys.add("space", eager=True)
        def _tick(event) -> None:
            if self._multi and self._focus < self._other:
                self._marked.symmetric_difference_update({self._focus})
            else:
                self._answer.insert_text(" ")

        @keys.add("enter", eager=True)
        def _commit(event) -> None:
            event.app.exit(result=self._chosen())

        # Escape is not eager, or it would swallow the first key of the Alt-Enter pair below.
        @keys.add("escape")
        @keys.add("c-c", eager=True)
        def _dismiss(event) -> None:
            event.app.exit(result=None)

        @keys.add("escape", "enter")
        def _commit_composed(event) -> None:
            # Alt-Enter and Shift-Enter commit rather than dismiss.
            event.app.exit(result=self._chosen())

        # Scroll the conversation behind the menu. Added after the arrows, whose names `c-up` and `c-down` extend.
        for action, amount in (("menu_scroll_up", _LINE), ("menu_scroll_down", -_LINE),
                               ("page_up", _PAGE), ("page_down", -_PAGE)):
            keys.add(*self._keymap[action].split())(_scroll(amount))

        return keys

    def _height(self, layout: Layout, size: Size) -> int:
        """The tallest the menu gets over every focus, since the focused option's preview sets its height."""
        focus = self._focus
        try:
            tallest = 0
            for index in range(self._other + 1):
                self._focus = index
                tallest = max(tallest, layout.container.preferred_height(
                    size.columns, size.rows).preferred)
            return tallest
        finally:
            self._focus = focus

    def _chosen(self) -> list[str] | None:
        """The committed values in option order, or None for any empty answer (as `ask:cli` treats it)."""
        if self._focus >= self._other:
            typed = self._answer.text.strip()
            return [typed] if typed else None
        if self._multi:
            return [self._options[i]["value"] for i in sorted(self._marked)] or None
        return [self._options[self._focus]["value"]]

    def read(self) -> list[str] | None:
        """Run the menu and return the values chosen, or None when dismissed."""
        size = self._output.get_size()
        layout = self._layout(size)
        app = Application(
            layout=layout,
            key_bindings=self._keys(),
            input=self._input,
            output=self._output,
            full_screen=False,
            erase_when_done=True,
        )
        # As in `_Line.read`.
        with contextlib.redirect_stdout(sys.stderr):
            # Room for the whole menu, so the conversation can scroll above it without painting over it.
            if _surface is not None:
                _surface.hold(self._height(layout, size), app)
            try:
                return app.run()
            finally:
                if _surface is not None:
                    _surface.app = None


def loop(session: Session, args: argparse.Namespace,
         keys: dict[str, str] | None = None) -> int:
    """Hold one session open across many turns; everything but answers goes to stderr."""
    # The same stream `approval:cli` reads, so piped prompts and answers share it.
    stream = session.stream or sys.stdin
    # rat-tail: time since launch or the last in-place switch, not the conversation's age; a recorded start time is the upgrade.
    started = time.monotonic()
    roles, finding = use("theme", "load")(session.root, args.theme)
    if finding:
        print(f"theme: {finding}", file=sys.stderr)
    # No renderer unless a stream is a terminal, so redirected stdout never gets escapes (A9).
    keys = keys or defaults()
    surface = (Surface(roles, markdown=sys.stdout.isatty(), headless=session.headless,
                       keys=keys)
               if sys.stdout.isatty() or sys.stderr.isatty() else None)
    for note in surface.findings if surface else ():
        print(f"theme: {note}", file=sys.stderr)
    # For `approval:repl`, which cannot be handed it; reset even to None.
    global _surface
    _surface = surface
    if surface is not None:
        surface.session = session
    # Replace only the default "cli" approver, which cannot work under a live footer.
    if surface is not None and session.approval == "cli":
        session.approval = "repl"
    render = surface.emit if surface else None
    # An input line only when nobody supplied a stream and someone is there (D13).
    reader = (_Line(session.root, keys=keys)
              if session.stream is None and not session.headless else None)
    if surface:
        surface.start()
        surface.banner(session)
        # Attached now rather than at the first turn, so a report before it reaches the surface.
        session.emit = render
    else:
        print(f"un - session {session.id}. /quit to exit.",
              file=sys.stderr)
    for name, text in core.FALLOUT.items():
        line = f"{name}: {text}"
        if surface:
            surface.emit("error", line)
        else:
            print(line, file=sys.stderr)
    try:
        return _turns(session, args, surface, reader, stream, render, started)
    finally:
        # Restore echo and the screen on every exit.
        if surface:
            surface.close()
            surface.stop()


def _turn(session, args, surface, render, prompt, started) -> list[str]:
    """Run one turn and return lines queued during it. An interrupt ends the turn, not the loop."""
    # The catch also covers `wait` and `settle`, where a key press can arrive.
    try:
        if surface:
            surface.open(session, time.monotonic() - started)
            surface.wait(session)
        try:
            # The session's value, so `/reload` changes apply.
            run_terminal(session, prompt,
                         max_turns=session.max_turns, stats=args.stats, render=render)
        finally:
            if surface:
                surface.settle()
    except KeyboardInterrupt:
        if surface:
            surface.interrupted()
        else:
            print(INTERRUPTED, file=sys.stderr)
    return surface.take_queued() if surface else []


LEAVE_QUESTION = "A learning pass is still running: {names}."
LEAVE_OPTIONS = (
    {"label": "Wait", "value": "wait", "description": "exit once it finishes", "preview": ""},
    {"label": "Abandon", "value": "abandon",
     "description": "stop it after its current step; nothing it was doing is committed",
     "preview": ""},
)


def _leave(session, ask_first: bool) -> None:
    """Settle this session's learning passes while the surface is still up, asking wait or abandon first when `ask_first`. A dismissed question waits."""
    names = curation.live(session)
    if not names:
        return
    if ask_first and _surface is not None:
        picked = ask(session, LEAVE_QUESTION.format(names=", ".join(names)), "", LEAVE_OPTIONS)
        if picked == ["abandon"]:
            curation.stop(session)
    curation.settle(session)


def _turns(session, args, surface, reader, stream, render, started) -> int:
    """The prompt loop; separate so `loop` can restore the terminal in one `finally`."""
    # Lines queued mid-turn run first, in order.
    pending: list[str] = []
    # False once Alt-O has left the input box, so it re-enters with the figures already read.
    fresh = True
    while True:
        elapsed = time.monotonic() - started
        try:
            if pending:
                line = pending.pop(0)
                if surface:
                    surface.close()
                    surface.echo(line.strip())
            elif reader:
                frame = surface.frame(session, elapsed, fresh) if surface else _BARE
                fresh = True
                if surface:
                    # The input line draws its own box in the footer's rows, reserved after the frame so they count the caption rows it draws.
                    surface.close(len(frame["more"]))
                line = reader.read(frame, opening=surface.take_partial() if surface else "")
                if surface and line.strip():
                    surface.echo(line.strip())
            else:
                if surface:
                    surface.prompt(session, elapsed)
                else:
                    print("> ", end="", flush=True, file=sys.stderr)
                line = stream.readline()
                if not line:  # end of input: a pipe has no /quit at the end of it
                    _leave(session, ask_first=False)
                    return EXIT_OK
        except EOFError:
            # Ctrl-D in the input line.
            _leave(session, ask_first=reader is not None)
            return EXIT_OK
        except _Toggled:
            # Alt-O: no echo, no dispatch; the typed text is already handed back.
            fresh = False
            continue
        except KeyboardInterrupt:
            if surface:
                surface.note("")
            else:
                print(file=sys.stderr)
            continue
        prompt = line.strip()
        if not prompt:
            continue
        # An interrupted turn leaves `cancelled` set, and a fork launched from this line shares it without clearing it.
        session.cancelled.clear()
        held = session.id
        try:
            # A footer for the command's run, so a slash-launched workflow shows its figures moving.
            try:
                if surface and prompt.startswith("/"):
                    surface.open(session, time.monotonic() - started)
                    surface.wait(session)
                handled = slash(session, prompt)
            finally:
                if surface:
                    surface.settle()
                    pending += surface.take_queued()
        except KeyboardInterrupt:
            if surface:
                surface.interrupted()
            else:
                print(INTERRUPTED, file=sys.stderr)
            continue
        except Quit:
            _leave(session, ask_first=reader is not None)
            return EXIT_OK
        except RunPrompt as ask:
            # The command's prompt replaces the typed line.
            pending += _turn(session, args, surface, render, ask.prompt, started)
            continue
        except NoSuchCommand as exc:
            if surface:
                surface.note(str(exc))
            else:
                print(exc, file=sys.stderr)
            continue
        if session.id != held:
            # /new and /resume switch in place; the clock follows the session.
            started = time.monotonic()
        if handled is not None:
            if surface:
                surface.note(handled)
            else:
                print(handled, file=sys.stderr)
            continue
        pending += _turn(session, args, surface, render, prompt, started)


# The rendering surface, for services registered at import to reach; None on a piped run.
_surface: "Surface | None" = None

# The `Application` whose input box has one ESC armed against it; None when none is.
_escaped: Application | None = None

# Appended to lines typed during a tool batch: an interjection, not an interrupt.
INTERJECT = "Act on this now. If it replaces what you were doing, say so and switch."


@hook("Turn")
@hook("TurnEnd")
def replied(*, session: Session, **_) -> None:
    """Mark the footer's figures stale. `Turn` fires before `transcript` writes the usage row, so `TurnEnd`, which follows the record, marks again."""
    if _surface is not None:
        _surface.mark_stale()


@hook("ToolResults")
def interject(*, session: Session, calls: list[dict]) -> str | None:
    """Deliver lines the operator typed during the batch as operator text before the model's next turn.

    Nothing for subagents, runs with no surface, or an empty queue. Lines typed after the last batch run as the next prompt instead.
    """
    if session.agent or _surface is None:
        return None
    # Drained, or later batches would repeat it.
    lines = _surface.take_queued()
    if not lines:
        return None
    for line in lines:
        _surface.echo(line.strip())
    # The operator is present, so reset the unattended-turn bound.
    session.attended()
    return "\n".join([*(f"[operator, mid-turn]: {line.strip()}" for line in lines),
                      "", INTERJECT])


@service("approval:repl")
def approve(session: Session, question: str, *, always: bool = False) -> str:
    """`approval:cli` run inside `Surface.reading`, so the question is not painted over by the footer."""
    if _surface is None:
        # A wiring mistake, not a refusal.
        raise RuntimeError("approval:repl reached with no REPL surface")
    with _surface.reading(session):
        return use("approval", "cli")(session, question, always=always)


@service("ask:repl")
def ask(session: Session, question: str, details: str, options: tuple[dict, ...],
        *, multi: bool = False) -> list[str] | None:
    """Put a choice to the operator in a `_Menu`, inside `Surface.reading`.

    Delegates to `ask:cli` when a stream was supplied or the run is headless, so nobody-there becomes a refusal rather than a blocked Application.
    """
    if _surface is None:
        raise RuntimeError("ask:repl reached with no REPL surface")
    # Both branches inside `reading`, which restores the terminal even on a raise.
    with _surface.reading(session):
        if session.stream is not None or session.headless:
            return use("ask", "cli")(session, question, details, options, multi=multi)
        return _Menu(question, details, options, multi,
                     style=_surface.ask_pt, glyphs=_surface.glyphs).read()


@service("command:repl")
def repl(args: argparse.Namespace) -> int:
    """Open the interactive prompt loop."""
    try:
        keys = keymap(core.project_root() or Path.cwd())
    except ValueError as exc:
        # Before `new_session`, so a bad keymap leaves no session behind.
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    session = new_session(args)
    # Outside `loop`, so SessionEnd hooks run after the terminal is restored.
    return end_session(session, lambda: loop(session, args, keys))
