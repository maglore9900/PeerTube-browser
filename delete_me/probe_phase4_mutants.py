from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "client" / "frontend" / "src" / "data" / "feed-params.ts").read_text()
spec = importlib.util.spec_from_file_location("phase4_ckpt_probe", ROOT / "tests" / "tmp" / "test_45_trending_from_source_instances_phase4.py")
ck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ck)

RENAMED = SRC.replace('"recommendations", "hot", "recent"', '"recommendations", "trending", "recent"')
OLD_PARSE = "return FEED_MODES.find((mode) => mode === raw) ?? \"recommendations\";"
VARIANTS = {
    "fixed": RENAMED.replace(OLD_PARSE, "const wanted = raw === \"hot\" ? \"trending\" : raw;\n  return FEED_MODES.find((mode) => mode === wanted) ?? \"recommendations\";"),
    "no-alias": RENAMED,
    "catch-all": RENAMED.replace(OLD_PARSE, "return FEED_MODES.find((mode) => mode === raw) ?? (raw ? \"trending\" : \"recommendations\");"),
    "url-only": RENAMED.replace("if (fromUrl) return { mode: parseFeedMode(fromUrl) };", "if (fromUrl) return { mode: parseFeedMode(fromUrl === \"hot\" ? \"trending\" : fromUrl) };"),
    "both-modes": SRC.replace('"recommendations", "hot", "recent"', '"recommendations", "hot", "trending", "recent"').replace(OLD_PARSE, "const wanted = raw === \"hot\" ? \"trending\" : raw;\n  return FEED_MODES.find((mode) => mode === wanted) ?? \"recommendations\";"),
    "bare-string": RENAMED.replace(OLD_PARSE, "const wanted = raw === \"hot\" ? \"trending\" : raw;\n  return FEED_MODES.find((mode) => mode === wanted) ?? \"recommendations\";").replace("if (parsed && typeof parsed === \"object\" && !Array.isArray(parsed)) {", "if (parsed === \"hot\") return { mode: \"trending\" };\n    if (parsed && typeof parsed === \"object\" && !Array.isArray(parsed)) {"),
}
TESTS = ["test_a_legacy_hot_from_the_url_or_storage_requests_trending", "test_only_hot_is_read_as_trending", "test_the_client_s_feed_modes_are_the_engine_s_with_trending_and_not_hot"]


@pytest.mark.parametrize("variant", list(VARIANTS))
def test_variant(variant):
    src = VARIANTS[variant]
    assert src != SRC
    d = ck.harness._tempdir()
    (d / "feed-params.ts").write_text(src)
    bundle, err = ck.harness._bundle(f'export {{ FEED_MODES, resolveFeedParams, persistFeedParams }} from "{d}/feed-params.ts";\n')
    assert bundle is not None, err
    ck.harness.FEED_PARAMS = bundle
    outcome = {}
    for name in TESTS:
        try:
            getattr(ck, name)()
            outcome[name] = "pass"
        except AssertionError as e:
            outcome[name] = "FAIL " + str(e).splitlines()[0][:80]
    for mode in ck.ENGINE_FEED_MODES:
        try:
            ck.test_every_engine_mode_round_trips_through_the_url_and_storage(mode)
            outcome[f"roundtrip[{mode}]"] = "pass"
        except AssertionError as e:
            outcome[f"roundtrip[{mode}]"] = "FAIL " + str(e).splitlines()[0][:80]
    print("\nVARIANT", variant)
    for k, v in outcome.items():
        print("  ", k, "->", v)
    assert False
