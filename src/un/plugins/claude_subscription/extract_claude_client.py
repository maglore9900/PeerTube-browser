#!/usr/bin/env python
"""Read the installed Claude Code binary and rewrite `client.toml` from what it says.

Hand-run, never imported. `claude_subscription.py` pins every value it sends to one Claude Code version and
there is no handshake to negotiate them against, so drift surfaces as a 4xx from the endpoint - typically
`claude_code_version_too_old`, which names the version and nothing else. This is the upgrade path: point it at
the installed binary and it re-derives each pin.

    python extract_claude_client.py                      # report what it found, change nothing
    python extract_claude_client.py --write              # rewrite client.toml
    python extract_claude_client.py --binary <path>      # a binary that is not the one on PATH

DRY BY DEFAULT, because every value here decides what goes out over the wire and the diff is the only place an
operator sees a change before it ships. `--write` is the second look.

HOW IT READS. The binary is a Bun-compiled bundle carrying its own JavaScript source, so every pin is matched
against the SOURCE that computes it rather than against a loose string. That is the whole reliability argument:
`2.1.280` appears in a dozen unrelated places, `VERSION:"2.1.280"` immediately after `PACKAGE_URL` appears in
one construction, and a pattern that stops matching is a pattern that reports a miss instead of a wrong value.
Every pattern below is anchored that way and every one refuses on an ambiguous match.

WHAT IT CANNOT DO. `betas` is not extractable as "the list the client sends": the client assembles that per
request from feature gates, and the binary carries only a REGISTRY of every beta it knows. So the curated list
in `client.toml` is checked against that registry - every entry must still exist - and never overwritten.
"""

from __future__ import annotations

import argparse
import mmap
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

CONFIG = Path(__file__).with_name("client.toml")

# Every pattern is matched against the bundle's own JavaScript. `_one` requires a single distinct value across
# all matches, so a bundle that grew a second spelling stops the run rather than picking whichever came first.
PATTERNS = {
    # The build-constants object, inlined at every use site. `PACKAGE_URL` immediately before `VERSION` is what
    # separates it from the many other places the version string appears.
    "code_version": re.compile(
        rb'PACKAGE_URL:"@anthropic-ai/claude-code",README_URL:"[^"]*",VERSION:"([0-9][0-9A-Za-z.\-]*)"'),
    # The user-agent's own default, inside `claude-cli/<version> (external, <entrypoint>...)`.
    "entrypoint": re.compile(
        rb'\(external, \$\{[A-Za-z_$][\w$]*\.CLAUDE_CODE_ENTRYPOINT\?\?"([a-z_-]+)"\}'),
    # The BILLING header's default for the same variable, which is a different word - see the note in
    # `client.toml`. Anchored on `process.env.` because the user-agent reaches the same variable as `a.`.
    "billing_entrypoint": re.compile(
        rb'process\.env\.CLAUDE_CODE_ENTRYPOINT\?\?"([a-z_-]+)"'),
    # The `anthropic-client-platform` switch's default case.
    "client_platform": re.compile(rb'case"cli":default:return"([a-z_]+)"\}'),
    "billing_prefix": re.compile(rb'`(x-anthropic-billing-header:) cc_version=\$\{'),
    # The literal the client emits in place of a computed integrity value, with its own leading space.
    "cch_placeholder": re.compile(rb'\?" (cch=[0-9]+);":""'),
    # The CLI marker, not the Agent SDK variant that starts identically and runs on.
    "marker": re.compile(rb'="(You are Claude Code, Anthropic\'s official CLI for Claude\.)"'),
}

# The billing fingerprint, matched as ONE shape so the salt, the indices, the order the three parts are hashed
# in and the digest length cannot drift apart silently. The salt is captured by VARIABLE NAME and resolved
# below, because the bundle minifies it to something new on every build.
FINGERPRINT = re.compile(
    rb'let (?P<seed>[\w$]+)=\[(?P<indices>[\d,]+)\]\.map\(\((?P<arg>[\w$]+)\)=>e\[(?P=arg)\]\|\|"0"\)'
    rb'\.join\(""\),(?P<joined>[\w$]+)=`\$\{(?P<salt>[\w$]+)\}\$\{(?P=seed)\}\$\{n\}`;'
    rb'return [\w$]+\("sha256"\)\.update\((?P=joined)\)\.digest\("hex"\)\.slice\(0,(?P<slice>\d+)\)')

