"""HTML cleaning for skatepro.es product descriptions.

Reused from the crawlee/javaestate sibling package in this experiment: the
whitelist, emptiness rules and whitespace handling are unchanged.  The comment
below is the original one, kept because the behaviour is still the same.

The cleaner is deliberately small and whitelist based.  It is not a general
sanitiser: the output is only consumed by the CSV export and by humans, never
rendered in a browser by this project.
"""

from __future__ import annotations

import re
from html import escape

from lxml import html

# Tags kept in the cleaned description.  Everything else is either dropped
# together with its subtree (script/style/...) or unwrapped (a/span/...).
ALLOWED_TAGS = {
    "p",
    "br",
    "ul",
    "ol",
    "li",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "dl",
    "dt",
    "dd",
    "blockquote",
    "div",
}

DROP_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "object",
    "embed",
    "svg",
    "img",
    "video",
    "audio",
    "source",
    "form",
    "input",
    "button",
    "select",
    "textarea",
    "label",
    "canvas",
    "link",
    "meta",
}

# Containers that are kept even when they have no direct text, because their
# children carry the content (lists, tables, etc.).
STRUCTURAL_TAGS = {
    "ul",
    "ol",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "dl",
    "div",
    "blockquote",
}


def _normalise_text(value: str | None) -> str:
    if not value:
        return ""
    # HTML collapses runs of whitespace.  Keep a single space so words that
    # were separated by a newline in the source do not get glued together.
    return re.sub(r"\s+", " ", value).strip()


def _is_empty(element: html.HtmlElement) -> bool:
    if element.tag == "div":
        # skatepro marks up specifications as nested ``div`` rows whose value
        # cell can be empty; an emptied row carries nothing and is removed.
        return not (element.text_content() or "").strip()
    if element.tag in STRUCTURAL_TAGS:
        return False
    if element.tag == "br":
        return False
    if (element.text or "").strip():
        return False
    if len(element):
        return False
    return True


def clean_html_fragment(fragment: str) -> str:
    """Return a whitelisted, attribute-free HTML fragment.

    Links are unwrapped and keep their text.  Images, scripts, styles, forms
    and other non-text elements are removed.  The result is suitable for the
    ``description_html`` column; callers must still set ``description_format``
    to ``html``.
    """

    if not fragment or not fragment.strip():
        return ""

    try:
        root = html.fragment_fromstring(fragment, create_parent="div")
    except (ValueError, TypeError):
        # A malformed fragment is treated as text, not silently dropped.
        return f"<p>{escape(fragment.strip())}</p>"

    # Iterate over a snapshot: drop_tree mutates the tree.
    for element in list(root.iter()):
        if element is root:
            continue
        tag = element.tag.lower() if isinstance(element.tag, str) else ""
        if tag in DROP_TAGS:
            element.drop_tree()
        elif tag == "a":
            element.drop_tag()
        elif tag not in ALLOWED_TAGS:
            element.drop_tag()
        else:
            for attribute in list(element.attrib):
                del element.attrib[attribute]

    # Normalise text and remove empty containers.  Work bottom-up so an empty
    # child does not leave an empty parent behind.
    for element in reversed(list(root.iter())):
        if element is root:
            continue
        element.text = _normalise_text(element.text) or None
        element.tail = _normalise_text(element.tail) or None
        if _is_empty(element):
            element.drop_tree()

    # Drop empty leading/trailing paragraphs produced by editor whitespace.
    children = [child for child in root if isinstance(child.tag, str)]
    while children and children[0].tag in {"p", "div", "br"} and not (
        children[0].text_content().strip()
    ):
        root.remove(children.pop(0))
    while children and children[-1].tag in {"p", "div", "br"} and not (
        children[-1].text_content().strip()
    ):
        root.remove(children.pop())

    if not children:
        return ""

    output = "".join(
        html.tostring(child, encoding="unicode", method="html") for child in root
    ).strip()
    return output


def html_to_text(fragment: str) -> str:
    """Return a plain-text representation for diagnostics and fallbacks."""

    if not fragment:
        return ""
    try:
        root = html.fragment_fromstring(fragment, create_parent="div")
    except (ValueError, TypeError):
        return _normalise_text(fragment)
    for element in list(root.iter()):
        if element is root:
            continue
        if not isinstance(element.tag, str):
            continue
        if element.tag.lower() in DROP_TAGS:
            element.drop_tree()
    return _normalise_text(root.text_content())
