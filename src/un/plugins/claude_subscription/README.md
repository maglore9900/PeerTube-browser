# claude_subscription

Reach Anthropic through a **Claude subscription** instead of a metered API key. un's own
agent loop stays in charge; this plugin supplies the OAuth issuer `un login` needs, and
shapes each outgoing request so the subscription endpoint accepts it.

An **aftermarket** plugin: a separate distribution that declares the `un.plugins`
entry-point group. Installing it is not enough to run it — un loads it only once
`.un/config.toml` names it in `enable_plugin`.

## Requirements

A Claude subscription. This plugin authenticates as the Claude Code client, so the plan
that covers Claude Code is the plan that covers this. It cannot be used with an API key,
and it is not a way to get one.

## Install

From the root of the project that should get the plugin:

```sh
sh /path/to/claude_subscription/install.sh
```

Two steps, both delegated: `pixi add --pypi <this directory>` to install the
distribution, then `un plugins enable claude_subscription` to write the `enable_plugin`
entry. The script aborts before enabling if the install fails, because a name in
`enable_plugin` that reaches nothing stops un starting at all.

To do it by hand instead, run those two commands.

## Configure

Add a provider entry naming this plugin's adaptor:

```toml
[providers.claude]
adaptor = "claude-code"
model   = "claude-sonnet-5"
main    = true
```

un runs its own agent loop — the tools, rules and permissions un already
has. `adaptor = "claude-code"` is what this plugin claims; nothing else answers to it.
Drop `main = true` if another provider is your default and select this one per run with
`--provider claude`.

## Log in

```sh
un login
```

It prints a URL to approve in a browser, then asks for the code the page shows back. The
credential is written to `.un/oauth/anthropic.credentials.json`, mode 0600, and is refused
to the model's own file tools by two independent permission rules. Running `un login`
again is a no-op while the credential is still good, so it is safe to repeat.

Then:

```sh
un chat --provider claude "..."
```

## What it does to each request

Six adaptations, so the request matches what the Claude Code client sends:

1. **Identity headers** — `user-agent`, `x-app` and `anthropic-client-platform`, and
   nothing else. The SDK generates `x-stainless-*` itself, and `anthropic-beta` is
   rendered from `betas=` on the request.
2. **A billing header as `system[0]`**, carrying a fingerprint derived from the first user
   message.
3. **The Claude Code identity marker as `system[1]`**, with un's own system prompt at
   `[2]`.
4. **`cch`**, sent as the placeholder `cch=00000` the installed client emits verbatim.
   Nothing is computed over the serialized body and no custom httpx transport is
   installed.
5. **`metadata.user_id`** — a `{device_id, session_id}` envelope. The device is stable per
   machine, the session per `un` invocation.
6. **`max_tokens` capped at 64000**, and one-hour retention on the cache breakpoint.

## When it breaks

**Every constant above is pinned to one Claude Code version** — currently 2.1.251. There
is no version negotiation and no way to detect drift: when Anthropic moves the client, the
endpoint starts refusing requests with a 4xx and nothing local can explain why.

**So a sudden 4xx means the pins have drifted, not that your credential is bad.** The fix
is to re-read the reference client and update the constants at the top of
`claude_subscription.py`. A credential problem looks different — `un login` names it, and
an expired token refreshes itself on read.

## What it is not

This is a proof of concept for OAuth-backed providers in un, and the template the next one
should copy. It reverse-engineers a client it is not part of, and that is a maintenance
burden it carries deliberately rather than a stable integration.
