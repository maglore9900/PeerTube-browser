"""The OAuth 2.0 authorization-code + PKCE mechanism, and the `un login` verb.

The mechanism names no issuer: issuers arrive as `Client`s from `oauth:<name>` services other plugins register (ADR-0020). Importing this module also registers `command:login`. `un login` walks every issuer and skips those with a usable credential, so running it twice is a no-op. Uses urllib rather than httpx, which is only a transitive dependency.

Writes `.un/oauth/<name>.credentials.json`, mode 0600, one file per issuer.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from un import EXIT_FAILED, EXIT_OK, ProviderError, service, variants
from un.core import OAUTH, locked, project_root


# ---- the mechanism: the flow, the token store, and refresh --------------------------

TOKEN_MODE = 0o600
# Refresh this many seconds early, so a token cannot expire mid-request.
SKEW = 60


class NotAuthorized(ProviderError):
    """No usable credential for this issuer, or the issuer refused to supply one."""


@dataclass(frozen=True)
class Client:
    """One issuer, as an `oauth:<name>` service returns it. A public client: PKCE, no secret.

    A loopback `redirect_uri` is caught by a local listener; any other is pasted back. Query parameters already on `authorize_url` are kept.
    """

    name: str
    client_id: str
    authorize_url: str
    token_url: str
    redirect_uri: str
    scope: str
    # Send a JSON token-request body instead of the RFC's form encoding (Anthropic requires JSON).
    token_json: bool = False
    # Token-request User-Agent; "" means urllib's, which some endpoints (Anthropic's, behind Cloudflare) refuse.
    user_agent: str = ""


def challenge(verifier: str) -> str:
    """The S256 challenge for a verifier (RFC 7636 4.2). Separate from `pkce` so it can be tested against the RFC's example."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def pkce() -> tuple[str, str]:
    """A verifier and its S256 challenge. The slice enforces the RFC's 128-character maximum."""
    verifier = secrets.token_urlsafe(96)[:128]
    return verifier, challenge(verifier)


