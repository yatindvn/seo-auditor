from app.seo import keyword_extraction


def test_extract_keywords_weights_fields_by_importance():
    page_meta = {
        "title": "",
        "h1": "Roasting",
        "meta_description": "Brewing",
        "heading_hierarchy": [],
    }
    content_stats = {"text": ""}

    result = keyword_extraction.extract_keywords(page_meta, content_stats)
    scores = {r["phrase"]: r["score"] for r in result}

    assert scores["roasting"] == 2.5
    assert scores["brewing"] == 2.0
    assert scores["roasting"] > scores["brewing"]


def test_extract_keywords_filters_stop_words():
    page_meta = {
        "title": "This is a Guide for Beginners",
        "h1": "",
        "meta_description": "",
        "heading_hierarchy": [],
    }
    content_stats = {"text": ""}

    result = keyword_extraction.extract_keywords(page_meta, content_stats)
    phrases = [r["phrase"] for r in result]

    assert not any(p in ("this", "is", "a", "for") for p in phrases)
    assert "guide" in phrases
    assert "beginners" in phrases


def test_extract_keywords_builds_ngram_phrases_up_to_three_words():
    page_meta = {
        "title": "Trail Running Shoes",
        "h1": "",
        "meta_description": "",
        "heading_hierarchy": [],
    }
    content_stats = {"text": ""}

    result = keyword_extraction.extract_keywords(page_meta, content_stats)
    phrases = {r["phrase"] for r in result}

    assert "trail running shoes" in phrases
    assert "trail running" in phrases
    assert "running shoes" in phrases
