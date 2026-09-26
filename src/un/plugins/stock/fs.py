"""File tools, and the filesystem seam they act through.

The tools are what the model sees; `fs:<name>` is what actually touches disk. They are
separated so a sandboxed or remote backend can be dropped in by registering another
`fs:` service and naming it on the session - no tool is edited, no schema changes, and
the model cannot tell the difference.

Writes: `Write` and `Edit` write. Everything else is read-only.

A write is gated on a READ. `Read` records each file it shows against the sha256 of that
file's whole content, on the session; `Write` over an existing file and `Edit` refuse
unless that record is present and still matches disk, and both refresh it afterwards. A
path that does not exist yet is exempt - creating a file cannot require reading it first.
The record lives on `Session`, not here, because it is a property of the conversation
rather than of the filesystem: a swapped backend must not lose it. What a backend does
contribute is the SPELLING, through `key`, so one file is one entry however it was named.


`Grep` and `Glob` produce MANY paths from one call, and the permission table returns one
verdict for the path a call NAMES. A search rooted at `.` is correctly allowed, because
`.` is not a credential, and everything beneath it comes back unjudged. So both ask the
table per RESULT, through `permissions:denied_path`, and announce what they withheld.
What a credential is stays stated once, in the table.
"""

from __future__ import annotations
import base64
import io
import fnmatch
import hashlib
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from un.core import locked
from un import Session, service, tool, use
from un.core import DEFAULT_TIMEOUT, PRUNE, spawn_child

_TEXT = {"type": "string"}

MODES = ("content", "files", "count")

# rat-tail: the window is sliced AFTER the whole file is read, because
# `LocalFileSystem.read` returns it whole. That spends the disk read to save the context
# window, which is the cost this bound is about - one unbounded `Read` of a 60KB module
# is most of what the model has to think with. A backend where the TRANSFER is the
# expensive part - remote, sandboxed - is the upgrade path, and `offset` and `limit` move
# onto the backend method then.
READ_LIMIT = 2000
LINE_WIDTH = 2000
# rat-tail: the same order as `READ_LIMIT` and for the same reason - a bound on what one call may spend of the context window. 100 answers an ordinary question in one call and stops `**/*` on a monorepo from spending the window. `head_limit` is the upgrade path for a caller that genuinely needs more.
GLOB_LIMIT = 100
# The four the Messages API accepts, and the only four `Read` will send.
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")