def authorize_url(client: Client, code_challenge: str, state: str) -> str:
    """The URL where the operator approves the request (RFC 6749 4.1.1 plus PKCE), merged into the issuer's own query."""
    parts = urllib.parse.urlparse(client.authorize_url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query.update({
        "response_type": "code",
        "client_id": client.client_id,
        "redirect_uri": client.redirect_uri,
        "scope": client.scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return urllib.parse.urlunparse(
        parts._replace(query=urllib.parse.urlencode(query)))


def localhost_port(redirect_uri: str) -> int | None:
    """The port of an http(s) loopback redirect URI, or None, which means the code is pasted back instead."""
    try:
        parsed = urllib.parse.urlparse(redirect_uri)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        return None
    try:
        return parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def listen(port: int, timeout: float = 300.0) -> dict[str, str]:
    """Serve on `port` until a request carries `code` or `error`, and return its query parameters. Loops because the browser may fetch `/favicon.ico` first."""
    captured: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.urlparse(self.path).query
            captured.update({k: v[0] for k, v in urllib.parse.parse_qs(query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<p>Signed in. You can close this tab.</p>")

        def log_message(self, *args):
            """Silenced: request logging on stderr reads as an error."""

    deadline = time.monotonic() + timeout
    with HTTPServer(("127.0.0.1", port), Handler) as server:
        while not ({"code", "error"} & captured.keys()):
            server.timeout = deadline - time.monotonic()
            if server.timeout <= 0:
                break
            server.handle_request()
    if not captured:
        raise NotAuthorized(f"no callback reached port {port} within {timeout:.0f}s")
    return captured


def _post(url: str, form: dict[str, str], *, as_json: bool = False,
          user_agent: str = "") -> dict:
    """One POST to a token endpoint, form-encoded or JSON, returning the parsed JSON object."""
    # https only (plain http on loopback): urllib would otherwise follow `file://` to a local read.
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "::1", "localhost")):
        raise NotAuthorized(f"{url} is not a token endpoint un will post to; use https")
    if as_json:
        body = json.dumps(form).encode("utf-8")
        content_type = "application/json"
    else:
        body = urllib.parse.urlencode(form).encode("ascii")
        content_type = "application/x-www-form-urlencoded"
    headers = {"Content-Type": content_type, "Accept": "application/json"}
    if user_agent:
        headers["User-Agent"] = user_agent
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        # The body carries the RFC 6749 5.2 error description.
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise NotAuthorized(f"{url} returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise NotAuthorized(f"{url} could not be reached: {exc.reason}") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        # Typically a proxy or captive portal answering with HTML.
        raise NotAuthorized(
            f"{url} answered with something that is not JSON: "
            f"{raw.decode('utf-8', 'replace')[:200]}") from exc
    if not isinstance(payload, dict):
        raise NotAuthorized(f"{url} answered with {type(payload).__name__}, not an object")
    return payload


def _agent(client) -> str:
    """This issuer's token-request User-Agent, or "". `getattr`, as in `_wants_json`."""
    return getattr(client, "user_agent", "") or ""


def _wants_json(client) -> bool:
    """Whether the token endpoint wants JSON. `getattr`, because an issuer may return its own type carrying only the six required fields."""
    return bool(getattr(client, "token_json", False))


def _record(payload: dict) -> dict:
    """The token response as the stored record, with `expires_in` converted to an absolute `expires_at` (0.0 = never). A response with no access token is refused."""
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise NotAuthorized(
            "the token endpoint returned success but no access_token; it answered with "
            f"{sorted(payload)}")
    expires_in = payload.get("expires_in")
    return {
        "access_token": access_token,
        "refresh_token": payload.get("refresh_token") or "",
        "expires_at": time.time() + float(expires_in) if expires_in else 0.0,
        "scope": payload.get("scope", ""),
    }


def exchange(client: Client, code: str, verifier: str, state: str = "") -> dict:
    """An authorization code for a token record. RFC 6749 section 4.1.3, plus PKCE."""
    form = {"grant_type": "authorization_code", "code": code,
            "client_id": client.client_id, "redirect_uri": client.redirect_uri,
            "code_verifier": verifier}
    # Omitted rather than sent empty, which some issuers refuse.
    if state:
        form["state"] = state
    return _record(_post(client.token_url, form, as_json=_wants_json(client),
                         user_agent=_agent(client)))


def refresh(client: Client, refresh_token: str) -> dict:
    """Refresh a token record (RFC 6749 6), keeping the old refresh token when the issuer does not rotate it."""
    fresh = _record(_post(client.token_url, {
        "grant_type": "refresh_token", "refresh_token": refresh_token,
        "client_id": client.client_id}, as_json=_wants_json(client),
        user_agent=_agent(client)))
    return {**fresh, "refresh_token": fresh["refresh_token"] or refresh_token}


def _path(name: str, cwd: Path | None = None) -> Path:
    """Where one issuer's credential lives. Both its directory and its `*credentials*` name are denied to the model's file tools."""
    return Path(cwd or project_root() or Path.cwd()) / OAUTH / f"{name}.credentials.json"


def save(name: str, record: dict, cwd: Path | None = None) -> Path:
    """Write one issuer's credential, owner-readable only, replacing any old one atomically. Returns where it went."""
    path = _path(name, cwd)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Written aside and renamed over, so a concurrent `load` reads the old record or the new one, never a truncated file.
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        # Restricted before the secret is written.
        os.fchmod(handle, TOKEN_MODE)
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(json.dumps(record, indent=2) + "\n")
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return path


def load(name: str, cwd: Path | None = None) -> dict | None:
    """One issuer's stored credential, or None when absent, unreadable or corrupt."""
    path = _path(name, cwd)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return record if isinstance(record, dict) else None


def expired(record: dict) -> bool:
    """Whether this record needs refreshing. One stating no expiry never does."""
    return bool(record.get("expires_at")) and record["expires_at"] - SKEW <= time.time()


def _digest(secret: str) -> str:
    """A 12-hex fingerprint of a token, enough to tell two apart and useless as the token."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12] if secret else "none"


def _trail(name: str, cwd: Path | None, outcome: str) -> None:
    """Append one line to `refresh.log` beside the credential. A refresh whose `sent` is not the last `saved` means something other than un wrote the file."""
    path = _path(name, cwd).with_name("refresh.log")
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, TOKEN_MODE)
    with os.fdopen(handle, "a", encoding="utf-8") as out:
        out.write(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} pid={os.getpid()} "
                  f"root={path.parent.parent.parent} {outcome}\n")


def _stored(client: Client, cwd: Path | None) -> dict:
    """The stored record, or `NotAuthorized` naming `un login` when there is none."""
    record = load(client.name, cwd)
    if record is None:
        raise NotAuthorized(f"no credential for {client.name!r}; run: un login")
    return record


def token(client: Client, cwd: Path | None = None) -> str:
    """A live access token, refreshed if expired. Raises `NotAuthorized` rather than return an empty bearer."""
    record = _stored(client, cwd)
    if not expired(record):
        return record["access_token"]
    # A rotated refresh token is single-use, so one caller (thread or process) spends it and the rest read what it saved.
    with locked(_path(client.name, cwd).with_suffix(".lock")):
        record = _stored(client, cwd)
        if expired(record):
            if not record.get("refresh_token"):
                raise NotAuthorized(
                    f"credential for {client.name!r} has expired and the issuer stored no "
                    "refresh token; run: un login")
            sent = record["refresh_token"]
            try:
                record = refresh(client, sent)
            except NotAuthorized as exc:
                _trail(client.name, cwd, f"refresh sent={_digest(sent)} -> {exc}")
                raise
            save(client.name, record, cwd)
            _trail(client.name, cwd, f"refresh sent={_digest(sent)} -> saved={_digest(record['refresh_token'])}")
    return record["access_token"]


# ---- the verb: `un login` ------------------------------------------------------------

def _valid_until(record: dict) -> str:
    """What to say about a credential that does not need touching."""
    if not record.get("expires_at"):
        return "credential is valid"
    when = datetime.fromtimestamp(record["expires_at"], timezone.utc)
    return f"credential is valid until {when:%Y-%m-%d %H:%M} UTC"


def _live(client: Client) -> dict | None:
    """The stored credential if usable, refreshing via `token` if needed; None means a new approval is required."""
    try:
        token(client)
    except NotAuthorized:
        return None
    return load(client.name)


def _authorize(client: Client) -> dict:
    """Run one issuer's flow start to finish and return its token record."""
    verifier, code_challenge = pkce()
    # 32 bytes: Anthropic refuses shorter state.
    state = secrets.token_urlsafe(32)
    port = localhost_port(client.redirect_uri)

    print(f"\n{client.name}: open this and approve\n\n  "
          f"{authorize_url(client, code_challenge, state)}\n")
    if port is None:
        # Accepts either `code#state` or a bare code.
        code, _, returned = input(
            "paste the code shown afterwards: ").strip().partition("#")
    else:
        print(f"waiting for the callback on port {port} ...")
        params = listen(port)
        if "error" in params:
            raise NotAuthorized(params["error"])
        code, returned = params.get("code", ""), params.get("state", "")

    # Checked only when the issuer echoed a state back.
    if returned and returned != state:
        raise NotAuthorized("state did not match; discarding the code")
    if not code:
        raise NotAuthorized("no authorization code came back")
    return exchange(client, code, verifier, returned)


@service("command:login")
def login(args: argparse.Namespace) -> int:
    """authorize every OAuth issuer that needs it"""
    issuers = variants("oauth")
    if not issuers:
        print("no OAuth issuers registered; enable a plugin that provides one "
              "(see `un plugins`)", file=sys.stderr)
        return EXIT_FAILED

    failed = False
    for name, issuer in issuers.items():
        try:
            # Inside the guard: one broken third-party issuer must not stop the others.
            client = issuer()
            if record := _live(client):
                print(f"{name}: {_valid_until(record)}")
                continue
            record = _authorize(client)
            print(f"{name}: saved to {save(name, record)}")
            _trail(name, None, f"login saved={_digest(record.get('refresh_token', ''))}")
        except Exception as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            failed = True
    return EXIT_FAILED if failed else EXIT_OK
