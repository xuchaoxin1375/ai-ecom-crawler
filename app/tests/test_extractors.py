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


if __name__ == "__main__":
    unittest.main()
