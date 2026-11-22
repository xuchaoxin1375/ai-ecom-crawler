# Build notes — bennytex.fr

## Target and scope

- Entry: `https://www.bennytex.fr/`
- Platform: PrestaShop 1.6-era theme `jms_deermarket`, French storefront, prices in EUR.
- Brief target: full catalog, at least 2,000 products. Host validation sample: 6.
- `scope.max_products: 3000`, `max_seconds: 5400`, static engine, one request at a time with 1200 ms delay.

## What was inspected

- Home page HTML (156 KB) and its mega menu (`ul.nav.level0`).
- Site map `https://www.bennytex.fr/plan-site`; the `Catégories` tree gives the authoritative top-level category list.
- Category pages for all top-level categories, page 1 and (for Coton) page 2 with `?p=2`.
- Three product pages from distinct listings:
  - `https://www.bennytex.fr/11603-molleton-gratte-uni-jaune.html` (Coton → Molleton Coton)
  - `https://www.bennytex.fr/31170-carre-de-soie-en-twill-de-soie-de-luxe-4040-cm-100-soie-fond-orange-imprime.html` (Soierie → Twill de soie)
  - `https://www.bennytex.fr/30865-coupon-velours-de-laine-carreau-fond-fuchia-et-noir-tres-doux.html` (Coupon)

## Category and pagination findings

Listings are server-rendered; pagination is `/category?p=N` and each page shows 24 products. The pager prints the last page number, which was used for `max_pages`.

| Top-level category | URL | Pages | Products (approx.) |
| --- | --- | ---: | ---: |
| Coton | `/3-coton` | 29 | 696 |
| Soierie | `/4-soierie` | 8 | 192 |
| Lainage | `/5-lainage` | 4 | 96 |
| Polyester | `/6-polyester` | 12 | 288 |
| Lin | `/8-lin` | 1 | 21 |
| Maille | `/81-maille` | 1 | 24 |
| Dentelle | `/9-dentelle` | 2 | 48 |
| Coupon | `/96-coupon` | 5 | 120 |
| Loisir Créatif | `/111-loisir-creatif` | 11 | 264 |
| Enfant | `/127-enfant` | 15 | 360 |
| Fin de rouleau | `/119-fin-de-rouleau` | 4 | 96 |
| Nouvelle collection | `/176-nouvelle-collection` | 3 | 72 |
| Nouvelle collection 2 | `/179-nouvelle-collection-2` | 5 | 120 |
| Nouvelle collection 3 | `/181-nouvelle-collection-3` | 12 | 288 |

Sum of listed slots is about 2,685 before deduplication, so the 2,000-product target is reachable even after removing overlaps between regular categories and the Nouvelle collection listings.

Excluded from `discovery.sources` because they return an empty `#center_column` (no product grid): `163-mercerie`, `132-vente-tissu-au-rouleau`, `71-carte-cadeau`. Empty price buckets (`164-1` … `174-9`, e.g. "1€") were also ignored.

## Selectors confirmed

On listing pages each product card contains two `a.product-name` links (grid and list view) with the same href; `product_link_selector: "a.product-name"` is used and duplicates are collapsed by URL identity. Product URLs match `/{id}-{slug}.html`.

Product page structure:

- Name: `<h1>`; also `meta[itemprop="name"]`.
- Price: `span#our_price_display` (current price, e.g. `6,45 €`); microdata `meta[itemprop="price"]` inside the first `[itemprop="offers"]` block.
- Currency: `meta[itemprop="priceCurrency"]` = `EUR`.
- Image: `meta[itemprop="image"]` with absolute URLs such as `https://www.bennytex.fr/48654/molleton-gratte-uni-jaune.jpg`.
- Category: breadcrumb `div.breadcrumb-box .navigation-page a`; microdata `meta[itemprop="category"]` is a slug and is `accueil` for coupons.
- Brand: `[itemprop="brand"] meta[itemprop="name"]` = "Made In France".
- Description: `#tabs-1` on the molleton and coupon pages; the silk page has no description tab, only a one-line `meta[itemprop="description"]`.

## Market and currency check

Static fetch (same engine the host uses, no cookies) returned `EUR` in `meta[itemprop="priceCurrency"]` and `€` on the price element for all three product pages. `site.market: FR` and `site.currency: EUR` match the batch and the observed static response.

## Repair round 1

- Host rejected `discovery.strategies: ["listing"]` when `discovery.sources` is set. Changed to `["entry_links"]` and added `link_selector: "a.product-name"`; the listing sources and their `max_pages` are unchanged.
- No selector changes were needed; no selector in the rule uses `:not(...)`/`:first-of-type`. No additional product page was fetched for this repair.

## Limitations / unverified

- Sampled product pages have **no Product JSON-LD**. Only Organization and WebPage JSON-LD blocks exist, so `json_ld` fallbacks will usually miss and microdata/CSS carries extraction. The JSON-LD entries are kept first for template variants that may add it.
- No `rel="canonical"` and no Open Graph tags on sampled pages. `url_identity: canonical` therefore falls back to the request URL in practice; `source_url` uses `meta[itemprop="url"]` as a secondary fallback.
- Coupon pages report the microdata category `accueil`, so breadcrumb is a better category source there.
- No product attribute selects were found on sampled pages (`#attributes` absent); `options` is not extracted.
- Enfant and Nouvelle collection listings may overlap regular fabric categories; deduplication by canonical/request URL is required and the product count is an estimate, not a verified unique count.
- Only three product pages were inspected. Pricing/template behavior for clearance ("fin de rouleau") and enfant products is assumed to follow the same PrestaShop template.
- The host validation covers a small sample only; full-catalog runtime depends on the host honoring `max_seconds`.
