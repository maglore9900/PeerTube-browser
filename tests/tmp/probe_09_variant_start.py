import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_09_similars_diversity_phase1 import NPROBE_PREFIX, UPNEXT_PREFIX, _messages, _start_variant, _tokens, engine  # noqa: E402,F401


def test_probe(engine, tmp_path):
    print("session upnext", _messages(engine.db_path, UPNEXT_PREFIX))
    print("session nprobe", _messages(engine.db_path, NPROBE_PREFIX))
    print("tokens of sample", _tokens("[similar-server] upnext_config SIMILAR_VIDEO_MIN_SCORE=0.36 SIMILAR_VIDEO_TOP_K=301"))
    log_path = tmp_path / "variant_engine.log"
    _start_variant(log_path)
    print("variant nprobe split", [m.split()[1] for m in _messages(log_path, NPROBE_PREFIX)])
    print("variant upnext", _messages(log_path, UPNEXT_PREFIX))
    assert False, "probe"
