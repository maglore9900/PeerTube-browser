"""Probe: the phase 2 checkpoint against the current block and against the plan's draft spliced in."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.tmp import test_21_static_page_visit_logs_phase2 as checkpoint

FORMAT = "log_format peertube_browser_pages 'page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method status=$status rt=$request_time request_id=$request_id uri=\"$request_uri\" x_request_id=$http_x_request_id ua=\"$http_user_agent\"';\n"
GOOD = "set $static_page about; try_files /dev-pages/about.html /dev-pages/about.template.html =404; access_log /var/log/nginx/peertube-browser.access.log peertube_browser; access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;"
WRONG = {
    "good": (FORMAT, GOOD),
    "pages-only": (FORMAT, GOOD.replace("access_log /var/log/nginx/peertube-browser.access.log peertube_browser;", "")),
    "uri-var": (FORMAT.replace("$request_uri", "$uri"), GOOD),
    "server-level": (FORMAT.replace("server {", ""), GOOD),
}
ORIGINAL = checkpoint._site_block


@pytest.mark.parametrize("variant", ["current", *WRONG])
@pytest.mark.parametrize("which", ["about", "other"])
def test_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str, which: str) -> None:
    def block() -> str:
        text = ORIGINAL()
        if variant == "current":
            return text
        fmt, body = WRONG[variant]
        text = fmt + text.replace("try_files /dev-pages/about.html /dev-pages/about.template.html =404;", body)
        if variant == "server-level":
            text = text.replace("access_log /var/log/nginx/peertube-browser.access.log peertube_browser;\n\n", "access_log /var/log/nginx/peertube-browser.access.log peertube_browser;\n    access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;\n\n", 1)
        return text

    monkeypatch.setattr(checkpoint, "_site_block", block)
    if which == "about":
        for present, code in ((("about.template.html",), 200), ((), 404)):
            checkpoint.test_each_about_request_writes_one_pages_line_and_one_main_line_with_same_request_id(tmp_path / str(code), present, code)
    else:
        checkpoint.test_other_routes_write_no_pages_line(tmp_path)
