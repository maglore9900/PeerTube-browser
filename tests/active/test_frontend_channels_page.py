"""A channels table row marks its instance domain with `channel-domain`, the class `channels.css` styles it with, and carries no `channel-meta`.

The channels page module (`src/pages/channels/index.ts`) runs in node on an esbuild bundle against a stubbed browser platform: a `document` holding plain recording elements for the four ids the module requires, `window.location`, and `fetch`, which answers `/api/channels` with a one-row payload and 404 for anything else. The rendered `#channels-body` is read once the load settles.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
BASE = "http://client.test"
CHANNEL = "Lofi Beats Radio"
DOMAIN = "tube.example"
CHANNEL_ROW = {"channel_id": "c1", "channel_name": "lofi_beats", "channel_url": None, "display_name": CHANNEL, "instance_domain": DOMAIN,
               "videos_count": 3, "followers_count": 12, "avatar_url": None, "health_status": None, "health_checked_at": None, "health_error": None,
               "last_error": None, "last_error_at": None, "last_error_source": None}

CHANNELS_RUNNER = """
const element = () => ({ innerHTML: "", textContent: "" });
const byId = new Map(["channels-body", "summary-counts", "summary-meta", "page-status"].map((id) => [id, element()]));
globalThis.window = { location: { origin: process.env.BASE, search: "" }, setTimeout, clearTimeout };
globalThis.document = { getElementById: (id) => byId.get(id) ?? null, querySelectorAll: () => [] };
const requested = [];
globalThis.fetch = async (input) => {
  const url = new URL(String(input), process.env.BASE);
  requested.push(url.pathname);
  if (url.pathname === "/api/channels") return new Response(process.env.PAYLOAD, { status: 200, headers: { "content-type": "application/json" } });
  return new Response("{}", { status: 404 });
};
await import(process.env.BUNDLE);
// The stubbed fetch resolves at once, so the page's load has rendered within a few macrotasks.
for (let i = 0; i < 10; i += 1) await new Promise((resolve) => setTimeout(resolve, 10));
process.stdout.write(JSON.stringify({ requested, body: byId.get("channels-body").innerHTML }) + "\\n");
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("channels_page")
    defines = [f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"]
    subprocess.run([str(ESBUILD), str(FRONTEND / "src" / "pages" / "channels" / "index.ts"), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out / 'channels.mjs'}", *defines],
                   check=True, capture_output=True)
    (out / "channels_runner.mjs").write_text(CHANNELS_RUNNER)
    return out


def test_the_channels_row_carries_channel_domain_on_its_instance_domain_and_no_channel_meta(bundle):
    proc = subprocess.run(["node", str(bundle / "channels_runner.mjs")], capture_output=True, text=True, timeout=60,
                          env={"BASE": BASE, "BUNDLE": str(bundle / "channels.mjs"), "PAYLOAD": json.dumps({"rows": [CHANNEL_ROW], "total": 1}), "PATH": os.environ.get("PATH", "")})
    assert proc.returncode == 0, proc.stderr
    page = json.loads(proc.stdout.splitlines()[-1])
    body = page["body"]

    # control: the page asked for its channels and rendered the row, so an empty or loading table cannot pass
    assert "/api/channels" in page["requested"], page["requested"]
    assert CHANNEL in body and DOMAIN in body, body
    assert re.search(r'class="channel-domain"[^>]*>\s*' + re.escape(DOMAIN) + r"\s*<", body), body
    assert "channel-meta" not in body, body
