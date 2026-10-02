import importlib.util
import traceback
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("cp21", Path(__file__).with_name("test_21_static_page_visit_logs_phase1.py"))
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)
ORIGINAL = cp._site_block()
ANCHOR = "    location / {\n"
GOOD = "".join(f"    location = {u} {{\n        try_files /dev-pages/about.html /dev-pages/about.template.html =404;\n    }}\n" for u in ("/about", "/about/", "/about.html"))
VARIANTS = {
    "good": GOOD,
    "template-first": GOOD.replace("/dev-pages/about.html /dev-pages/about.template.html", "/dev-pages/about.template.html /dev-pages/about.html"),
    "own-add_header": GOOD.replace("=404;\n", "=404;\n        add_header X-Frame-Options DENY;\n"),
    "prefix": "    location /about {\n        try_files /dev-pages/about.html /dev-pages/about.template.html =404;\n    }\n",
    "missing-slash": GOOD.replace("location = /about/ {", "location = /about-x/ {"),
}
SCEN = [(("about.html", "about.template.html"), "about.html"), (("about.html",), "about.html"), (("about.template.html",), "about.template.html"), ((), None)]


def _run(fn, *args):
    try:
        fn(*args)
        return "PASSED"
    except BaseException as exc:  # noqa: BLE001
        frames = [f for f in traceback.extract_tb(exc.__traceback__) if "phase1" in f.filename]
        return f"RAISED {type(exc).__name__} at {frames[-1].lineno if frames else '?'}"


@pytest.mark.parametrize("variant", list(VARIANTS))
def test_probe_variant(tmp_path, monkeypatch, variant) -> None:
    assert ANCHOR in ORIGINAL
    monkeypatch.setattr(cp, "_site_block", lambda: ORIGINAL.replace(ANCHOR, VARIANTS[variant] + ANCHOR))
    out = [f"mapping={_run(cp.test_about_mapping_matches_vite)}"]
    for i, (present, served) in enumerate(SCEN):
        d = tmp_path / str(i)
        d.mkdir()
        out.append(f"{present or 'neither'}={_run(cp.test_about_urls_serve_override_then_template_then_404_with_csp, d, present, served)}")
    print(f"\n== {variant}: " + " | ".join(out))
