# Build notes — familidoo.fr

- Build date: 2026-11-23
- Rule: `familidoo-fr-build` (`2026.11.23-1`, candidate)
- Entry: `https://www.familidoo.fr/fr/`
- Market / locale: `FR` / `fr-FR`
- Currency observed: `EUR`
- Engine: static HTML (PrestaShop 1.7 theme "transformer")

## What was inspected

- Entry page fetched statically once. It is server-rendered and lists six product cards in a slider.
- All six cards use `a.product_img_link` with absolute PrestaShop URLs of the form
  `/fr/<category-slug>/<product-id>-<slug>.html`.
- Three product pages were fetched with the same static path and inspected in full:
  - Poussette 4 places Lidoo Lite Cosmic Black — 599,00 € TTC
  - Poussette compacte Lidoo One Noire — 79,00 € TTC
  - Poussette 4 places Lidoo City H4E Full Grey — 799,00 € TTC
- No browser engine was needed: name, price, currency, image and description are present in the raw HTML.

## Confirmed selectors (product page)

| Field | Primary evidence |
| --- | --- |
| `name` | `h1.product_name[itemprop="name"]` |
| `price.amount` | `span.price[itemprop="price"][content]` inside `[itemprop="offers"]` |
| `price.currency` | `meta[itemprop="priceCurrency"][content="EUR"]`; also `meta[property="product:price:currency"]` |
| `primary_image_url` | `img.pro_gallery_item[itemprop="image"][content]`; also `og:image` |
| `description_html` | `.product-description .product_description_container` (long description) |
| `category` | `nav.breadcrumb_nav` anchors (skip "Accueil") |
| `source_url` | `<link rel="canonical">` matches the current URL |
| `brand` | No product-level brand block; falls back to `og:site_name` = "Familidoo" |

Observed microdata on all three pages: `section#main[itemscope][itemtype="https://schema.org/Product"]`,
`[itemprop="offers"]`, `[itemprop="price"]`, `[itemprop="priceCurrency"]`, `[itemprop="image"]`.

## Currency / market check

The host validation uses the declared static engine. Both entry and product pages were fetched
without browser cookies or locale overrides. Product pages return:

- `<body class="... country-fr currency-eur ...">`
- `<meta property="product:price:amount" content="599">`
- `<meta property="product:price:currency" content="EUR">`

This matches `site.market: FR` and `site.currency: EUR`. The site only exposes a French locale
(`/fr/`, `hreflang="fr-fr"`), so no alternate country path is needed.

## Sample URLs

- https://www.familidoo.fr/fr/poussette-quadruple/74464-poussette-4-places-lidoo-lite-cosmic-black-0615402035002.html
- https://www.familidoo.fr/fr/poussette-compacte/183-poussette-compacte-lidoo-one-noire-4712928373475.html
- https://www.familidoo.fr/fr/poussette-quadruple/193-poussette-4-places-lidoo-city-h4e-full-grey-4712928374274.html

Additional entry-page links observed but not fetched:
`.../8-poussette-4-places-lidoo-star-dj04frl-4712928372676.html`,
`.../316-veilleuse-5-en-1-baby-dream-machine-0617092971653.html`,
`.../74427-bascule-en-mousse-iglu-banane-4751005644831.html`.

## Normalization notes

- Prices are shown TTC. Sale items expose both `span.price` (current) and `span.regular-price`
  (older price). `choose: smaller_public_pair` selects the current public price.
- The page also publishes `product:pretax_price:amount`; it is deliberately **not** used as a
  price candidate because it is the ex-tax value and would undercut the public TTC price.
- `description_html` uses the full tab description; the short description is not used as primary.

## Limitations / not verified

- No `application/ld+json` on any inspected page, so no JSON-LD fallback is declared.
- Brand is shop-level only; no reliable manufacturer/brand element was found in the product DOM.
- `.product-variants` was present but empty on all three samples, so `options` is not extracted.
- Only the six home-page cards were used for discovery. Category listing pages, pagination and
  sitemap coverage were not enumerated, so the rule does not claim full-catalog coverage.
- No login, cart, checkout or captcha path was exercised.
- Legal/consent overlays exist but do not block static HTML extraction.

## Request/time usage

- HTTP requests used: 4 (1 entry page + 3 product pages), well under the 30-request budget.
- Wall-clock time: a few minutes, under the 900-second budget.
- No packages installed, no browser launched, no proxy used.
