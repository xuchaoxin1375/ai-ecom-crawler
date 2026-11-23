from __future__ import annotations

import json
import unittest

from ecom_crawler.executor.extract import HtmlPage, extract_product


def _page(offers: list[float]) -> HtmlPage:
    payload = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Example Pack",
        "image": "https://example.test/pack.jpg",
        "offers": {"priceCurrency": "USD"},
        "hasVariant": [{"offers": {"price": price}} for price in offers],
    }
    body = (
        "<html><head><script type='application/ld+json'>"
        + json.dumps(payload)
        + "</script></head><body></body></html>"
    )
    return HtmlPage(body, "https://example.test/products/pack")


class JsonLdTakeTests(unittest.TestCase):
    def _plan(self, take: str) -> dict:
        return {
            "site": {"locale": "en-US"},
            "extract": {
                "fields": {
                    "name": {
                        "fallbacks": [
                            {"type": "json_ld", "path": "name", "label": "name"}
                        ]
                    },
                    "price.amount": {
                        "fallbacks": [
                            {
                                "type": "json_ld",
                                "path": "hasVariant.offers.price",
                                "label": "first_variant",
                                "take": take,
                            }
                        ]
                    },
                    "price.currency": {
                        "fallbacks": [
                            {
                                "type": "json_ld",
                                "path": "offers.priceCurrency",
                                "label": "currency",
                            }
                        ]
                    },
                    "primary_image_url": {
                        "fallbacks": [
                            {
                                "type": "json_ld",
                                "path": "image",
                                "label": "image",
                            }
                        ]
                    },
                }
            },
        }

    def test_first_positive_skips_zero_and_keeps_order(self) -> None:
        product = extract_product(_page([0, 25, 19]), self._plan("first_positive"))
        self.assertEqual(product.values["price.amount"], 25)

    def test_min_positive_keeps_existing_minimum_behavior(self) -> None:
        product = extract_product(_page([0, 25, 19]), self._plan("min_positive"))
        self.assertEqual(product.values["price.amount"], 19)


class ComposeDescriptionTests(unittest.TestCase):
    HTML = """
    <html><head>
      <meta itemprop="description" content="100% coton">
    </head><body>
      <div id="tabs-1">
        <p>Soft cotton fabric for dresses and skirts.</p>
        <span class="promo">REDUCTION 20</span>
      </div>
      <ul class="feature-list">
        <li><span>Compositions: </span>80% coton 20% viscose</li>
        <li><span>Poids: </span>500g/m</li>
      </ul>
      <div id="tabs-2">
        <ul class="feature-list">
          <li><span>Compositions: </span>80% coton 20% viscose</li>
          <li><span>Poids: </span>500g/m</li>
        </ul>
      </div>
    </body></html>
    """

    def _plan(self, *, compose: bool) -> dict:
        description = {
            "fallbacks": [
                {
                    "type": "compose",
                    "label": "description_blocks",
                    "parts": [
                        {
                            "type": "css_html",
                            "selector": "#tabs-1",
                            "exclude_selectors": [".promo"],
                        },
                        {"type": "css_html", "selector": "ul.feature-list"},
                        {"type": "css_html", "selector": "#tabs-2"},
                    ],
                },
                {
                    "type": "css_attr",
                    "selector": 'meta[itemprop="description"]',
                    "attr": "content",
                    "label": "microdata_description",
                },
            ],
            "audit": {
                "blocks": [
                    {
                        "selector": "#tabs-1",
                        "label": "narrative",
                        "exclude_selectors": [".promo"],
                    },
                    {"selector": "ul.feature-list", "label": "specs"},
                    {"selector": "#tabs-2", "label": "spec_tab"},
                ]
            },
        }
        if not compose:
            description["fallbacks"] = description["fallbacks"][1:]
        return {
            "site": {"locale": "fr-FR"},
            "extract": {
                "fields": {
                    "name": {
                        "fallbacks": [{"type": "constant", "value": "Fabric"}]
                    },
                    "price.amount": {
                        "fallbacks": [{"type": "constant", "value": 10}]
                    },
                    "price.currency": {
                        "fallbacks": [{"type": "constant", "value": "EUR"}]
                    },
                    "primary_image_url": {
                        "fallbacks": [{"type": "constant", "value": "https://x.test/a.jpg"}]
                    },
                    "source_url": {
                        "fallbacks": [{"type": "constant", "value": "https://x.test/p"}]
                    },
                    "description_html": description,
                }
            },
        }

    def test_compose_merges_narrative_and_specs_without_promo(self) -> None:
        product = extract_product(
            HtmlPage(self.HTML, "https://x.test/p"), self._plan(compose=True)
        )
        description = product.values["description_html"]
        self.assertIn("Soft cotton fabric", description)
        self.assertIn("80% coton 20% viscose", description)
        self.assertIn("500g/m", description)
        self.assertNotIn("REDUCTION", description)
        self.assertEqual(product.description_status, "complete")
        self.assertEqual(product.extras["description_html"]["audit"]["missing_blocks"], [])

    def test_audit_flags_blocks_when_only_microdata_is_used(self) -> None:
        product = extract_product(
            HtmlPage(self.HTML, "https://x.test/p"), self._plan(compose=False)
        )
        self.assertEqual(product.values["description_html"], "<p>100% coton</p>")
        self.assertEqual(product.description_status, "partial")
        self.assertEqual(
            product.missing_reasons["description_html"],
            "DESCRIPTION_BLOCKS_MISSING",
        )
        self.assertIn(
            "specs",
            product.extras["description_html"]["audit"]["missing_blocks"],
        )


if __name__ == "__main__":
    unittest.main()
