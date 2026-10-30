"""Brand mentions, position and citations in an AI answer."""

from app.ai_visibility.detect import Brand, analyze, citation_domain, first_index, highlights, spans

ME = Brand("books.toscrape.com", True, ("Books to Scrape", "BTS"), "books.toscrape.com")
AMAZON = Brand("amazon.com", False, ("Amazon",), "amazon.com")
READS = Brand("goodreads.com", False, ("Goodreads",), "goodreads.com")


def test_whole_word_case_insensitive_and_domains():
    assert spans("I like books to scrape a lot", ME) == [(7, 22)]
    assert spans("Bookstores and AmazonBasics", AMAZON) == []
    assert spans("non-Amazon sellers", AMAZON) == []              # hyphen counts as part of the word
    assert spans("visit www.amazon.com today", AMAZON) == [(6, 20)]
    assert first_index("BTS, then Books to Scrape", ME) == 0
    assert first_index("nothing here", ME) is None


def test_position_is_order_among_tracked_brands():
    text = "Amazon is biggest. Goodreads has reviews. Books to Scrape is a fun demo."
    result = analyze(text, [], [ME, AMAZON, READS])
    assert result["brands_mentioned"] == ["amazon.com", "goodreads.com", "books.toscrape.com"]
    assert result["mentioned"] is True and result["position"] == 3


def test_absent_brand_has_no_position():
    result = analyze("Amazon only.", [], [ME, AMAZON])
    assert result["mentioned"] is False and result["position"] is None and result["brands_mentioned"] == ["amazon.com"]


def test_citations_count_subdomains_and_gemini_titles():
    assert citation_domain({"url": "https://www.amazon.com/x"}) == "amazon.com"
    gemini = {"url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc", "title": "books.toscrape.com"}
    assert citation_domain(gemini) == "books.toscrape.com"
    assert citation_domain({"url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/x", "title": "A great page"}) is None
    cites = [{"url": "https://reviews.example.com/a"}, {"url": "https://shop.books.toscrape.com/b"}, gemini,
             {"url": "https://reviews.example.com/c"}]
    result = analyze("no brands", cites, [ME, AMAZON])
    assert result["cited"] is True
    assert result["cited_domains"] == ["reviews.example.com", "shop.books.toscrape.com", "books.toscrape.com"]
    assert analyze("x", [{"url": "https://notbooks.toscrape.com.evil.io/"}], [ME])["cited"] is False


def test_highlights_are_sorted_and_never_overlap():
    text = "Books to Scrape (books.toscrape.com) beats Amazon."
    hl = highlights(text, [ME, AMAZON])
    assert [(text[h["start"]:h["end"]], h["owner"]) for h in hl] == [
        ("Books to Scrape", "books.toscrape.com"), ("books.toscrape.com", "books.toscrape.com"), ("Amazon", "amazon.com")]
