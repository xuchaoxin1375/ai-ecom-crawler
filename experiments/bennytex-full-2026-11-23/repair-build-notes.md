# bennytex.fr rule repair — build notes

## Target

- Rule: `bennytex-fr-build`, `2026.11.23-1` → `2026.11.23-2`
- Entry: `https://www.bennytex.fr/`
- Market / locale / currency: `FR` / `fr-FR` / `EUR` (unchanged)
- Scope of the repair: description composition only. Discovery sources, scope, fetch,
  normalize, validate, output and the five core fields are byte-identical to the
  previous rule.

## Reported gap

The old `description_html` took the first matching block: an absent product JSON-LD
(no Product JSON-LD on this site), then `#tabs-1`, then `meta[itemprop="description"]`.
Two failure shapes came out of that:

- The description tab is often a single line ("100% viscose eco", "80% laine
  20% polyamide super doux et souple") while the real specification rows live in
  `ul.feature-list` and in the Specification tab (`#tabs-2`). On 30739 the old chain
  produced "100% viscose eco REDUCTION 50", badge included.
- Some products render no Description tab at all, so the chain fell through to the
  flattened microdata summary. On 31170 that meta tag is literally `100% soie`, so the
  whole composition/poids/largeur block was lost.

## Pages inspected (5 GETs, static engine, no cookies)

| URL | Description tab | Feature list | Specification tab |
| --- | --- | --- | --- |
| `/11603-molleton-gratte-uni-jaune.html` | present, full narrative + inline specs | 3 rows | 3 rows |
| `/31170-carre-de-soie-en-twill-de-soie-de-luxe-4040-cm-100-soie-fond-orange-imprime.html` | **absent** (only Specification + Avis) | 5 rows | 5 rows |
| `/30865-coupon-velours-de-laine-carreau-fond-fuchia-et-noir-tres-doux.html` | present, one line only | 6 rows | 6 rows |
| `/30739-fibranne-viscose-fond-vert-eau-poids-noir-marine.html` | present, heading only | 6 rows | 6 rows |
| `/11607-molleton-gratte-uni-bleu-turquoise.html` | present, full narrative + inline specs | 3 rows | 3 rows |

Currency confirmed as `EUR` on every sampled page (`meta[itemprop="priceCurrency"]`),
and `link[rel="canonical"]` is still absent, so the `source_url` fallback is unchanged.

## Page structure that the rule now relies on

- `ul.feature-list` — the visible spec block in the product summary column; one `li`
  per attribute with a `<span>` label ("Hauteur: ", "Poids: ", "Compositions: ").
  Exactly one per page, and it appears before the tab panes in document order.
- `#tabs-1` — Description pane. Varies from a full narrative (care, OEKO-TEX note,
  image) to a single ingredient line. Absent on some products.
- `#tabs-2` — Specification pane; repeats the feature-list values as `div.specification`
  rows with the label before the colon ("Hauteur : 1m40").
- `#tabs-3` — customer reviews; never used.
- Promo badges inside `#tabs-1`: `<span class="unite"><font color="#FFFFFF">REDUCTION 50</font></span>`
  and, on some pages, `<span style="color:#ffffff;">Ce tissu a une REDUC20</span>`.

## Rule changes

- New first fallback `type: compose` (`label: composed_description`,
  `description_status: complete`) merging three blocks in document order:
  `ul.feature-list`, `#tabs-1`, `#tabs-2`. Missing blocks are skipped, which is what
  the 31170 sample needs.
- `exclude_selectors` on that fallback: `span.unite` and `span[style*="color:#ffffff"]`,
  so the REDUCTION/REDUC coupon badges do not leak into the description text.
- `extract.fields.description_html.audit.blocks` declares the same three blocks
  (label + selector), so the host can check that every block present on a page is
  represented in the final `description_html`.
- The two now-secondary CSS fallbacks (`#tabs-1` and the microdata meta) are downgraded
  from `description_status: complete` to `partial`: on their own they are exactly the
  truncated output this repair fixes. `json_ld` stays `complete` but never fires here.
- Specification rows stay in `description_html`; no `options` / `attributes` field was
  added, because the samples expose no purchasable variants (the mètre/coupon wording
  is in the price line, not an option selector).
- `evidence.sample_urls` extended to the five pages above; limitations updated for the
  absent tab, the intentional list/tab repetition, and the sample size.

## Verification performed

- `yq -e` parses the manifest cleanly (JSON round-trip), so the YAML is well formed.
- Fallback chain and block list were replayed against the five saved pages with the
  declared selectors and excludes. Result per page:
  - 11603: list + narrative + spec tab, badges stripped.
  - 31170: narrative reported absent, list + spec tab compose normally; previously
    the field was the microdata summary "100% soie".
  - 30865: narrative "80% laine 20% polyamide super doux et souple" (no badge).
  - 30739: narrative "100% viscose eco" (no badge) plus 6 spec rows — previously the
    field would have been "100% viscose eco REDUCTION 50".
  - 11607: list + narrative + spec tab.
- Total outbound requests for this repair: 5 product pages, all `200`.

## Not verified

- The host's own `compose` implementation was not run here; the merge was replayed with
  an equivalent local DOM pass, so ordering and exclusion behaviour are checked but the
  host's block-audit result is not.
- `host_validation` in the rule is still the record from `2026.11.23-1` (6 products); it
  must be regenerated by the host for `2026.11.23-2`.
- Pagination, other category templates and products whose tabs use different ids were
  not sampled; the compose blocks are declared optional so a missing block degrades to
  the remaining ones rather than failing the field.
- Feature list and specification tab duplicate the same values, so a composed
  description shows those rows twice by design (the brief asks for both blocks).