# `w(name, header)` builds one beta; the header is a literal for most and a variable for a few.
BETA = re.compile(rb'=w\("([a-z0-9_]+)",(?:"([a-z0-9._-]+)"|([\w$]+))\)')
# Per-model output ceilings. The client has no single global clamp - see `max_output_tokens` below.
MAX_TOKENS = re.compile(rb'max_output_tokens:\{default:(\d+),upper:(\d+)\}')


class Missing(Exception):
    """A pattern matched nothing, or matched two different things. Either way the value is not known."""


def _one(data: bytes, name: str, pattern: re.Pattern) -> str:
    """The single distinct value `pattern` finds, or a refusal naming what went wrong.

    Several matches are normal - the bundle inlines the same construction repeatedly - but they must AGREE.
    Disagreement means the anchor no longer identifies one thing, and guessing between them is how a wrong pin
    ships looking extracted.
    """
    found = {match.group(1).decode("utf-8") for match in pattern.finditer(data)}
    if not found:
        raise Missing(f"{name}: no match for {pattern.pattern.decode('utf-8', 'replace')[:90]}")
    if len(found) > 1:
        raise Missing(f"{name}: {len(found)} different values match: {sorted(found)}")
    return found.pop()


def _fingerprint(data: bytes) -> tuple[str, list[int], int]:
    """(salt, indices, digest length) out of the billing fingerprint function."""
    matches = list(FINGERPRINT.finditer(data))
    if not matches:
        raise Missing("fingerprint: the seed/salt/sha256 shape matched nothing")
    seen = {(m.group("salt"), m.group("indices"), m.group("slice")) for m in matches}
    if len(seen) > 1:
        raise Missing(f"fingerprint: {len(seen)} different shapes match")
    match = matches[0]
    variable = re.escape(match.group("salt"))
    # The salt is `var <name>="<hex>"` or `,<name>="<hex>"` in the same minified scope.
    salts = {found.group(1).decode("utf-8")
             for found in re.finditer(rb'[,;{ ]' + variable + rb'="([0-9a-f]{8,})"', data)}
    if len(salts) != 1:
        raise Missing(f"fingerprint: salt variable {match.group('salt').decode()} resolved to {sorted(salts)}")
    indices = [int(part) for part in match.group("indices").decode("utf-8").split(",")]
    return salts.pop(), indices, int(match.group("slice"))


def _betas(data: bytes) -> set[str]:
    """Every beta HEADER the binary knows. The registry, NOT the set a request carries.

    Keyed by header rather than by name, because the registry reuses a name: `tool_search` is declared twice,
    once as `advanced-tool-use-2025-11-20` and once as `tool-search-tool-2025-10-19`. A name-keyed dict drops
    the first and then reports a curated beta as missing when it is sitting right there.
    """
    registry: set[str] = set()
    for match in BETA.finditer(data):
        if match.group(2) is not None:
            registry.add(match.group(2).decode("utf-8"))
            continue
        # A variable-valued header, e.g. `w("oauth_auth",Cd)`, resolved to the definition NEAREST the use site.
        # The bundle minifies each chunk independently and reuses short names across them: `Cd` is
        # `oauth-2025-04-20` 1.6 MB from this call and `defaults_mode` 15.7 MB away. Taking the nearest is what
        # distinguishes them; requiring a globally unique name instead drops a beta that is plainly there and
        # then reports it as removed, which is a false alarm in the one check that exists to be trusted.
        variable = re.escape(match.group(3))
        defined = [(abs(found.start() - match.start()), found.group(1).decode("utf-8"))
                   for found in re.finditer(rb'[,;{ (=]' + variable + rb'="([a-z0-9._-]{4,})"', data)]
        if defined:
            registry.add(min(defined)[1])
    return registry


