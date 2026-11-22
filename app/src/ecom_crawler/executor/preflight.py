"""Static rule checks that do not need a network request.

The host used to detect an invalid selector only while extracting a real product
page.  ``lxml.cssselect`` accepts some selectors in its parser but fails later
when translating them to XPath (for example ``:not(:first-of-type)``), and the
bounded validation reports only ``plan_error`` for every page.  Compiling every
selector before the fetch makes that class of failure explicit and lets the
build agent repair it without spending the request budget.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lxml.cssselect import CSSSelector

# ``wait_selector`` is interpreted by Playwright, which supports a wider
# selector syntax than lxml; it must not be checked with the static extractor.
SKIP_SELECTOR_KEYS = {"wait_selector", "wait_selector_state"}


def iter_selectors(
    value: Any, path: str = ""
) -> Iterator[tuple[str, str]]:
    """Yield ``(path, selector)`` for every lxml-oriented selector in a rule."""
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            next_path = f"{path}.{key_text}" if path else key_text
            if (
                isinstance(item, str)
                and item.strip()
                and key_text not in SKIP_SELECTOR_KEYS
                and (key_text == "selector" or key_text.endswith("_selector"))
            ):
                yield next_path, item
                continue
            yield from iter_selectors(item, next_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_selectors(item, f"{path}[{index}]")


def check_rule_selectors(rule: dict[str, Any]) -> list[dict[str, str]]:
    """Return every selector that lxml/cssselect cannot compile."""
    errors: list[dict[str, str]] = []
    for path, selector in iter_selectors(rule):
        try:
            CSSSelector(selector)
        except Exception as exc:  # noqa: BLE001 - cssselect/lxml error boundary
            errors.append(
                {
                    "path": path,
                    "selector": selector,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return errors


def format_selector_errors(
    errors: list[dict[str, str]], *, limit: int = 5
) -> str:
    """Format selector errors for a build record and a repair prompt."""
    parts = [
        f"{item.get('path') or 'selector'} = {item.get('selector')!r} "
        f"({item.get('error')})"
        for item in errors[:limit]
    ]
    suffix = f"; {len(errors) - limit} more" if len(errors) > limit else ""
    return "invalid CSS selector(s): " + "; ".join(parts) + suffix
