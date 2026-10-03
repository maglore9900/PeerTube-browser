"""The client reads a legacy `hot` feed mode as `trending`, from `?mode=hot` and from a stored `{"mode": "hot"}`, and its `FEED_MODES` are the Engine's, with `trending` and without `hot`.

- `?mode=hot` gives `["trending"]` with nothing stored and over a stored `recent`; a stored `{"mode": "hot"}` gives `["trending"]` to a bare search; persisting what `?mode=hot` resolves to gives `["trending"]` to the next bare search.
- Only `hot` is aliased: beside `?mode=hot` and a stored `{"mode": "hot"}` giving `["trending"]`, `?mode=bogus`, a stored `{"mode": "bogus"}` and the bare JSON string `"hot"` stored each still give `["recommendations"]`.
- The Engine's `FEED_MODES` name `trending` and not `hot`; the client's `FEED_MODES` hold the same modes, none repeated and no `hot`.
- For each Engine mode, `?mode=<mode>` and a stored `{"mode": <mode>}` each give `[<mode>]`.

The cases run through the harness in `tests/active/test_frontend_feed_params.py`, loaded by path: `feed-params.ts` and `videos.ts` bundled with esbuild, run in node over an in-memory `localStorage`, reporting the `mode` entries of the Engine URL `buildSimilarUrl(q, resolveFeedParams(search))` builds. The Engine's modes are read from `similar.py` by AST there. The Trending button in the HTML is markup and is covered by `test_frontend_dist.py` after the dist rebuild.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("feed_params_harness_trending_phase4", ROOT / "tests" / "active" / "test_frontend_feed_params.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

ENGINE_FEED_MODES = harness.ENGINE_FEED_MODES


def test_a_legacy_hot_from_the_url_or_storage_requests_trending():
    assert harness.VIDEOS is not None, harness.VIDEOS_ERROR  # control: videos.ts bundles
    got = harness._modes([
        {"search": "?mode=hot"},
        {"search": "?mode=hot", "stored": harness._stored("recent")},
        {"search": "", "stored": harness._stored("hot")},
        {"search": "", "persist": "?mode=hot"},
    ])
    # The previous client gives ["hot"], which the Engine answers 400; a rename with no alias gives ["recommendations"].
    assert got[0] == ["trending"], got[0]  # C1
    # An alias that falls through to storage gives ["recent"].
    assert got[1] == ["trending"], got[1]  # C1
    # An alias applied only to the URL gives ["recommendations"] for the stored object.
    assert got[2] == ["trending"], got[2]  # C1
    # What a ?mode=hot visit persists is read back as a mode the Engine accepts, not ["hot"].
    assert got[3] == ["trending"], got[3]  # C1


def test_only_hot_is_read_as_trending():
    assert harness.VIDEOS is not None, harness.VIDEOS_ERROR  # control: videos.ts bundles
    got = harness._modes([
        {"search": "?mode=hot"},
        {"search": "", "stored": harness._stored("hot")},
        {"search": "?mode=bogus"},
        {"search": "", "stored": harness._stored("bogus")},
        {"search": "", "stored": json.dumps("hot")},
    ])
    # The alias fires on both paths here, so a recommendations below is the alias declining, not an alias that does not exist or storage never read.
    assert got[0] == ["trending"], got[0]  # C1
    assert got[1] == ["trending"], got[1]  # C1
    # An alias catching every unknown value gives ["trending"]; a raw pass-through gives ["bogus"].
    assert got[2] == ["recommendations"], got[2]  # C1
    assert got[3] == ["recommendations"], got[3]  # C1
    # Storage holds an object, so a bare JSON string "hot" is not a stored choice; an alias applied before the object check gives ["trending"].
    assert got[4] == ["recommendations"], got[4]  # C1


def test_the_client_s_feed_modes_are_the_engine_s_with_trending_and_not_hot():
    assert harness.VIDEOS is not None, harness.VIDEOS_ERROR  # control: videos.ts bundles
    # The Engine's FEED_MODES is read from similar.py by AST: the client bundle cannot reach the Engine, so its tuple's value is the only observable at this seam.
    assert "trending" in ENGINE_FEED_MODES and "hot" not in ENGINE_FEED_MODES, ENGINE_FEED_MODES  # C2
    client = harness._run([])["feedModes"]
    assert client is not None, harness.FEED_PARAMS_ERROR  # control: feed-params.ts bundles
    # The previous client lists hot in place of trending; one keeping hot beside trending has six.
    assert "hot" not in client, client  # C2
    assert sorted(client) == sorted(ENGINE_FEED_MODES) and len(set(client)) == len(client), (client, ENGINE_FEED_MODES)  # C2


@pytest.mark.parametrize("mode", ENGINE_FEED_MODES)
def test_every_engine_mode_round_trips_through_the_url_and_storage(mode):
    assert harness.VIDEOS is not None, harness.VIDEOS_ERROR  # control: videos.ts bundles
    got = harness._modes([{"search": f"?mode={mode}"}, {"search": "", "stored": harness._stored(mode)}])
    # A client without the mode maps it to ["recommendations"]; for recommendations itself this reads the same either way, so trending is the case that bites.
    assert got[0] == [mode], (mode, got[0])  # C2
    assert got[1] == [mode], (mode, got[1])  # C2