def _media_type(data: bytes) -> str | None:
    """Which of the four accepted types these BYTES are, or None for anything else.

    Never the extension: the API rejects a media_type that disagrees with the payload,
    and a name is a claim where the signature is evidence. Slicing rather than indexing
    throughout, so a file shorter than a signature refuses rather than raising.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    # WebP carries the file length in the four bytes between, so this is not one prefix.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


# The API's two limits. 5MB is its cap on an image measured AFTER base64, which inflates
# by 4/3, so the cap on the bytes is three quarters of it. 8000 is the per-side pixel cap.
MAX_IMAGE_BYTES = 5 * 1024 * 1024 * 3 // 4
MAX_IMAGE_EDGE = 8000
MIN_IMAGE_EDGE = 256

PDF_SIGNATURE = b"%PDF-"
# What one call may spend of the context window, the same kind of bound as `READ_LIMIT`: a longer PDF must name its pages.
PDF_READ_PAGES = 10
PDF_PAGE_LIMIT = 20
# The API's per-request cap is 32MB measured AFTER base64, which inflates by 4/3, so the cap on the bytes is three quarters of it.
MAX_PDF_BYTES = 32 * 1024 * 1024 * 3 // 4
# `[0-9]`, not `\d`: `\d` admits other scripts' digits, which `int` would then accept silently.
_PAGES = re.compile(r"([0-9]+)(?:-([0-9]+))?")


def _fitted(path: str, data: bytes, media: str) -> bytes:
    """`data` brought under both API limits by downscaling, or a refusal.

    Pillow is imported here rather than at module scope: `fs` loads on every run and
    most runs read no image at all, so the cost falls on the call that needs it. The
    same reason `anthropic_provider` constructs its client on first use.
    """
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(data))
    except OSError as exc:
        # Identification is by signature and says nothing about whether the bytes
        # decode. A truncated download keeps its header, so this is the ordinary case
        # rather than a corrupt-input edge - and it must arrive as a sentence naming
        # the file, not as a Pillow exception type through the tool boundary.
        raise ValueError(f"{path} has a {media} signature but its content will not "
                        "decode as an image") from exc
    if max(image.size) <= MAX_IMAGE_EDGE and len(data) <= MAX_IMAGE_BYTES:
        return data
    # rat-tail: halve the long edge until both bounds hold, re-encoding in the ORIGINAL
    # format - re-encoding a photograph as PNG comes out LARGER than it went in, so a
    # single target format would push the bound the wrong way. Searching encoder quality
    # rather than dimensions is the upgrade path, and it matters only if detail loss on
    # dense screenshots turns out to bite.
    #
    # rat-tail: an animated GIF leaves as its first frame, because `thumbnail` flattens
    # it. Rare enough to accept; resizing frame by frame is the fix.
    edge = min(max(image.size), MAX_IMAGE_EDGE)
    while edge >= MIN_IMAGE_EDGE:
        shrunk = image.copy()
        shrunk.thumbnail((edge, edge))
        buffer = io.BytesIO()
        # `image.format`, not the copy's: `copy()` does not carry it.
        shrunk.save(buffer, format=image.format)
        if buffer.tell() <= MAX_IMAGE_BYTES:
            return buffer.getvalue()
        edge //= 2
    raise ValueError(f"{path} is {len(data)} bytes and will not fit under "
                     f"{MAX_IMAGE_BYTES} even downscaled to {MIN_IMAGE_EDGE}px; "
                     "resize it or read a crop")


def _window(pages) -> tuple[int, int] | None:
    """`pages` as an inclusive (first, last), or None when absent. Syntax only; bounds need the page count."""
    if pages is None:
        return None
    # Not only a str check: nothing validates arguments against the schema, so an int or a list arrives here as sent.
    match = _PAGES.fullmatch(pages) if isinstance(pages, str) else None
    if match is None:
        raise ValueError(f'pages is one page such as "3" or an inclusive range such as "3-7", not {pages!r}')
    first = int(match[1])
    return first, int(match[2] or first)


def _pdf(path: str, data: bytes, window: tuple[int, int] | None) -> tuple[bytes, int, int, int]:
    """The pages to send as a new PDF, with the first and last page sent and the document's page count; or a refusal.

    pypdf is imported here for `_fitted`'s reason. The window is written out even when it is the whole document, with decimal page labels starting at the original page number, so the payload carries its own numbering.

    rat-tail: rewriting through `PdfWriter` drops document-level structure (outlines, the author's page labels, form scripts) and keeps page content, fonts and images. Passing the original bytes through untouched is the upgrade path, if numbering can come from somewhere else.
    """
    from pypdf import PdfReader, PdfWriter
    from pypdf.errors import PyPdfError

    broken = f"{path} has a PDF signature but will not parse"
    # Deliberately broad, and scoped to opening and counting only: lenient parsing leaks builtin exceptions, and no library type may cross the tool boundary. Chained, so nothing is swallowed.
    try:
        reader = PdfReader(io.BytesIO(data))
        encrypted = reader.is_encrypted
        # Not counted when encrypted: pypdf raises on the pages of an undecrypted file, which would turn this refusal into the corrupt one.
        total = 0 if encrypted else len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(broken) from exc
    if encrypted:
        # rat-tail: an owner-password-only PDF opens with an empty password, but decrypting AES needs pypdf's `cryptography` extra, a second dependency. Refusing every encrypted file is the ceiling; `reader.decrypt("")` with the extra is the upgrade path.
        raise ValueError(f"{path} is encrypted (password-protected), so Read cannot open it")
    if total == 0:
        raise ValueError(broken)
    if window is None:
        if total > PDF_READ_PAGES:
            raise ValueError(f'{path} has {total} pages, more than the {PDF_READ_PAGES} Read sends without `pages`; pass pages such as "1-{min(total, PDF_PAGE_LIMIT)}"')
        window = 1, total
    first, last = window
    if first < 1:
        raise ValueError(f"pages are numbered from 1, not {first}")
    if last < first:
        raise ValueError(f"pages {first}-{last} is reversed; the first page comes first")
    if last > total:
        raise ValueError(f"{path} has {total} pages; pages {first}-{last} runs past the end")
    if last - first + 1 > PDF_PAGE_LIMIT:
        raise ValueError(f"pages {first}-{last} is {last - first + 1} pages; one Read sends at most {PDF_PAGE_LIMIT}")
    writer = PdfWriter()
    buffer = io.BytesIO()
    try:
        for page in reader.pages[first - 1:last]:
            writer.add_page(page)
        writer.set_page_label(0, last - first, style="/D", start=first)
        writer.write(buffer)
    except PyPdfError as exc:
        # Page objects parse lazily, so a file that opened can still fail here. Only pypdf's own type is caught: a builtin from this block is a bug and surfaces as one.
        raise ValueError(f"{broken} at pages {first}-{last}") from exc
    sent = buffer.getvalue()
    # After windowing, and read from the module at call time so a test can monkeypatch the cap.
    if len(sent) > MAX_PDF_BYTES:
        raise ValueError(f"{path} pages {first}-{last} are {len(sent)} bytes, over the {MAX_PDF_BYTES}-byte cap; read fewer pages")
    return sent, first, last, total


def _digest(text: str) -> str:
    """A file's identity in the read ledger, for the moment it was read or written.

    A DIGEST rather than an mtime: it needs nothing added to the `fs:` contract for a
    backend to `stat` through, it cannot be fooled by a clock, and it catches a rewrite
    inside one mtime tick that a timestamp would call unchanged.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _number(lines: list[str], offset: int) -> list[str]:
    """`cat -n`: the number, a tab, the line - so splitting once on the tab recovers it.

    The width bound is per LINE, not per window: one generated file with a single
    enormous line would otherwise spend the whole budget, and its neighbours carry
    ordinary code the caller still wants to see.
    """
    numbered = []
    for number, line in enumerate(lines, offset):
        if len(line) > LINE_WIDTH:
            line = f"{line[:LINE_WIDTH]}[truncated: line is {len(line)} chars]"
        numbered.append(f"{number:6d}\t{line}")
    return numbered


def bounded(hits: list[str], head_limit: int | None, notice: list[str]) -> list[str]:
    """`hits` capped at `head_limit`, announced when it bit, with `notice` after it.

    `Glob` and `Grep` both bound a result the model would otherwise read in full, and the
    truncation line is part of the contract each one has with the model - so it is
    spelled here once rather than in each of them, where the two copies would drift into
    two different announcements of the same thing.

    Announced, not silent, for the reason `withheld` is: a caller who cannot see the gap
    reasons past it. Only when something was actually cut, because a notice printed
    unconditionally is noise the model learns to skip.

    `is not None`, so `head_limit=0` is a limit of zero rather than "unset". The total is
    counted over `hits`, which both callers have already filtered - a refused or
    out-of-root path was never a result that could have been shown, and counting it here
    would report a number that was never available.
    """
    if head_limit is not None and len(hits) > head_limit:
        return (hits[:head_limit]
                + [f"[truncated: {head_limit} of {len(hits)} shown]"] + notice)
    return hits + notice


def withheld(refused: dict[str, int]) -> list[str]:
    """The one announcement every multi-result reader makes, or nothing to say.

    Announced rather than silently dropped, for the reason `head_limit` announces a
    truncation: a caller who cannot see the gap reasons past it.

    The RULES are named, deduplicated and sorted, because `**/*credentials*` catches
    ordinary source files and an operator needs to know which rule to look at. Sorted so
    the line does not depend on which file the walk reached first. The PATHS are not
    named: that would tell the model exactly where the credentials are, which is the
    leak being closed.

    `refused` counts PATHS per rule, so the count and the rule list are counted over
    different things - two keys refused by one rule is `2 paths` and one rule.
    """
    if not refused:
        return []
    total = sum(refused.values())
    return [f"[withheld: {total} path{'' if total == 1 else 's'} refused by "
            f"{', '.join(sorted(refused))}]"]


@service("fs:local")
class LocalFileSystem:
    """The real filesystem. Relative paths anchor on the session directory; what
    keeps a path inside it is the permission table, not this class."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _resolve(self, path: str) -> Path:
        """Anchor a relative path on the session, never on the process working directory.

        A long-lived agent and the python process do not share a notion of "here";
        os.chdir by any tool would otherwise silently relocate every later path.

        ANCHORING, not confinement. An absolute path is resolved as given and this
        returns it. What keeps a named target inside the project is the permission
        table's `ask_outside_project` policy, `!<project>/**` across the six built-in
        tools, which is a floor ASSUMED_ASK with no toggle key, and the sandbox's
        `confine_outside_project`, which denies the same paths. Enforcing either here
        as well would put the same rule in two places, and the copy is what drifts.

        `glob` is the exception and confines itself, because it never comes through
        here. What it cannot borrow from the table is CONFINEMENT - the table judges
        the target a call names, and a pattern is not a path. The credential rules it
        does borrow, per result, through `permissions:denied_path`.
        """
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.session.cwd / candidate
        resolved = candidate.resolve()
        return resolved

    def key(self, path: str) -> str:
        """This path's identity in the session's read ledger.

        Canonical, so `notes.txt`, `./notes.txt` and the absolute spelling are one entry
        rather than three. Here rather than in the tool because `_resolve` already
        decides what a path IS, and a second copy of that decision is the copy that
        drifts.
        """
        return str(self._resolve(path))

    def read(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def read_bytes(self, path: str) -> bytes:
        """The sixth method on this seam. Every other one speaks `str`, and an image is
        the one thing `Read` returns that text cannot carry."""
        return self._resolve(path).read_bytes()

    def write(self, path: str, content: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # HELD for the write. A turn's tool calls run at once, so two `Write`s naming one
        # path would otherwise be two truncating writers on one file and the loser's content
        # is simply gone. The lock is on the target, so writes to different files are not
        # delayed by each other at all.
        with locked(target):
            target.write_text(content, encoding="utf-8")

    def glob(self, pattern: str, path: str = ".", *,
             head_limit: int | None = GLOB_LIMIT) -> list[str]:
        """Confined separately: this method never goes through `_resolve` for its hits.

        `root.glob("../**/*")` leaves the `..` unresolved, so `relative_to(root)`
        succeeds textually and the escape is returned. Resolving each hit and
        re-testing it is what actually keeps the walk inside the session - and it is
        also what stops a symlink inside the project from listing a file outside it,
        which confining the pattern alone would miss.

        **`path` moves the walk root, never the fence.** It is anchored by `_resolve`,
        the way `grep`'s `path` is, so a relative one joins the session and an absolute
        one is taken as given; what every hit is TESTED against stays `session.cwd`.
        Those are two different values for the first time here, and testing containment
        against the walk root instead would list the whole filesystem to a caller that
        asked for `path="/"`.

        **Most recently modified first.** The result goes into the model's context
        verbatim, and the file touched last is almost always the one the question is
        about; alphabetical order buries it. Ties break on the path, ascending, because
        `Path.glob` walks `os.scandir` order and a sort keyed on the timestamp alone
        would leave files sharing a timestamp in an order that is not reproducible.
        Stat'd after `_judge`, so a refused path is never stat'd and cannot influence
        the order of the paths that survive it.

        Filtering rather than raising, unlike `_resolve`: this is a listing, and a
        listing that refused outright because one match resolved outside the root
        would be unusable for an ordinary `**/*`.

        **Every match is judged, not just the pattern.** `evaluate` decides the target a
        call NAMES, and `**/*` is not a credential - so the call is correctly allowed and
        then lists `.env` and `keys/*.pem` as results no verdict ever saw. The deny table
        is asked per result, through `permissions:denied_path`, so what a credential is
        stays stated in one place.
        """
        root = self._resolve(path)
        cwd = self.session.cwd.resolve()
        refused: dict[str, int] = {}
        kept = []
        for hit in root.glob(pattern):
            resolved = hit.resolve()
            if not (hit.is_file() and resolved.is_relative_to(cwd)):
                continue
            spelled = str(resolved.relative_to(cwd))
            if self._judge("Glob", spelled, refused):
                kept.append((-resolved.stat().st_mtime, spelled))
        # Bounded LAST: the cap is taken over what survived confinement and the deny
        # table, so a path the caller may never see cannot spend a slot, and the total it
        # reports is the number that could have been shown.
        return bounded([spelled for _, spelled in sorted(kept)],
                       head_limit, withheld(refused))

    def grep(self, pattern: str, path: str = ".", *, mode: str = "content",
             glob: str | None = None, ignore_case: bool = False,
             head_limit: int | None = None) -> list[str]:
        """Search, through ripgrep when it is installed and a bounded walk when it is not.

        Two backends, one contract: the same arguments, the same output spelling, and
        the same `ValueError` for a pattern neither can compile. A caller that had to
        know which one ran would have no contract at all.

        The withheld NOTICE is where they legitimately differ, and it follows from
        prevention rather than from carelessness. The walk judges a candidate file
        before opening it, so it counts every refused path in scope without knowing
        whether one would have matched. ripgrep only ever emits files that matched, so
        it can only refuse those, and it under-reports. Making the two agree would mean
        reading the credentials to find out - which is the read the walk exists to
        avoid. The notice does not claim results were lost; it says these locations were
        refused, which is true either way.
        """
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}, not {mode!r}")
        root = self._resolve(path)
        rg = shutil.which("rg")
        # Filled by whichever backend ran, and turned into the notice below. Both judge
        # every result: `evaluate` decides the target the call NAMES, and `.` is not a
        # credential, so a search rooted there is correctly allowed and then returns
        # everything beneath it that no verdict ever saw.
        refused: dict[str, int] = {}
        hits = (self._rg(rg, pattern, root, mode, glob, ignore_case, refused) if rg
                else self._walk(pattern, root, mode, glob, ignore_case, refused))
        return bounded(hits, head_limit, withheld(refused))

    def _judge(self, name: str, spelled: str, refused: dict[str, int]) -> bool:
        """May this path be returned to `name`'s caller? Tallies what refused it if not.

        Counts PATHS per rule, which is what lets the notice say `2 paths` and name one
        rule. By the CALLING tool's name rather than `Read`: the credential policies are
        generated across every built-in tool, so a `Grep` rule sits beside each `Read`
        one, and asking per tool is the grammar the rest of the table uses.
        """
        rule = use("permissions", "denied_path")(self.session, name, spelled)
        if rule:
            refused[rule] = refused.get(rule, 0) + 1
        return not rule

    def _spell(self, resolved: Path) -> str:
        """`resolved` as it should be NAMED in output: relative to the session when under it.

        ripgrep echoes back the path it was given, so handing it an absolute one repeats
        the same long prefix on every hit. The walk is spelled the same way, so a file
        found through `path="."` and through `path="src"` has one name rather than two.
        """
        cwd = self.session.cwd.resolve()
        return (str(resolved.relative_to(cwd)) if resolved.is_relative_to(cwd)
                else str(resolved))

    def _rg(self, rg: str, pattern: str, root: Path, mode: str, glob: str | None,
            ignore_case: bool, refused: dict[str, int]) -> list[str]:
        # `--no-require-git`: ripgrep applies `.gitignore` only inside a git repository
        # unless told otherwise, and un's project boundary is `.un/`, not `.git`. A
        # project that is not a repo still means what its `.gitignore` says.
        argv = [rg, "--color", "never", "--sort", "path", "--no-require-git"]
        argv += {"content": ["--line-number", "--no-heading"],
                 "files": ["--files-with-matches"],
                 "count": ["--count"]}[mode]
        if mode != "files":
            # A NUL between the path and the rest, so a path CONTAINING a colon is still
            # recovered exactly - splitting `path:line:text` on the first colon reads
            # `keys/ser:ver.pem` as `keys/ser`, which no rule refuses, and the guard
            # fails OPEN. Not in `files` mode: there rg emits one NUL-SEPARATED record
            # with no newlines at all, and the whole line is already the path.
            argv.append("--null")
        if ignore_case:
            argv.append("--ignore-case")
        if glob:
            argv += ["--glob", glob]
        # `--regexp` keeps a pattern starting with `-` from being read as a flag, and
        # `--` does the same for the path.
        argv += ["--regexp", pattern, "--", self._spell(root)]
        try:
            done = spawn_child(argv, cwd=self.session.cwd, timeout=DEFAULT_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ValueError(f"rg timed out after {DEFAULT_TIMEOUT}s") from None
        # rg exits 1 for "no matches", which is an ordinary empty result and not a
        # failure. Only 2 and above mean rg itself could not run.
        if done.returncode >= 2:
            raise ValueError(f"rg failed: {done.stderr.strip()}")
        # rg echoes the search path as given, so a search rooted at `.` comes back as
        # `./src/app.py` where the walk says `src/app.py`.
        kept = []
        for line in (line.removeprefix("./") for line in done.stdout.splitlines()):
            # rat-tail: FILTERED, not prevented. Preventing rg's read means passing
            # `--glob=!` exclusions, which needs the deny specs translated from fnmatch
            # into gitignore semantics - a second copy of the rules in another dialect,
            # where a translation that under-matches fails open. rg reads into its own
            # process and un discards it, so nothing reaches the model, the transcript
            # or SessionRead. The walk gets true prevention because un owns that loop.
            if self._judge("Grep", line.split("\0", 1)[0], refused):
                # A no-op in `files` mode, which carries no NUL.
                kept.append(line.replace("\0", ":", 1))
        return kept

    def _files(self, root: Path, glob: str | None,
               refused: dict[str, int]) -> list[Path]:
        """Every file under `root`, pruned. `os.walk` because `rglob` cannot prune.

        Descending into `.venv/` and discarding the results afterwards still costs the
        read. Editing `dirnames` in place is what stops the descent happening at all,
        and it is the whole reason this is not a one-line `rglob`.

        A refused path is dropped HERE rather than filtered out of the results, so
        `_walk` never reads it. Prevention where prevention is exact and free - and it
        has to happen before the decode, or a refused binary file is discarded by
        `read_text` first and never counted in the notice.
        """
        if root.is_file():
            return [root] if self._judge("Grep", self._spell(root), refused) else []
        found = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in PRUNE]
            for name in filenames:
                file = Path(dirpath) / name
                # rat-tail: fnmatch, where rg's --glob has gitignore semantics. Close
                # enough for the fallback; ripgrep is the upgrade path.
                if glob is None or fnmatch.fnmatch(str(file.relative_to(root)), glob):
                    if self._judge("Grep", self._spell(file), refused):
                        found.append(file)
        return sorted(found)

    def _walk(self, pattern: str, root: Path, mode: str, glob: str | None,
              ignore_case: bool, refused: dict[str, int]) -> list[str]:
        try:
            regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as exc:
            # `re.error` is not a `ValueError`, and the rg path raises one. Same
            # contract either way, or the caller catches two types depending on what
            # happens to be installed.
            raise ValueError(f"bad pattern {pattern!r}: {exc}") from exc
        hits: list[str] = []
        # No judging of its own: `_files` already dropped what the table refuses, and
        # judging in both places would count the same path into the notice twice.
        for file in self._files(root, glob, refused):
            try:
                text = file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary or unreadable: not an error, just not a text match
            matched = [(number, line)
                       for number, line in enumerate(text.splitlines(), 1)
                       if regex.search(line)]
            if not matched:
                continue
            name = self._spell(file)
            if mode == "files":
                hits.append(name)
            elif mode == "count":
                hits.append(f"{name}:{len(matched)}")
            else:
                hits += [f"{name}:{number}:{line}" for number, line in matched]
        return hits


def _fs(session: Session):
    return use("fs", session.fs)(session)


# Held by `Write` and `Edit` from the ledger check to the ledger update. The backend's lock covers only the write, so two edits of one file in one turn would both read the original and the second write would drop the first's change.
# rat-tail: in-process only, which covers a turn's parallel calls and subagent threads; another un process can still interleave a read-modify-write. A flock on a sidecar file is the upgrade path.
_MODIFYING: dict[str, threading.Lock] = {}
_MODIFYING_LOCK = threading.Lock()


def _modifying(key: str) -> threading.Lock:
    with _MODIFYING_LOCK:
        return _MODIFYING.setdefault(key, threading.Lock())


def _unchanged(session: Session, backend, path: str, verb: str) -> str | None:
    """The file's current text if `verb` may modify it, or None if it does not exist yet.

    Raises when this session never read the path, or when it changed since - the two
    ways a write acts on content the model has not actually seen. A path that does not
    exist is neither: creating a file cannot require reading it first.

    rat-tail: `Write` now reads the file it is about to replace, where before it read
    nothing. One extra full read per overwrite, to answer a question only the content
    can answer. A digest the backend could return without shipping the bytes is the
    upgrade path, and it arrives with the same backend work the `Read` bound waits on.
    """
    try:
        current = backend.read(path)
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as exc:
        # `Read` records no digest for a file that is not text (an image or a PDF comes back as blocks), so this check can never be satisfied. Said plainly rather than left as a dead end the model retries forever.
        raise ValueError(f"{path} is not UTF-8 text; {verb} writes text and will not "
                                    "overwrite it") from exc
    seen = session.files_read.get(backend.key(path))
    if seen is None:
        raise ValueError(f"{path} must be read first: {verb} will not modify a file "
                         "this session has not read. Call Read on it, then retry.")
    if seen != _digest(current):
        # A DIFFERENT message from the one above, deliberately. One message for both
        # sends the model to re-read a file it had read, or to give up on one it had not.
        raise ValueError(f"{path} changed on disk since it was read, so {verb} would "
                         "act on a stale copy. Read it again, then retry.")
    return current


@tool("Read",
      "Read a window of a file, `cat -n` style: the line number, a tab, then the line. "
      "The numbers are a PREFIX un adds and are not in the file, so text quoted into an "
      "`Edit` must not carry one. `offset` is the 1-based first line and `limit` how "
      f"many lines, defaulting to {READ_LIMIT}; a window stopping short of the end says "
      "so and gives the offset to continue from. A line longer than "
      f"{LINE_WIDTH} characters is cut and says how long it was. A PNG, JPEG, GIF or "
      "WebP comes back as the picture itself, and a PDF as the document itself, both "
      "identified by their content and not their name, with `offset` and `limit` not "
      "applying. `pages` picks a PDF's pages, 1-based: one page \"3\" or an inclusive "
      f"range \"3-7\", at most {PDF_PAGE_LIMIT} per call. A PDF of more than "
      f"{PDF_READ_PAGES} pages needs `pages`, and `pages` is refused for any other file.",
      {"type": "object",
       "properties": {"path": _TEXT,
                      "offset": {"type": "integer"},
                      "limit": {"type": "integer"},
                      "pages": {"type": "string"}},
       "required": ["path"]})
def read(*, session: Session, path: str, offset: int = 1,
        limit: int = READ_LIMIT, pages: str | None = None) -> str | list[dict]:
    if offset < 1:
        raise ValueError(f"offset is the 1-based first line to show, not {offset}")
    if limit < 1:
        raise ValueError(f"limit is how many lines to show, not {limit}")
    # Syntax before any I/O, after offset and limit: a malformed string is wrong whatever the file is.
    window = _window(pages)
    backend = _fs(session)
    try:
        text = backend.read(path)
    except UnicodeDecodeError as exc:
        data = backend.read_bytes(path)
        # rat-tail: only a PDF that fails UTF-8 decoding reaches here, so a hand-written ASCII-only PDF reads as text and records a ledger entry. Every real-world PDF, and every file pypdf writes, carries the binary marker line. A `startswith("%PDF-")` check on the decoded text is the upgrade path.
        if data.startswith(PDF_SIGNATURE):
            # Nothing goes in the read ledger, for the image reason below.
            sent, first, last, total = _pdf(path, data, window)
            return [{"type": "text",
                     "text": f"[pdf: {path}, pages {first}-{last} of {total}, {len(sent)} bytes]"},
                    {"type": "document",
                     "source": {"type": "base64", "media_type": "application/pdf",
                                "data": base64.b64encode(sent).decode("ascii")}}]
        media = _media_type(data)
        if media is None:
            # Nothing was read, so nothing is recorded below: a file the model has not
            # seen must not become one `Write` will overwrite.
            raise ValueError(f"{path} is not UTF-8 text and is not a PDF or an image Read "
                             f"can show ({', '.join(IMAGE_TYPES)})") from exc
        if window is not None:
            raise ValueError(f"{path} is a {media} image; pages applies only to a PDF")
        # NOTHING goes in the read ledger. It answers "may Write overwrite this", and
        # seeing a picture is not consent to replace it with text - which is what an
        # entry here would authorise, since `Write` only checks that one was made.
        #
        # REBOUND before the text block is built, so the reported size is the size
        # actually sent rather than the size on disk.
        data = _fitted(path, data, media)
        return [{"type": "text",
                "text": f"[image: {path}, {media}, {len(data)} bytes]"},
                {"type": "image",
                "source": {"type": "base64", "media_type": media,
                            "data": base64.b64encode(data).decode("ascii")}}]
    # Before the ledger write: a refused call showed nothing and must authorise nothing.
    if window is not None:
        raise ValueError(f"{path} is text; pages applies only to a PDF, so use offset and limit")
    lines = text.splitlines()
    # `lines and`, so an empty file reads as empty at any offset. There is no line to be
    # past, and refusing would make the error depend on a count the caller cannot know
    # until it has read the file.
    if lines and offset > len(lines):
        raise ValueError(f"{path} has {len(lines)} lines; offset {offset} is past the end")
    # The WHOLE file's digest, though only a window comes back. The ledger's question is
    # whether the file changed since it was looked at, and a window's digest cannot
    # answer that - recording one would refuse every write to a file bigger than the
    # default, which is every file the window exists for.
    #
    # After the offset check, not before: a call that raised showed the model nothing,
    # and a read the model never saw must not authorise a later write.
    session.files_read[backend.key(path)] = _digest(text)
    window = _number(lines[offset - 1:offset - 1 + limit], offset)
    last = offset + len(window) - 1
    if last < len(lines):
        # Announced, not silent, and with the offset to continue from: a caller who
        # cannot see the gap reasons past it. The same reason `grep` announces its
        # `head_limit`.
        window.append(f"[truncated: lines {offset}-{last} of {len(lines)} shown; "
                      f"read from offset {last + 1} for more]")
    return "\n".join(window)


@tool("Write",
      "Write a file, creating parent directories as needed. A file that already exists "
      "must have been read by this session first and must not have changed since; a "
      "file that does not exist yet needs no read.",
      {"type": "object", "properties": {"path": _TEXT, "content": _TEXT},
       "required": ["path", "content"]})
def write(*, session: Session, path: str, content: str) -> str:
    backend = _fs(session)
    with _modifying(backend.key(path)):
        _unchanged(session, backend, path, "Write")
        backend.write(path, content)
        # Refreshed, or the tool refuses its own last write and no two-step change is
        # possible.
        session.files_read[backend.key(path)] = _digest(content)
    return f"wrote {path}"


@tool("Edit",
      "Replace one exact occurrence of `old` with `new` in a file. `old` is raw file "
      "text: `Read` prefixes every line with a number and a tab, and those are not in "
      "the file - strip them. The file must have been read by this session and must "
      "not have changed since.",
      {"type": "object", "properties": {"path": _TEXT, "old": _TEXT, "new": _TEXT},
       "required": ["path", "old", "new"]})
def edit(*, session: Session, path: str, old: str, new: str) -> str:
    backend = _fs(session)
    with _modifying(backend.key(path)):
        # The ledger check reads the file, so `edit` reads it once rather than twice. Ahead
        # of the match count deliberately: the model cannot compose a good `old` for a file
        # it has not read, so the ledger reason is the useful one to report first.
        text = _unchanged(session, backend, path, "Edit")
        if text is None:
            raise FileNotFoundError(path)
        found = text.count(old)
        if found != 1:
            # Refuse rather than guess. Replacing the first of several matches is how an
            # agent silently edits the wrong line, and the file is left untouched so the
            # model can retry with more context instead of recovering from a bad write.
            raise ValueError(
                f"expected exactly one occurrence of that text in {path}, found {found}; "
                "include more surrounding context to make it unique"
            )
        updated = text.replace(old, new)
        backend.write(path, updated)
        session.files_read[backend.key(path)] = _digest(updated)
    return f"edited {path}"


@tool("Glob",
      "List files matching a glob pattern, most recently modified first - the file "
      "touched last is usually the one a question is about. `path` roots the walk and "
      "defaults to the session directory, with the pattern taken relative to it. "
      f"`head_limit` caps the result and says when it truncated, defaulting to "
      f"{GLOB_LIMIT}.",
      {"type": "object",
       "properties": {"pattern": _TEXT, "path": _TEXT,
                      "head_limit": {"type": "integer"}},
       "required": ["pattern"]})
def glob(*, session: Session, pattern: str, path: str = ".",
         head_limit: int = GLOB_LIMIT) -> str:
    matches = _fs(session).glob(pattern, path, head_limit=head_limit)
    return "\n".join(matches) if matches else "no matches"


@tool("Grep",
      "Search files for a regular expression. Uses ripgrep when it is on PATH, which "
      "respects .gitignore and is far faster; without it, a slower built-in walk that "
      # Generated from the set itself, sorted so the sentence does not follow set
      # iteration order. Spelling the seven names here by hand was the second copy that
      # `core.PRUNE` exists to retire.
      "skips " + ", ".join(sorted(PRUNE)) + ", and reads Python `re` "
      "syntax rather than Rust regex. `mode` chooses what comes back: `content` "
      "(file:line:text, the default), `files` (matching paths only - much cheaper on a "
      "broad search, reach for it first), or `count` (file:count). `glob` limits which "
      "files are searched, `ignore_case` is -i, and `head_limit` caps the result and "
      "says when it truncated.",
      {"type": "object",
       "properties": {"pattern": _TEXT, "path": _TEXT,
                      "mode": {"type": "string", "enum": list(MODES)},
                      "glob": _TEXT,
                      "ignore_case": {"type": "boolean"},
                      "head_limit": {"type": "integer"}},
       "required": ["pattern"]})
def grep(*, session: Session, pattern: str, path: str = ".", mode: str = "content",
         glob: str | None = None, ignore_case: bool = False,
         head_limit: int | None = None) -> str:
    hits = _fs(session).grep(pattern, path, mode=mode, glob=glob,
                             ignore_case=ignore_case, head_limit=head_limit)
    return "\n".join(hits) if hits else "no matches"
