"""Anthropic Messages API provider. Writes nothing; network I/O only."""

from __future__ import annotations

import sys
import time

from un import (SYSTEM_UNSUPPORTED, CacheSpec, Profile, ProviderError, Reply,
                env_value, fold_system, providers, service, warn_spoofable)
from un.core import project_root
from pathlib import Path


def _emit(sink, channel: str, text: str) -> None:
    """Push to the caller's sink if there is one. Headless runs pass None."""
    if sink is not None:
        sink(channel, text)


def _warn(sink, text: str) -> None:
    """A warning through the caller's sink, else stderr; printing under an interface would be repainted away."""
    if sink is not None:
        sink("error", text)
        return
    print(text, file=sys.stderr)


_client: anthropic.Anthropic | None = None


class NotAuthenticated(ProviderError):
    """The SDK's credential chain came up empty."""


class Refused(RuntimeError):
    """Safety classifiers declined the request. Not an API error, a content outcome."""


def _get_client() -> anthropic.Anthropic:
    """The shared client, imported and built on first use: the SDK resolves credentials at construction and costs ~0.3s to import.

    `max_retries` is the whole retry policy; the SDK backs off on 408/409/429/5xx itself.
    """
    import anthropic

    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=5)
    return _client


def _client_for(profile: Profile) -> anthropic.Anthropic:
    """The client for this profile: the SDK's own credential chain, or a client built on the variable `api_key` names."""
    import anthropic

    if not profile.api_key:
        return _get_client()
    key = env_value(project_root() or Path.cwd(), profile.api_key)
    if not key:
        raise NotAuthenticated(
            f"provider {profile.name!r} names api_key = {profile.api_key!r}, but that "
            "variable is set neither in the project's .env nor in the environment.")
    return anthropic.Anthropic(api_key=key, max_retries=5)


MISPLACED = "was handed operator text in a position the Messages API refuses"

# Pauses before the second and third attempt at a reply whose stream was cut; one more attempt than there are pauses.
# rat-tail: a fixed 1 s then 2 s, three attempts, for every profile; a connection that drops on every attempt still fails the call, and a retry key on `[providers.<name>]` is the upgrade path if a gateway ever needs more.
RETRY_PAUSES = (1, 2)


def _transport_errors() -> tuple[type[Exception], ...]:
    """The transport-error base of whichever HTTP stack the SDK imported, read from `sys.modules` so un imports neither.

    rat-tail: knows `httpx` and `httpx2` by name; an SDK moving to a third stack makes the retry match nothing, which the retry tests catch, and adding the name is the upgrade path.
    """
    return tuple(module.TransportError for name in ("httpx", "httpx2")
                 if (module := sys.modules.get(name)) is not None)


def _system_misplaced(messages: list[dict]) -> bool:
    """Whether a system message is first, or is followed by anything but an assistant turn - both refused by the Messages API.

    An interrupted or bounded turn strands one this way. `claude_subscription` keeps its own copy, since importing this module would register it.
    """
    for index, message in enumerate(messages):
        if message.get("role") != "system":
            continue
        if index == 0:
            return True
        after = messages[index + 1:index + 2]
        if after and after[0].get("role") != "assistant":
            return True
    return False


