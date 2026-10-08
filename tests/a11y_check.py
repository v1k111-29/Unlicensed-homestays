"""Static accessibility checks on rendered HTML (M10). Standard library only.

These checks need no browser: they parse the server's HTML and look for the structural
problems a screen reader or keyboard user would hit (WCAG 2.1 A/AA items that are visible in
markup). They do not replace a real browser or screen-reader test (not done; see
docs/ui-and-accessibility.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}
FOCUSABLE = {"a", "button", "input", "select", "textarea"}
CONTROLS = {"input", "select", "textarea"}
NO_LABEL_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}
LANDMARK_ROLES = {"main", "banner", "contentinfo", "navigation", "complementary", "region"}
TAMIL = re.compile(r"[஀-௿]")


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    parent: Node | None = None
    children: list[Node | str] = field(default_factory=list)

    def text(self) -> str:
        out = []
        for child in self.children:
            out.append(child if isinstance(child, str) else child.text())
        return " ".join(" ".join(out).split())

    def iter(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.iter()

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, parent=self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self.stack[-1].children.append(data)


def parse(html: str) -> Node:
    builder = _Builder()
    builder.feed(html)
    builder.close()
    return builder.root


def _name(node: Node, ids: dict[str, Node]) -> str:
    """Accessible name, approximately: aria-labelledby, aria-label, then text content."""
    if node.attrs.get("aria-labelledby"):
        return " ".join(
            ids[i].text() for i in node.attrs["aria-labelledby"].split() if i in ids
        ).strip()
    if node.attrs.get("aria-label"):
        return node.attrs["aria-label"].strip()
    if node.tag == "input" and node.attrs.get("type") in {"submit", "button"}:
        return node.attrs.get("value", "").strip()
    return node.text()


def problems(html: str, lang: str, switch: bool = True) -> list[str]:
    """Return a list of accessibility problems found in one rendered page. ``switch=False``
    for the pages Django renders without a request context (500, CSRF failure)."""
    root = parse(html)
    nodes = list(root.iter())
    found: list[str] = []

    def by_tag(tag: str) -> list[Node]:
        return [n for n in nodes if n.tag == tag]

    # Language of the page (WCAG 3.1.1).
    htmls = by_tag("html")
    if len(htmls) != 1 or htmls[0].attrs.get("lang") != lang:
        found.append(f"<html lang> is not {lang!r}")

    # Unique ids, and every id reference points at an existing element (1.3.1, 4.1.1).
    ids: dict[str, Node] = {}
    for n in nodes:
        if "id" in n.attrs:
            if n.attrs["id"] in ids:
                found.append(f"duplicate id {n.attrs['id']!r}")
            ids[n.attrs["id"]] = n
    for n in nodes:
        for attr in ("aria-labelledby", "aria-describedby", "aria-controls"):
            for ref in n.attrs.get(attr, "").split():
                if ref not in ids:
                    found.append(f"<{n.tag} {attr}={ref!r}> points at no element")
        if n.tag == "label" and n.attrs.get("for") and n.attrs["for"] not in ids:
            found.append(f"<label for={n.attrs['for']!r}> points at no element")
        href = n.attrs.get("href", "")
        if n.tag == "a" and href.startswith("#") and len(href) > 1 and href[1:] not in ids:
            found.append(f"in-page link {href!r} has no target")

    # Landmarks: one main (target of the skip link), a banner, a footer; named navs (1.3.1).
    mains = by_tag("main")
    if len(mains) != 1 or mains[0].attrs.get("id") != "main":
        found.append("page must have exactly one <main id='main'>")
    if not by_tag("header") or not by_tag("footer"):
        found.append("page needs a <header> and a <footer>")
    for nav in by_tag("nav") + by_tag("aside"):
        if not nav.attrs.get("aria-label") and not nav.attrs.get("aria-labelledby"):
            found.append(f"<{nav.tag}> without aria-label")
    navs = {nav.attrs.get("aria-label") for nav in by_tag("nav")}
    if len(navs) != len(by_tag("nav")):
        found.append("two <nav> landmarks share a label")

    # Skip link is the first focusable element (2.4.1).
    focusables = [
        n
        for n in nodes
        if n.tag in FOCUSABLE and n.attrs.get("type") != "hidden" or "tabindex" in n.attrs
    ]
    focusables = [n for n in focusables if n.attrs.get("tabindex") != "-1"]
    if not focusables or focusables[0].attrs.get("href") != "#main":
        found.append("first focusable element is not the skip link to #main")

    # No positive tabindex (2.4.3); no inline styles or fixed widths (1.4.10, brief §2).
    for n in nodes:
        tabindex = n.attrs.get("tabindex")
        if tabindex and tabindex.lstrip("-").isdigit() and int(tabindex) > 0:
            found.append(f"positive tabindex on <{n.tag}>")
        if "style" in n.attrs or ("width" in n.attrs and n.tag not in {"img", "col"}):
            found.append(f"inline style/width on <{n.tag}>")

    # Headings: one h1, no skipped levels going down (1.3.1, 2.4.6).
    levels = [int(n.tag[1]) for n in nodes if re.fullmatch(r"h[1-6]", n.tag)]
    if levels.count(1) != 1:
        found.append(f"expected one <h1>, found {levels.count(1)}")
    for before, after in zip(levels, levels[1:], strict=False):
        if after > before + 1:
            found.append(f"heading level jumps from h{before} to h{after}")
    for n in nodes:
        if re.fullmatch(r"h[1-6]", n.tag) and not n.text():
            found.append(f"empty <{n.tag}>")
    title = by_tag("title")
    if not title or not title[0].text():
        found.append("missing <title>")

    # Form controls have labels; errors are tied to their fields (1.3.1, 3.3.1, 3.3.2, 4.1.2).
    labelled_for = {n.attrs.get("for") for n in by_tag("label")}
    for n in nodes:
        if n.tag not in CONTROLS:
            continue
        if n.tag == "input" and n.attrs.get("type", "text") in NO_LABEL_INPUT_TYPES:
            continue
        wrapped = any(a.tag == "label" for a in n.ancestors())
        named = n.attrs.get("aria-label") or n.attrs.get("aria-labelledby")
        if not (wrapped or named or (n.attrs.get("id") and n.attrs["id"] in labelled_for)):
            found.append(f"<{n.tag} name={n.attrs.get('name')!r}> has no label")
        if n.attrs.get("aria-invalid") == "true" and not n.attrs.get("aria-describedby"):
            found.append(f"invalid <{n.tag} name={n.attrs.get('name')!r}> has no description")
        if n.attrs.get("type") == "radio" and not any(a.tag == "fieldset" for a in n.ancestors()):
            found.append(f"radio {n.attrs.get('name')!r} outside a <fieldset>")
    for fs in by_tag("fieldset"):
        legends = [c for c in fs.children if isinstance(c, Node) and c.tag == "legend"]
        if not legends or not legends[0].text():
            found.append("<fieldset> without a <legend>")

    # Buttons and links have names; images have alt (1.1.1, 2.4.4, 4.1.2).
    for n in nodes:
        if n.tag in {"button", "a"} and not _name(n, ids):
            found.append(f"<{n.tag}> without an accessible name")
        if n.tag == "a" and "href" not in n.attrs:
            found.append(f"<a> without href: {n.text()!r}")
        if n.tag == "img" and "alt" not in n.attrs:
            found.append("<img> without alt")
        if n.tag in {"div", "span", "tr", "td"} and "onclick" in n.attrs:
            found.append(f"clickable <{n.tag}>: use a link or button")

    # Tables: a name and header scope (1.3.1).
    for table in by_tag("table"):
        has_caption = any(c.tag == "caption" for c in table.iter() if c is not table)
        if not (has_caption or table.attrs.get("aria-label") or table.attrs.get("aria-labelledby")):
            found.append("<table> without caption or aria-label(ledby)")
    for th in by_tag("th"):
        if th.attrs.get("scope") not in {"col", "row", "colgroup", "rowgroup"}:
            found.append(f"<th> without scope: {th.text()!r}")

    # Scrollable regions are named; status is never colour alone (1.4.1, 2.1.1).
    for n in nodes:
        if n.attrs.get("role") == "region" and not _name(n, ids):
            found.append("role=region without a name")
        if "badge" in n.classes() and not n.text():
            found.append("status badge without text")
        if n.attrs.get("role") == "alert" and not n.text():
            found.append("empty role=alert")

    # Language switch on every page that has a request context (T2).
    navs_switch = [n for n in by_tag("nav") if "lang-switch" in n.classes()]
    if switch and not navs_switch:
        found.append("no language switch")
    elif switch:
        links = [a for a in navs_switch[0].iter() if a.tag == "a"]
        if sorted(a.attrs.get("lang") for a in links) != ["en", "ta"]:
            found.append("language switch must link English and Tamil, each with lang")
        current = [a for a in links if a.attrs.get("aria-current") == "true"]
        if len(current) != 1 or current[0].attrs.get("lang") != lang:
            found.append("language switch does not mark the current language")

    # Tamil pages: chrome is in Tamil (title and skip link).
    if lang == "ta":
        skip = focusables[0].text() if focusables else ""
        if not TAMIL.search(skip) or not (title and TAMIL.search(title[0].text())):
            found.append("Tamil page has an English title or skip link")
    return found


def visible_text(html: str) -> str:
    root = parse(html)
    out = []
    for n in root.iter():
        if n.tag in {"script", "style"}:
            continue
        out.extend(c for c in n.children if isinstance(c, str))
    return " ".join(" ".join(out).split())
