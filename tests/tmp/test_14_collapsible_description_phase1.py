"""The markup video-page.html ships for the collapsible description: a hidden native
`#description-toggle` button follows `#video-description` inside `.player-info`.

- `#description-toggle` is unique, the element directly after `#video-description`, and both sit in
  `.player-info`; it is a `<button type="button">` with classes `ghost-button` and
  `description-toggle`, `aria-controls="video-description"`, `aria-expanded="false"` and `hidden`.
- `#video-description` still carries `video-description` and now also `description-collapsed`.

Not asserted: that the collapsed description renders exactly four whole lines. No layout engine
reaches this suite; that stays the maintainer's browser check.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / "client" / "frontend" / "video-page.html"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Node:
    def __init__(self, tag: str, attrs: dict, parent: _Node | None):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = _Node("#root", {}, None)
        self._open = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self._open)
        self._open.children.append(node)
        if tag not in VOID:
            self._open = node

    def handle_startendtag(self, tag, attrs):
        self._open.children.append(_Node(tag, dict(attrs), self._open))

    def handle_endtag(self, tag):
        node = self._open
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self._open = node.parent


def _by_id(root: _Node, element_id: str) -> list[_Node]:
    return [n for n in root.walk() if n.attrs.get("id") == element_id]


def test_video_page_ships_a_hidden_ghost_button_toggle_right_after_the_collapsed_description():
    tree = _Tree()
    tree.feed(PAGE.read_text())
    descriptions = _by_id(tree.root, "video-description")
    toggles = _by_id(tree.root, "description-toggle")

    assert len(descriptions) == 1  # control: the description the toggle attaches to is still there
    assert len(toggles) == 1, [t.attrs for t in toggles]  # C2
    description, toggle = descriptions[0], toggles[0]
    siblings = description.parent.children
    position = next(i for i, n in enumerate(siblings) if n is description)

    assert "player-info" in description.parent.classes()  # C2
    assert siblings[position + 1:position + 2] == [toggle], [(n.tag, n.attrs) for n in siblings[position + 1:]]  # C2: directly after, same parent
    assert toggle.tag == "button"  # C2: native button, not a div or link
    assert toggle.attrs.get("type") == "button"  # C2: not the default submit
    assert {"ghost-button", "description-toggle"} <= toggle.classes(), toggle.classes()  # C2
    assert toggle.attrs.get("aria-controls") == "video-description"  # C2
    assert toggle.attrs.get("aria-expanded") == "false"  # C2
    assert "hidden" in toggle.attrs  # C2
    assert {"video-description", "description-collapsed"} <= description.classes(), description.classes()  # C1 markup precondition only; the four-line clip itself is unasserted