def call(profile: Profile, *, system: str, messages: list[dict], tools: list[dict],
         model: str, effort: str, cache: CacheSpec, emit=None) -> Reply:
    # Needed here for the exception type in the `except` below.
    import anthropic

    # After the SDK import, so its HTTP stack is in sys.modules.
    transport = _transport_errors()

    # A breakpoint on the system block caches tools + system; top-level cache_control caches the history. Omitted, not None, when not promised.
    system_block = [{"type": "text", "text": system}]
    if cache.system_stable:
        system_block[-1]["cache_control"] = {"type": "ephemeral"}
    caching = ({"cache_control": {"type": "ephemeral"}}
               if cache.history_append_only else {})

    def issue(sent: list[dict]) -> Reply:
        attempts = len(RETRY_PAUSES) + 1
        for attempt in range(1, attempts + 1):
            opened = False
            try:
                with _client_for(profile).beta.messages.stream(
                    model=model,
                    # Large, and streamed: max_tokens caps thinking and text together.
                    max_tokens=64000,
                    betas=["server-side-fallback-2026-07-01"],
                    # Routes a classifier refusal by category rather than pinning a fallback model.
                    fallbacks="default",
                    system=system_block,
                    tools=tools,
                    messages=sent,
                    **caching,
                    output_config={"effort": effort},
                    # No `thinking` (omitted means adaptive); this model family rejects temperature/top_p/top_k.
                ) as stream:
                    # Entered means the response arrived; only a fault after this is a cut.
                    opened = True
                    for event in stream:
                        # Text only; `core.gate` announces tool calls.
                        if (event.type == "content_block_delta"
                                and event.delta.type == "text_delta"):
                            _emit(emit, "text", event.delta.text)
                    return stream.get_final_message()
            except transport as exc:
                # Before the stream opened is the SDK's `max_retries` to handle, not ours.
                if not opened or attempt == attempts:
                    raise
                _warn(emit, f"warning: provider {profile.name!r} dropped the connection mid-reply ({type(exc).__name__}); retrying, attempt {attempt + 1} of {attempts}")
                time.sleep(RETRY_PAUSES[attempt - 1])

    # Detected from position before sending; the SYSTEM_UNSUPPORTED retry below is a different fault.
    # rat-tail: folds every system message, not just the misplaced one.
    if _system_misplaced(messages):
        # No remedy: a stranded message is un's own to repair and no model choice affects
        # it, so the advice the other branch gives would be unfollowable here.
        #warn_spoofable(model, emit, why=MISPLACED, remedy="")
        messages = fold_system(messages)

    # Nested so the retry is also covered by the credential translation.
    try:
        try:
            response = issue(messages)
        except anthropic.BadRequestError as exc:
            if SYSTEM_UNSUPPORTED not in str(exc):
                raise
            warn_spoofable(model, emit)
            response = issue(fold_system(messages))
    except TypeError as exc:
        # The SDK reports a missing credential as a TypeError from inside the `with` (anthropic 0.125.0). Any other TypeError is a bug.
        if "authentication" not in str(exc).lower():
            raise
        # The SDK's own words; un adds only the profile name.
        raise NotAuthenticated(
            f"provider {profile.name!r} has no usable credential: {exc}") from exc

    # A refusal is HTTP 200 with empty or partial content, so check before reading it.
    if response.stop_reason == "refusal":
        raise Refused(str(response.stop_details))

    wire = response.to_dict()
    return Reply(content=wire["content"], stop_reason=response.stop_reason,
                 usage=wire["usage"])


# rat-tail: five seconds and one retry, not the shared client's five retries at the SDK's default timeout. `/v1/models/{id}` reads metadata, so it answers fast or not at all, and this runs on a session's first turn: the ceiling is about eleven seconds on an unreachable endpoint (two attempts plus the SDK's backoff), and the one retry covers a transient 429/529. The upgrade path is a `timeout` key on the profile if a gateway ever needs longer.
PROBE_TIMEOUT = 5
PROBE_RETRIES = 1


@service("probe:anthropic")
def probe(profile: Profile, model: str) -> int | None:
    """The model's input window from the Models API, or None when the answer states no usable one.

    Registered at module level, not in `register`: the key is per adaptor, as `probe:ollama`'s is. Uses `call`'s client for the profile. What could not be asked (404, refused credential, unreachable) raises. `max_tokens` beside it is the output cap, never read.
    """
    try:
        info = (_client_for(profile)
                .with_options(timeout=PROBE_TIMEOUT, max_retries=PROBE_RETRIES)
                .models.retrieve(model))
    except TypeError as exc:
        # `call`'s translation, repeated so `call` stays untouched: the SDK reports a missing credential as a TypeError.
        if "authentication" not in str(exc).lower():
            raise
        raise NotAuthenticated(
            f"provider {profile.name!r} has no usable credential: {exc}") from exc
    # getattr: pyproject allows anthropic>=0.60, which may predate the field.
    size = getattr(info, "max_input_tokens", None)
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        return None
    return size


# The profile for a project with no `[providers]` table. Empty `model` falls through to `Session.model`. `context.FALLBACK` spells the same profile for the probe; change both together.
DEFAULT = Profile(name="anthropic", adaptor="anthropic", model="")


def register(profiles) -> None:
    """Register one `provider:<name>` service per anthropic-adaptor profile. The only registration path, so a table entry named `anthropic` cannot collide with a bare one."""
    claimed = [p for p in profiles if p.adaptor == "anthropic"]
    # Fall back to DEFAULT unless another profile already owns its name.
    if not claimed and not any(p.name == DEFAULT.name for p in profiles):
        claimed = [DEFAULT]

    for profile in claimed:
        def serve(*, system, messages, tools, model, effort, cache, emit=None,
                  _profile=profile):
            # Default argument, not a closure, so each service keeps its own profile.
            return call(_profile, system=system, messages=messages, tools=tools,
                        model=model, effort=effort, cache=cache, emit=emit)

        serve.__doc__ = (f"Anthropic Messages API as {profile.name}"
                         + (f" ({profile.model})." if profile.model else "."))
        service(f"provider:{profile.name}")(serve)


# At import, against the project the process was launched in.
register(providers(project_root() or Path.cwd()))
