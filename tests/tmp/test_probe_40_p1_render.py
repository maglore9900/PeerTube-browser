from tests.tmp.test_40_search_card_actions_phase1 import _buttons, _render


def test_probe(tmp_path):
    for name, html in _render(tmp_path).items():
        buttons = _buttons(html)
        print("PROBE", name, {action: [b.get("aria-pressed") for b in found] for action, found in buttons.items()})
    assert False
