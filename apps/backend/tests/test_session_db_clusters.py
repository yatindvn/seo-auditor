"""Grouping pages by URL path, for an architecture graph that stays drawable.

A node per page is ~5000 nodes and a few hundred thousand edges at the Full Site
Crawl preset, which no browser renders interactively. Pages group by their first
path segment and a cluster expands on demand.

The edge cases are where this gets ambiguous, so they are pinned here rather
than left to the renderer.
"""

import pytest

from app.models.session_db import SessionDB

HOME = "https://example.com/"


@pytest.fixture
def db(tmp_path):
    database = SessionDB(tmp_path / "sess_clusters.db")
    yield database
    database.close()


def _add(db, urls, depth=1):
    db.add_pages([
        {"url": url, "final_url": url, "depth": depth, "status": 200,
         "title": "T", "issues": [], "meta": {}}
        for url in urls
    ])


def test_pages_group_by_their_first_path_segment(db):
    _add(db, [f"{HOME}blog/{i}" for i in range(4)])
    _add(db, [f"{HOME}shop/{i}" for i in range(7)])

    clusters = db.get_clusters(HOME)

    by_id = {c["id"]: c for c in clusters}
    assert by_id["/blog"]["count"] == 4
    assert by_id["/shop"]["count"] == 7


def test_the_start_url_is_its_own_node(db):
    """The home page anchors the graph. Folding it into a cluster would hide
    the one page every site has."""
    _add(db, [HOME], depth=0)
    _add(db, [f"{HOME}blog/{i}" for i in range(3)])

    clusters = db.get_clusters(HOME)

    home_node = next(c for c in clusters if c["id"] == "home")
    assert home_node["count"] == 1
    assert home_node["url"] == HOME


def test_a_page_with_no_path_segment_joins_home(db):
    """Query-only and root URLs have no segment to group on."""
    _add(db, [HOME, f"{HOME}?utm=x"], depth=0)

    clusters = db.get_clusters(HOME)

    assert next(c for c in clusters if c["id"] == "home")["count"] == 2
    assert len(clusters) == 1


def test_a_cluster_of_one_page_is_that_page(db):
    """A cluster node standing for a single page adds a click and tells the
    viewer nothing."""
    _add(db, [f"{HOME}about"])

    cluster = next(c for c in db.get_clusters(HOME) if c["id"] != "home")

    assert cluster["count"] == 1
    assert cluster["url"] == f"{HOME}about"
    assert cluster["is_page"] is True


def test_clusters_beyond_the_cap_collapse_into_one_other_node(db):
    _add(db, [f"{HOME}seg{i:03d}/a" for i in range(70)])
    _add(db, [f"{HOME}seg{i:03d}/b" for i in range(70)])

    clusters = db.get_clusters(HOME, max_clusters=60)

    assert len(clusters) == 61, "60 largest plus one 'other'"
    other = next(c for c in clusters if c["id"] == "other")
    assert other["count"] == 20, "10 leftover segments of 2 pages each"


def test_clusters_are_ordered_by_size(db):
    _add(db, [f"{HOME}small/1"])
    _add(db, [f"{HOME}big/{i}" for i in range(9)])

    clusters = [c for c in db.get_clusters(HOME) if c["id"] != "home"]

    assert [c["id"] for c in clusters] == ["/big", "/small"]


def test_cluster_edges_aggregate_the_links_between_them(db):
    _add(db, [f"{HOME}blog/a", f"{HOME}shop/x", f"{HOME}shop/y"])
    db.add_links([
        (f"{HOME}blog/a", f"{HOME}shop/x", True),
        (f"{HOME}blog/a", f"{HOME}shop/y", True),
        (f"{HOME}shop/x", f"{HOME}blog/a", True),
    ])

    edges = db.get_cluster_edges(HOME)

    weights = {(e["source"], e["target"]): e["weight"] for e in edges}
    assert weights[("/blog", "/shop")] == 2
    assert weights[("/shop", "/blog")] == 1


def test_expanding_a_cluster_returns_its_pages_and_their_edges(db):
    _add(db, [f"{HOME}blog/a", f"{HOME}blog/b", f"{HOME}shop/x"])
    db.add_links([
        (f"{HOME}blog/a", f"{HOME}blog/b", True),
        (f"{HOME}blog/a", f"{HOME}shop/x", True),
    ])

    nodes, links = db.get_cluster_pages(HOME, "/blog")

    assert {n["url"] for n in nodes} == {f"{HOME}blog/a", f"{HOME}blog/b"}
    assert links == [{"source": f"{HOME}blog/a", "target": f"{HOME}blog/b"}], (
        "only edges within the expanded cluster; the rest stay collapsed"
    )


def test_expanding_an_unknown_segment_is_empty_not_an_error(db):
    _add(db, [f"{HOME}blog/a"])

    nodes, links = db.get_cluster_pages(HOME, "/nope")

    assert nodes == []
    assert links == []


def test_a_flat_site_produces_a_single_cluster(db):
    """Every page at the root. The caller uses this to fall back to a
    depth-limited view rather than drawing one enormous node."""
    _add(db, [f"{HOME}page{i}.html" for i in range(30)], depth=1)

    clusters = [c for c in db.get_clusters(HOME) if c["id"] != "home"]

    assert len(clusters) == 30, "each root-level page is its own segment"