def _installed_binary() -> Path:
    """The `claude` on PATH, resolved through its symlink to the real executable."""
    found = shutil.which("claude")
    if not found:
        raise Missing("no `claude` on PATH; pass --binary <path>")
    return Path(found).resolve()


def _installed_version() -> str:
    """What `claude --version` says, for the cross-check against what the bytes say."""
    try:
        out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unavailable ({exc})"
    return out.stdout.strip() or "unavailable (no output)"


def extract(path: Path) -> tuple[dict, set[str], list[tuple[int, int]]]:
    """(pins, beta registry, per-model output ceilings) out of one binary."""
    with path.open("rb") as handle:
        data = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            pins = {name: _one(data, name, pattern) for name, pattern in PATTERNS.items()}
            salt, indices, length = _fingerprint(data)
            registry = _betas(data)
            ceilings = sorted({(int(m.group(1)), int(m.group(2))) for m in MAX_TOKENS.finditer(data)})
        finally:
            data.close()
    pins["fingerprint_salt"] = salt
    pins["fingerprint_indices"] = indices
    pins["fingerprint_digest_length"] = length
    if not ceilings:
        raise Missing("max_output_tokens: no per-model ceiling matched")
    # NOT a pin. The client clamps PER MODEL - the binary carries ceilings from (8192, 8192) to (128000, 128000)
    # and no global value - so there is nothing here to extract into one number. Taking the highest would send
    # 128000 to a model whose upper is 32000 and turn a working request into a 400. The observed table is
    # reported and `max_output_tokens` stays curated, for the same reason `betas` does.
    return pins, registry, ceilings


