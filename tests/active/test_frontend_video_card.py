"""The feed card names its title, channel and avatar with the `card-*` classes `videos.css` styles, never the video page's names.

`renderVideoCard` runs in node on an esbuild bundle of `src/components/video-card.ts`, on a row with a channel avatar and on one without. Its HTML holds `class="card-title"` on the title, `class="card-channel"` and `class="card-avatar"`, with the avatar image inside the avatar element, and none of `video-title`, `channel-meta` or `channel-avatar`, which belong to the video page's heading and would collide once a card renders there.
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
TITLE = "Fixture card title"
CHANNEL = "Lofi Beats Radio"
DOMAIN = "tube.example"
AVATAR = "https://tube.example/avatar.png"
CARD_ROWS = [
    {"video_uuid": "uuid-1", "instance_domain": DOMAIN, "title": TITLE, "channel_name": "lofi_beats", "channel_display_name": CHANNEL, "channel_avatar_url": AVATAR},
    # no avatar: the card renders initials instead of an <img> inside the avatar element
    {"video_uuid": "uuid-2", "instance_domain": DOMAIN, "title": TITLE, "channel_name": "lofi_beats", "channel_display_name": CHANNEL},
]

CARD_RUNNER = """
const m = await import(process.env.BUNDLE);
process.stdout.write(JSON.stringify({ cards: JSON.parse(process.env.ROWS).map((row) => m.renderVideoCard(row)) }) + "\\n");
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("video_card")
    defines = [f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}", "--define:import.meta.env.DEV=false"]
    subprocess.run([str(ESBUILD), str(FRONTEND / "src" / "components" / "video-card.ts"), "--bundle", "--format=esm", "--platform=node", "--loader:.css=empty", f"--outfile={out / 'card.mjs'}", *defines],
                   check=True, capture_output=True)
    (out / "card_runner.mjs").write_text(CARD_RUNNER)
    return out


def test_the_feed_card_with_or_without_an_avatar_carries_card_title_card_channel_and_card_avatar_and_none_of_the_video_page_names(bundle):
    proc = subprocess.run(["node", str(bundle / "card_runner.mjs")], capture_output=True, text=True, timeout=60,
                          env={"BUNDLE": str(bundle / "card.mjs"), "ROWS": json.dumps(CARD_ROWS), "PATH": os.environ.get("PATH", "")})
    assert proc.returncode == 0, proc.stderr
    cards = json.loads(proc.stdout.splitlines()[-1])["cards"]

    assert len(cards) == 2, cards
    for card in cards:
        # control: the card rendered the row, so the absences below are read from real markup
        assert TITLE in card and CHANNEL in card, card
        assert re.search(r'class="card-title"[^>]*>\s*' + re.escape(TITLE), card), card
        assert 'class="card-channel"' in card, card
        assert 'class="card-avatar"' in card, card
        assert "video-title" not in card, card
        assert "channel-meta" not in card, card
        assert "channel-avatar" not in card, card
    # the avatar image still sits inside the avatar element, so `.card-avatar img` reaches it
    assert re.search(r'class="card-avatar"[^>]*>\s*<img src="' + re.escape(AVATAR) + '"', cards[0]), cards[0]
