"""The shared stylesheet defines the design tokens, and every contrast pair listed in
docs/ui-design-brief.md meets WCAG 2.1 AA (computed here, not copied from the brief)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "src" / "static" / "css" / "app.css"
BRIEF = ROOT / "docs" / "ui-design-brief.md"

REQUIRED_TOKENS = [
    "--color-text",
    "--color-text-muted",
    "--color-bg",
    "--color-surface",
    "--color-border-strong",
    "--color-accent",
    "--color-on-accent",
    "--color-focus",
    "--color-danger",
    "--color-warning",
    "--color-success",
    "--color-neutral",
    "--font-sans",
    "--font-tamil",
    "--text-base",
    "--space-4",
    "--radius",
    "--target",
]
# Minimum ratios: normal text 4.5:1 (SC 1.4.3); UI components and focus 3:1 (SC 1.4.11).
MINIMUM = {"text": 4.5, "ui": 3.0}
PAIR_ROW = re.compile(r"^\|\s*`(--[\w-]+)`\s*\|\s*`(--[\w-]+)`\s*\|\s*(text|ui)\s*\|", re.M)


def _root_tokens() -> dict[str, str]:
    css = CSS.read_text(encoding="utf-8")
    root = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    assert root, "app.css has no :root block"
    return {m[1]: m[2].strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", root[1])}


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    assert len(h) == 6, f"expected #rrggbb, got {hex_colour}"
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _pairs() -> list[tuple[str, str, str]]:
    return PAIR_ROW.findall(BRIEF.read_text(encoding="utf-8"))


def test_contrast_formula_known_values() -> None:
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


def test_stylesheet_defines_tokens() -> None:
    tokens = _root_tokens()
    missing = [t for t in REQUIRED_TOKENS if t not in tokens]
    assert not missing, f"app.css is missing tokens: {missing}"


def test_stylesheet_is_self_contained() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert "@import" not in css
    assert not re.search(r"url\(\s*['\"]?(https?:)?//", css), "no external fonts or assets"


def test_base_template_uses_app_css() -> None:
    base = (ROOT / "src" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "css/app.css" in base


def test_brief_lists_contrast_pairs() -> None:
    assert len(_pairs()) >= 15


@pytest.mark.parametrize("fg,bg,kind", _pairs())
def test_contrast_pair_meets_aa(fg: str, bg: str, kind: str) -> None:
    tokens = _root_tokens()
    ratio = contrast(tokens[fg], tokens[bg])
    assert ratio >= MINIMUM[kind], f"{fg} on {bg}: {ratio:.2f} < {MINIMUM[kind]}"
