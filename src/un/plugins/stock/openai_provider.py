"""OpenAI-compatible chat completions: one provider per `[providers.<name>]` profile with `adaptor = "openai"` (OpenAI, ollama, ...). Writes nothing; network I/O only.

Mostly translation between un's canonical Anthropic content blocks and chat-completions messages.
"""

from __future__ import annotations

import base64
import io
import json
import re
import sys
import time
from pathlib import Path

from un import (SYSTEM_UNSUPPORTED, Profile, ProviderError, Reply, env_value,
                fold_system, providers, service, warn_spoofable)
from un.core import project_root


class NotAuthenticated(ProviderError):
    """The endpoint refused the credential, or the named variable held nothing."""


class Refused(RuntimeError):
    """The endpoint's content filter declined. Not an API error, a content outcome."""


# un effort -> `reasoning_effort`. Exhaustive, so a new un effort raises KeyError instead of silently mapping.
EFFORT = {"low": "low", "medium": "medium", "high": "high",
          "xhigh": "high", "max": "high"}

# `finish_reason` -> un stop reason. `content_filter` is absent because it raises.
STOP = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens",
        "function_call": "tool_use"}

# Narrow, as seen from ollama, so unrelated 400s are not retried.
NO_THINKING = "does not support thinking"

# `fs.read`'s PDF placeholder; greedy, so a path holding ", pages " still ends at the last one.
PDF_PLACEHOLDER = re.compile(r"^\[pdf: (.+), pages \d+-\d+ of \d+, \d+ bytes\]$", re.M)

# Sent in place of a degraded PDF whose pages extract no text, so the model knows why it has nothing.
NO_TEXT_LAYER = "[this PDF has no text layer (likely scanned images), so no text could be sent in its place]"

# profile name -> fallbacks already forced, so each costs one rejected request per process.
_degraded: dict[str, set[str]] = {}

# Pauses before the second and third attempt at a reply whose stream was cut; one more attempt than there are pauses.
# rat-tail: a fixed 1 s then 2 s, three attempts, for every profile; a connection that drops on every attempt still fails the call, and a retry key on `[providers.<name>]` is the upgrade path if a gateway ever needs more.
RETRY_PAUSES = (1, 2)


def _emit(sink, channel: str, text: str) -> None:
    """Push to the caller's sink if there is one. Headless runs pass None."""
    if sink is not None:
        sink(channel, text)


def _client(profile: Profile, cwd: Path) -> openai.OpenAI:
    """A client built per call; the SDK is imported here because it costs ~0.3s and most runs never reach a provider.

    rat-tail: sends the placeholder key "un" when the profile names none, since the SDK requires one and ollama checks none.
    """
    import openai

    key = env_value(cwd, profile.api_key) if profile.api_key else None
    if profile.api_key and not key:
        raise NotAuthenticated(
            f"provider {profile.name!r} names api_key = {profile.api_key!r}, but that "
            f"variable is set neither in {Path(cwd) / '.env'} nor in the environment.")
    # The SDK's retries cover every fault before the stream opens; `call` retries only a cut after it.
    return openai.OpenAI(base_url=profile.url, api_key=key or "un", max_retries=5)


def _tools(tools: list[dict]) -> list[dict]:
    """un's tool schemas as function definitions: `input_schema` moves to `function.parameters`."""
    return [{"type": "function",
             "function": {"name": tool["name"],
                          "description": tool["description"],
                          "parameters": tool["input_schema"]}}
            for tool in tools]


def _media(blocks: list[dict], text: str) -> list[dict]:
    """Image and document blocks as `image_url` and `file` parts in block order, each file named after `fs.read`'s PDF placeholder in `text`.

    rat-tail: every document in `blocks` takes the one placeholder's name, since `Read` returns one PDF per result; pairing placeholders with documents in order is the upgrade path if a tool ever returns several.
    """
    found = PDF_PLACEHOLDER.search(text)
    # Cosmetic, so a rewritten or emptied placeholder falls back rather than dropping the file.
    filename = Path(found[1]).name if found else "document.pdf"
    parts = []
    for b in blocks:
        if b["type"] not in ("image", "document"):
            continue
        url = f"data:{b['source']['media_type']};base64,{b['source']['data']}"
        if b["type"] == "image":
            parts.append({"type": "image_url", "image_url": {"url": url}})
        else:
            parts.append({"type": "file", "file": {"filename": filename, "file_data": url}})
    return parts


def _text(blocks: list[dict]) -> str:
    return "\n".join(b["text"] for b in blocks if b["type"] == "text")


def _extracted(block: dict) -> str:
    """A PDF document block as each page's text under `--- page <n> ---`, numbered from the page labels `fs.read` writes; a sentence where there is no text to send."""
    from pypdf import PdfReader

    # Deliberately broad: lenient parsing leaks builtin exceptions, and a degraded profile extracts on every request, so a raise would fail every later turn.
    try:
        reader = PdfReader(io.BytesIO(base64.b64decode(block["source"]["data"])))
        pages = [(label, page.extract_text()) for label, page in zip(reader.page_labels, reader.pages)]
    except Exception as exc:  # noqa: BLE001
        return f"[this PDF's text could not be extracted: {exc}]"
    if not any(text.strip() for _, text in pages):
        return NO_TEXT_LAYER
    return "\n".join(f"--- page {label} ---\n{text}" for label, text in pages)