def _toml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml(item) for item in value) + "]"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(pins: dict, betas: list[str], curated_max: int, provenance: dict) -> str:
    """The whole of `client.toml`. Written out rather than patched, so the file has exactly one author."""
    lines = [
        "# The Claude Code client this plugin impersonates, one entry per pinned value.",
        "#",
        "# GENERATED by `extract_claude_client.py` beside it, which reads the installed Claude Code binary. A hand-edit survives until the next extraction and is then lost, so fix the extractor rather than this file when a value is wrong.",
        "#",
        "# There is no handshake to negotiate any of this against, so drift surfaces as a 4xx from the endpoint - typically `claude_code_version_too_old`, which names the version and nothing else. Re-run the extractor when that happens.",
        "",
        "[provenance]",
        "# `claude_version` is the client these values were read out of. A mismatch between it and `claude --version` is the first thing to check when the endpoint starts refusing.",
    ]
    for key, value in provenance.items():
        lines.append(f"{key} = {_toml(value)}")
    lines += [
        "",
        "[client]",
        "# `claude-cli/<version> (external, <entrypoint>)` in the user-agent, and `cc_version=<version>.<suffix>` in the billing header, where it is also hashed into the suffix.",
        f"code_version = {_toml(pins['code_version'])}",
        "# `process.env.CLAUDE_CODE_ENTRYPOINT ?? \"cli\"`, as the USER-AGENT spells the default.",
        f"entrypoint = {_toml(pins['entrypoint'])}",
        "# The same variable's default in the BILLING header, which the client spells differently. Read but not yet used: `claude_subscription.billing_header` sends `entrypoint` above for both.",
        f"billing_entrypoint = {_toml(pins['billing_entrypoint'])}",
        "# The `anthropic-client-platform` switch's default case.",
        f"client_platform = {_toml(pins['client_platform'])}",
        "# CURATED, and not extracted: the client clamps PER MODEL, with ceilings from (8192, 8192) to (128000, 128000) and no global value, so there is no single number in the binary to read. See `max_output_tokens_observed` in [provenance] for every pair the last extraction found.",
        f"max_output_tokens = {_toml(curated_max)}",
        "# The billing fingerprint: characters at `fingerprint_indices` of the first user message are joined, prefixed with `fingerprint_salt`, suffixed with `code_version`, and the first `fingerprint_digest_length` hex digits of the SHA-256 become the version suffix.",
        f"fingerprint_salt = {_toml(pins['fingerprint_salt'])}",
        f"fingerprint_indices = {_toml(pins['fingerprint_indices'])}",
        f"fingerprint_digest_length = {_toml(pins['fingerprint_digest_length'])}",
        f"billing_prefix = {_toml(pins['billing_prefix'])}",
        "# Sent VERBATIM, not computed. The client emits this literal and nothing in the binary replaces it.",
        f"cch_placeholder = {_toml(pins['cch_placeholder'])}",
        "# System block [1], between the billing header and un's own prompt.",
        f"marker = {_toml(pins['marker'])}",
        "# CURATED, and the one list this extractor does not overwrite: the client assembles the set it sends per request from feature gates, so the binary carries only a registry of every beta it knows. Each entry below is checked to still exist in that registry.",
        "betas = [",
    ]
    lines += [f"    {_toml(beta)}," for beta in betas]
    lines += ["]", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--binary", type=Path, default=None, help="the Claude Code executable to read")
    parser.add_argument("--write", action="store_true", help="rewrite client.toml; without it, report only")
    args = parser.parse_args(argv)

    try:
        binary = args.binary or _installed_binary()
        pins, registry, ceilings = extract(binary)
    except Missing as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        print("The bundle has moved since these patterns were written. Fix the pattern rather than the value: "
              "a pin guessed here is sent on every request.", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"REFUSED: cannot read the binary: {exc}", file=sys.stderr)
        return 1

    with CONFIG.open("rb") as handle:
        before = tomllib.load(handle)
    current = before.get("client", {})
    betas = list(current.get("betas", []))

    reported = _installed_version()
    print(f"binary   {binary}")
    print(f"reports  {reported}")
    print(f"bytes    code_version = {pins['code_version']}")
    if pins["code_version"] not in reported:
        print(f"  WARNING: `claude --version` and the bytes disagree; the binary read may not be the one on PATH")
    print(f"\n{len(registry)} betas in the binary's registry; {len(betas)} curated in client.toml")
    if gone := [beta for beta in betas if beta not in registry]:
        print(f"  WARNING: curated beta no longer in the registry: {', '.join(gone)}")
    if added := sorted(registry - set(betas)):
        print(f"  not curated ({len(added)}): {', '.join(added)}")
    print(f"\nper-model output ceilings (default, upper): {ceilings}")
    print(f"  max_output_tokens stays curated at {current.get('max_output_tokens', '<absent>')}; "
          f"no single global clamp exists to extract")

    print("\n--- pins ---")
    changed = False
    for key in ("code_version", "entrypoint", "billing_entrypoint", "client_platform",
                "fingerprint_salt", "fingerprint_indices", "fingerprint_digest_length", "billing_prefix",
                "cch_placeholder", "marker"):
        was, now = current.get(key, "<absent>"), pins[key]
        mark = "   " if was == now else ">> "
        changed = changed or was != now
        print(f"{mark}{key} = {now!r}" + ("" if was == now else f"   (was {was!r})"))

    if not args.write:
        print("\nDRY RUN. Nothing written." + ("  Re-run with --write to apply the >> lines."
                                               if changed else "  Nothing would change."))
        return 0

    provenance = {
        "claude_version": pins["code_version"],
        "reported_by_cli": reported,
        "extracted_from": str(binary),
        "extracted_at": date.today().isoformat(),
        "extractor": "extract_claude_client.py",
        "beta_registry_size": len(registry),
        "max_output_tokens_observed": [list(pair) for pair in ceilings],
    }
    curated_max = current.get("max_output_tokens")
    if not isinstance(curated_max, int):
        print(f"REFUSED: {CONFIG} carries no integer max_output_tokens to carry forward; this extractor does "
              f"not invent one", file=sys.stderr)
        return 1
    CONFIG.write_text(render(pins, betas, curated_max, provenance), encoding="utf-8")
    # Read back rather than trusting the write: this file is parsed at import by a plugin whose refusal is
    # non-fatal, so a malformed write would surface as a provider that silently is not there.
    with CONFIG.open("rb") as handle:
        after = tomllib.load(handle)
    if after.get("client", {}).get("code_version") != pins["code_version"]:
        print(f"REFUSED: {CONFIG} did not read back with the value just written", file=sys.stderr)
        return 1
    print(f"\nwrote {CONFIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
