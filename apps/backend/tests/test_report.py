from app.utils.report import build_executive_summary


class FakeCrawler:
    def __init__(self):
        self.results = {}
        self.start_url = "https://example.com"
        self.robots_txt_content = "User-agent: *\nDisallow: /admin"
        self.sitemaps_found = ["https://example.com/sitemap.xml"]
        self.sitemap_urls = {"https://example.com/", "https://example.com/about"}


def _build_summary(crawler):
    return build_executive_summary(
        crawler,
        all_page_issues={},
        site_wide={},
        duplicates={},
        redirects={},
        broken_links=[],
        recommendations=[],
    )


def test_executive_summary_includes_robots_txt_content():
    crawler = FakeCrawler()

    summary = _build_summary(crawler)

    assert summary["robots_txt_content"] == crawler.robots_txt_content


def test_executive_summary_includes_sitemap_urls():
    crawler = FakeCrawler()

    summary = _build_summary(crawler)

    assert set(summary["sitemap_urls"]) == crawler.sitemap_urls