def _degrade(blocks: list[dict], pdf_as_text: bool) -> tuple[list[str], list[dict]]:
    """With `pdf_as_text`, the documents in `blocks` as their extracted text, and the blocks left for `_media`."""
    if not pdf_as_text:
        return [], blocks
    return ([_extracted(b) for b in blocks if b["type"] == "document"],
            [b for b in blocks if b["type"] != "document"])


def _carries_pdf(messages: list[dict]) -> bool:
    """Whether any message, or any tool result inside one, holds a document block."""
    for message in messages:
        if isinstance(message["content"], str):
            continue
        for block in message["content"]:
            inner = block["content"] if block["type"] == "tool_result" else [block]
            if not isinstance(inner, str) and any(b["type"] == "document" for b in inner):
                return True
    return False


def _parts(content: str | list[dict], pdf_as_text: bool = False) -> tuple[str, list[dict]]:
    """A tool result split into text (for the `tool` message) and image and file parts (for one following `user` message), since `tool` messages cannot carry either. A degraded PDF joins the text instead."""
    if isinstance(content, str):
        return content, []
    text = _text(content)
    pages, kept = _degrade(content, pdf_as_text)
    return "\n".join([text, *pages]), _media(kept, text)


def _messages(system: str, messages: list[dict], pdf_as_text: bool = False) -> list[dict]:
    """un's Anthropic-shaped messages as chat-completions messages, with the system prompt as a leading message.

    Content may be a string or a block list (every recorded assistant turn is blocks). Mid-conversation system messages pass through; folding them is only a fallback, since it makes them spoofable.
    """
    out = [{"role": "system", "content": system}]
    for message in messages:
        role, content = message["role"], message["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            # Thinking blocks have no field here and are dropped.
            text = "".join(b["text"] for b in content if b["type"] == "text")
            calls = [{"id": b["id"], "type": "function",
                      "function": {"name": b["name"],
                                   "arguments": json.dumps(b["input"])}}
                     for b in content if b["type"] == "tool_use"]
            # None, not "": some endpoints reject empty content beside tool_calls.
            built = {"role": role, "content": text or None}
            if calls:
                built["tool_calls"] = calls
            out.append(built)
            continue
        # One `tool` message per result, where un batches them; `is_error` has no field.
        for block in content:
            if block["type"] == "tool_result":
                text, parts = _parts(block["content"], pdf_as_text)
                out.append({"role": "tool", "tool_call_id": block["tool_use_id"],
                            "content": text})
                if parts:
                    # Directly after the call that produced them.
                    out.append({"role": "user", "content": parts})
            elif block["type"] == "text":
                out.append({"role": role, "content": block["text"]})
        # `core._deliver` puts a background job's images and documents at the top level, behind its text.
        pages, kept = _degrade(content, pdf_as_text)
        if pages:
            # A string of its own: there is no `tool` message to carry it, and the job text is left as it was.
            out.append({"role": "user", "content": "\n".join(pages)})
        parts = _media(kept, _text(content))
        if parts:
            out.append({"role": "user", "content": parts})
    return out


def _usage(usage) -> dict:
    """Token counts under un's names. A cached count of zero is kept, and an absent one is not invented."""
    if usage is None:
        return {}
    out = {"input_tokens": usage.prompt_tokens,
           "output_tokens": usage.completion_tokens}
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", None)
    if cached is not None:
        out["cache_read_input_tokens"] = cached
    return out


def _consume(stream, emit) -> tuple[list[dict], str | None, dict]:
    """Drain one stream into content blocks, the raw finish reason, and usage."""
    text: list[str] = []
    # Keyed by index: parallel calls' argument fragments arrive interleaved.
    calls: dict[int, dict] = {}
    finish, usage = None, None
    for chunk in stream:
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        # The final usage chunk has no choices.
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        if delta is not None:
            if delta.content:
                text.append(delta.content)
                _emit(emit, "text", delta.content)
            for call in delta.tool_calls or ():
                slot = calls.setdefault(call.index,
                                        {"id": "", "name": "", "args": ""})
                if call.id:
                    slot["id"] = call.id
                if call.function is not None:
                    if call.function.name:
                        # Not announced here; `core.gate` announces calls with their arguments.
                        slot["name"] = call.function.name
                    if call.function.arguments:
                        slot["args"] += call.function.arguments
        if choice.finish_reason:
            finish = choice.finish_reason
    content = [{"type": "text", "text": "".join(text)}] if text else []
    for _, slot in sorted(calls.items()):
        # Empty arguments mean none; malformed JSON raises rather than becoming `{}`.
        content.append({"type": "tool_use", "id": slot["id"], "name": slot["name"],
                        "input": json.loads(slot["args"] or "{}")})
    return content, finish, _usage(usage)


def _warn(sink, text: str) -> None:
    """A warning through the caller's sink, else stderr; printing under an interface would be repainted away."""
    if sink is not None:
        sink("error", text)
        return
    print(text, file=sys.stderr)


def _transport_errors() -> tuple[type[Exception], ...]:
    """The transport-error base of whichever HTTP stack the SDK imported, read from `sys.modules` so un imports neither.

    A copy of `anthropic_provider`'s, since importing that module would register its provider.
    rat-tail: knows `httpx` and `httpx2` by name; an SDK moving to a third stack makes the retry match nothing, which the retry tests catch, and adding the name is the upgrade path.
    """
    return tuple(module.TransportError for name in ("httpx", "httpx2")
                 if (module := sys.modules.get(name)) is not None)


def call(profile: Profile, *, system: str, messages: list[dict], tools: list[dict],
         model: str, effort: str, cache, emit=None) -> Reply:
    """One turn against one OpenAI-compatible endpoint. `cache` is unused: this API caches prefixes automatically."""
    # Needed here for the exception types below.
    import openai

    # After the SDK import, so its HTTP stack is in sys.modules.
    transport = _transport_errors()
    forced = _degraded.setdefault(profile.name, set())
    client = _client(profile, project_root() or Path.cwd())
    schemas = _tools(tools)

    def issue():
        extra = {}
        if "effort" not in forced:
            extra["reasoning_effort"] = EFFORT[effort]
        # Omitted when empty: some servers refuse `tools: []`.
        if schemas:
            extra["tools"] = schemas
        sent = fold_system(messages) if "system" in forced else messages
        attempts = len(RETRY_PAUSES) + 1
        for attempt in range(1, attempts + 1):
            opened = False
            try:
                with client.chat.completions.create(
                    model=model,
                    messages=_messages(system, sent, pdf_as_text="pdf" in forced),
                    stream=True,
                    # Otherwise the stream reports no usage.
                    stream_options={"include_usage": True},
                    **extra,
                ) as stream:
                    # Entered means the response arrived; only a fault after this is a cut.
                    opened = True
                    return _consume(stream, emit)
            except transport as exc:
                # Before the stream opened is the SDK's `max_retries` to handle, not ours.
                if not opened or attempt == attempts:
                    raise
                _warn(emit, f"warning: provider {profile.name!r} dropped the connection mid-reply ({type(exc).__name__}); retrying, attempt {attempt + 1} of {attempts}")
                time.sleep(RETRY_PAUSES[attempt - 1])

    try:
        content, finish, usage = issue()
    except openai.BadRequestError as exc:
        # Three narrow fallbacks, each taken once per endpoint; any other 400 raises.
        text = str(exc)
        if NO_THINKING in text and "effort" not in forced:
            forced.add("effort")
            _warn(emit,
                  f"warning: {model} does not accept a reasoning effort, so --effort "
                  f"{effort} is being dropped for provider {profile.name!r}.")
        elif SYSTEM_UNSUPPORTED in text and "system" not in forced:
            # Makes operator rules spoofable, so only on rejection, and warned.
            forced.add("system")
            warn_spoofable(model, emit)
        elif "pdf" not in forced and _carries_pdf(messages):
            # rat-tail: keyed on the request carrying a PDF, not on the error text, since endpoints word this refusal differently; a 400 caused by something else in the same request costs one text-only retry, and matching per-endpoint wording is the upgrade path.
            forced.add("pdf")
            _warn(emit,
                  f"warning: provider {profile.name!r} refused a PDF, so {model} is being "
                  f"sent each PDF as its extracted text from now on.")
        else:
            raise
        content, finish, usage = issue()
    except openai.AuthenticationError as exc:
        # The endpoint's own reason, when it gave one, after the profile details.
        said = str(exc).strip()
        raise NotAuthenticated(
            f"provider {profile.name!r} at {profile.url} refused the credential"
            + (f" held in {profile.api_key}" if profile.api_key
               else " and the profile names no api_key")
            + (f": {said}" if said else ".")) from exc

    # A refusal is a normal 200 with empty content.
    if finish == "content_filter":
        raise Refused(f"{profile.name} declined the request on content grounds")
    return Reply(content=content, stop_reason=STOP.get(finish, finish or "end_turn"),
                 usage=usage)


def register(profiles) -> None:
    """Register one `provider:<name>` service per openai-adaptor profile. A function so tests can drive it with their own config."""
    for profile in profiles:
        if profile.adaptor != "openai":
            continue

        def serve(*, system, messages, tools, model, effort, cache, emit=None,
                  _profile=profile):
            # Default argument, not a closure, so each service keeps its own profile.
            return call(_profile, system=system, messages=messages, tools=tools,
                        model=model, effort=effort, cache=cache, emit=emit)

        serve.__doc__ = f"OpenAI-compatible endpoint at {profile.url}."
        service(f"provider:{profile.name}")(serve)


register(providers(project_root() or Path.cwd()))
