# SEO Auditor (CLI)

A full-site SEO auditing tool that crawls a website and produces a
technical, on-page, content, performance, mobile, accessibility, security
and international-SEO audit — with an AI-style prioritized recommendation
engine and CSV / JSON / Excel / PDF / HTML reports.

## What it checks

- **Crawler**: BFS crawl from a start URL, same-domain scoping, robots.txt,
  sitemap.xml (incl. sitemap indexes), redirect-chain following, retries,
  multi-threaded fetching, URL de-duplication, crawl-depth control.
- **Technical SEO**: status codes, redirect chains/loops, HTTPS + mixed
  content, canonical tags, robots meta / X-Robots-Tag, noindex/nofollow.
- **On-page SEO**: title, meta description, H1/heading hierarchy, image alt
  text, link quality (empty anchors, `rel=noopener`), JSON-LD structured
  data, Open Graph / Twitter Card tags, URL structure.
- **Content analysis**: word count / thin content, keyword density,
  Flesch readability, exact + near-duplicate content detection.
- **Performance**: TTFB, DOM size, render-blocking CSS/JS, compression,
  cache headers — plus **optional real Core Web Vitals** (LCP/CLS/INP/FCP/TBT,
  lab + field data) via the Google PageSpeed Insights API if you pass
  `--psi-key`.
- **Mobile**: viewport meta tag, tiny inline font sizes.
- **Accessibility**: missing alt attributes, unlabeled form fields, missing
  `lang`, focusable elements inside `aria-hidden` (static checks — not a
  substitute for a full axe-core browser audit).
- **Security**: HSTS, CSP, X-Frame-Options, X-Content-Type-Options,
  Referrer-Policy headers.
- **International SEO**: hreflang duplicates / missing x-default.
- **Media**: video posters, PDF link inventory.
- **JavaScript SEO**: heuristic detection of pages that may depend on
  client-side rendering (thin raw HTML + SPA root + many scripts).
- **Site-wide analysis**: internal link graph, orphan pages, dead-end pages,
  crawl-depth distribution, PageRank-style importance ranking (via
  networkx), duplicate titles/descriptions/H1/content/canonicals, redirect
  chain/loop report, broken internal + external link report.
- **AI-style recommendations**: a weighted rule engine turns every issue
  found into a prioritized, human-readable fix recommendation (no external
  API calls needed — fully offline).

### Not included (by design, for a dependency-light CLI)
- **JavaScript rendering** (Playwright): the crawler reads static HTML only.
  Sites that require JS to render primary content will show as thin/CSR-only.
- **Full Core Web Vitals / Lighthouse**: use `--psi-key` for real Google
  PageSpeed Insights data instead of running a full local Chrome instance.
- **Google Search Console / Analytics / backlink APIs**: not wired up, but
  `report.py`'s output is structured JSON that's easy to merge with them.

## Install

```bash
pip install -r requirements.txt
# or, for a `seo-audit` console command:
pip install -e .
```

## Usage

```bash
python -m seo_auditor.cli https://example.com --max-pages 200 --out ./audit_output

# or, after `pip install -e .`:
seo-audit https://example.com --max-pages 200 --out ./audit_output
```

### Common options

| Flag | Default | Description |
|---|---|---|
| `--max-pages` | 200 | Max pages to crawl |
| `--max-depth` | 5 | Max crawl depth from the start URL |
| `--concurrency` | 8 | Concurrent requests |
| `--timeout` | 15 | Per-request timeout (s) |
| `--retries` | 2 | Retries per failed request |
| `--delay` | 0.0 | Delay between requests per worker (politeness) |
| `--ignore-robots` | off | Ignore robots.txt disallow rules |
| `--skip-external-links` | off | Skip checking external link status codes |
| `--check-near-duplicates` | off | Run near-duplicate content detection (slower, O(n²)) |
| `--psi-key` | — | Google PageSpeed Insights API key for real Core Web Vitals |
| `--psi-strategy` | mobile | `mobile` or `desktop` for PSI |
| `--out` | ./seo_audit_output | Output directory |

## Output

Written to `--out`:

- `audit_report.json` — full structured data (everything)
- `audit_report.xlsx` — multi-sheet workbook (pages, recommendations,
  broken links, redirects, duplicates, issue frequency)
- `audit_report.html` — shareable visual report with health score
- `audit_summary.pdf` — executive summary + top recommendations
- `pages.csv` — one row per crawled page

## Architecture

```
seo_auditor/
├── crawler.py         # BFS crawler, robots.txt, sitemap, redirects
├── checks.py           # Per-page checks: technical/on-page/content/mobile/
│                        # accessibility/security/structured data/intl/media
├── performance.py      # Page-weight proxies + optional PSI API integration
├── analysis.py         # Site-wide: link graph, duplicates, redirects, orphans
├── ai_suggestions.py   # Rule-based prioritized recommendation engine
├── report.py           # Health score + CSV/JSON/Excel/PDF/HTML exporters
└── cli.py               # argparse CLI entry point
```

## Extending

- Swap `ai_suggestions.py`'s rule engine for a real LLM call (e.g. the
  Anthropic API) by replacing `generate_recommendations()` — the issue data
  it consumes is already structured and ready to hand to a prompt.
- Add JS rendering by wiring Playwright into `crawler.py`'s `_fetch()`
  method as an alternate fetch path.
- Add Search Console / Analytics by pulling their APIs and merging results
  into `full_data` in `cli.py` before export.
