"""Retired from `tests/active/test_frontend_feed_params.py` in build 55-54-follow-channels-and-accounts (plan 55), step 8.

Retired whole: `test_the_client_s_feed_modes_are_the_engine_s_with_trending_and_not_hot`.

It conflicts with that build's confirmed requirement AC5: `following` joins the Engine's `FEED_MODES` (Phase 1) and the frontend's (Phase 4), so the Engine has six modes. The function's control `assert len(ENGINE_FEED_MODES) == 5` fails before its client/Engine equality is reached (step 8 suite comparison: `assert 6 == 5`, with `['recommendations', 'trending', 'recent', 'random', 'popular', 'following']`).

Retired whole and not replaced, by operator decision. The function's other assertions, that the Engine names `trending` and not `hot` and that the client's `FEED_MODES` equals the Engine's with nothing repeated, go with it. What stays active elsewhere: every Engine mode, `following` included, is resolved and sent by the client in this file's parametrised cases (`test_the_url_mode_beats_the_stored_mode_and_the_legacy_random_flag`, `test_with_no_url_mode_the_stored_mode_is_sent_and_an_empty_mode_falls_through_to_it`, `test_a_persisted_mode_is_what_a_bare_resolve_sends_next` and the two non-default ones), so a client short of a mode still fails there. A client with an extra mode the Engine lacks is no longer caught at this seam. The Engine refusing `mode=hot` stays in `tests/active/test_similar.py::test_an_unseeded_request_with_a_mode_outside_feed_modes_is_answered_400_naming_them[hot]`, and the client's legacy `hot` alias stays in `test_a_legacy_hot_from_the_url_or_a_stored_mode_object_requests_trending_and_a_bare_hot_string_does_not`.

The original code of the retired function follows unchanged, as an excerpt: lines 146-153 of the file as it stood. The helpers it calls (`VIDEOS`, `VIDEOS_ERROR`, `ENGINE_FEED_MODES`, `FEED_PARAMS_ERROR`, `_run`) stay in the active file.
"""
# --- excerpt: lines 146-153 ---

def test_the_client_s_feed_modes_are_the_engine_s_with_trending_and_not_hot():
    assert VIDEOS is not None, VIDEOS_ERROR  # control: videos.ts bundles
    assert len(ENGINE_FEED_MODES) == 5, ENGINE_FEED_MODES  # control: the Engine's five modes (recommendations, trending, recent, random, popular)
    # The Engine's FEED_MODES is read from similar.py by AST: the client bundle cannot reach the Engine, so its tuple's value is the only observable at this seam. With trending and hot swapped back, the equality below still holds.
    assert "trending" in ENGINE_FEED_MODES and "hot" not in ENGINE_FEED_MODES, ENGINE_FEED_MODES
    client = _run([])["feedModes"]
    # A client list short of a mode maps that mode to recommendations; one with an extra mode sends it to an Engine that answers 400.
    assert client is not None and sorted(client) == sorted(ENGINE_FEED_MODES) and len(set(client)) == len(client), (client, ENGINE_FEED_MODES, FEED_PARAMS_ERROR)
