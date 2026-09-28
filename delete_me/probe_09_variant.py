import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ROOT  # noqa: E402

SERVER_CONFIG = ROOT / "engine" / "server" / "api" / "server_config.py"


def _load(name, source):
    spec = importlib.util.spec_from_file_location(name, SERVER_CONFIG)
    module = importlib.util.module_from_spec(spec)
    exec(compile(source, str(SERVER_CONFIG), "exec"), module.__dict__)
    return module


def test_probe():
    source = SERVER_CONFIG.read_text()
    print("count", source.count('"batch_size": 48,'))
    base = _load("a", source)
    variant = _load("b", source.replace('"batch_size": 48,', '"batch_size": 64,', 1))
    print("base", base.BATCH_SIZE, "variant", variant.BATCH_SIZE, "guest_home", variant.RECOMMENDATION_PIPELINE["profiles"]["guest_home"]["batch_size"], "home", variant.RECOMMENDATION_PIPELINE["profiles"]["home"]["batch_size"])
    message = "[similar-server] upnext_config SIMILAR_VIDEO_TOP_K=300 SIMILAR_VIDEO_MIN_SCORE=0.35"
    print("tokens", sorted(tuple(t.split("=", 1)) for t in message[len("[similar-server] upnext_config"):].split() if "=" in t))
    assert False, "probe"
