import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("t", Path(__file__).parent / "test_28_tailwind_evaluation_phase1.py")
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


def _renamed(text, pairs):
    for old, new in pairs:
        text = text.replace(old + " {", new + " {").replace(old + " img {", new + " img {")
    return text


def test_probe():
    import subprocess
    raw_videos = subprocess.run(["git", "-C", str(t.ROOT), "show", f"{t.PRE_CHANGE_SHA}:client/frontend/src/videos.css"], capture_output=True, text=True).stdout
    raw_channels = subprocess.run(["git", "-C", str(t.ROOT), "show", f"{t.PRE_CHANGE_SHA}:client/frontend/src/channels.css"], capture_output=True, text=True).stdout
    old_videos, old_channels = t._rules(raw_videos), t._rules(raw_channels)
    for key in [("", ".video-title"), ("", ".channel-meta"), ("", ".channel-avatar"), ("", ".channel-avatar img")]:
        print(key, old_videos.get(key))
    print("channels", old_channels.get(("", ".channel-meta")))
    print("media keys videos:", [k for k in old_videos if k[0]])
    print("nav pair:", old_videos.get(("", ".nav-link.active")), old_videos.get(("", ".nav-link:hover")))

    good = t._rules('@import "./base.css";\n\n' + _renamed(raw_videos, [(".video-title", ".card-title"), (".channel-meta", ".card-channel"), (".channel-avatar", ".card-avatar")]))
    print("good videos equal:", [good.get(("", n)) == old_videos[("", o)] for n, o in t.VIDEOS_RENAMES.items()],
          "old left:", t._selectors_naming(good, set(t.VIDEOS_RENAMES.values())))
    print("import-led first key:", next(iter(good)))
    both = t._rules(raw_videos + "\n.card-title { margin: 0; }")
    print("kept-old detected:", t._selectors_naming(both, set(t.VIDEOS_RENAMES.values())))
    drift = t._rules(_renamed(raw_videos, [(".video-title", ".card-title")]).replace("-webkit-line-clamp: 2", "-webkit-line-clamp: 3"))
    print("drift equal:", drift.get(("", ".card-title")) == old_videos[("", ".video-title")])
    goodc = t._rules(_renamed(raw_channels, [(".channel-meta", ".channel-domain")]))
    print("good channels equal:", goodc.get(("", ".channel-domain")) == old_channels[("", ".channel-meta")], t._selectors_naming(goodc, {".channel-meta"}))
    assert False
