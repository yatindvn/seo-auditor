"""Which scripts really block rendering."""

from types import SimpleNamespace

from app.utils.performance import html_weight


def _count(head: str) -> int:
    return html_weight(SimpleNamespace(html=f"<html><head>{head}</head><body><p>x</p></body></html>"))["render_blocking_js_count"]


def test_a_plain_external_script_blocks():
    assert _count('<script src="/a.js"></script>') == 1


def test_bare_async_and_defer_attributes_do_not_block():
    # `async` with no value parses to "", which is falsy: presence is what counts.
    assert _count('<script src="/a.js" async></script><script src="/b.js" async=""></script>'
                  '<script src="/c.js" defer></script>') == 0


def test_module_and_nomodule_scripts_do_not_block():
    # Modules are deferred by default; modern browsers skip nomodule entirely.
    assert _count('<script type="module" src="/m.js"></script><script nomodule src="/polyfills.js"></script>') == 0


def test_inline_scripts_are_not_counted():
    assert _count("<script>var a = 1;</script>") == 0


def test_scripts_in_the_body_do_not_block_rendering():
    # By the time the parser reaches the end of <body>, the page above has
    # rendered; only <head> scripts hold back the first paint (as Lighthouse
    # judges render-blocking resources).
    html = ('<html><head><title>t</title></head><body><h1>Books</h1><p>text</p>'
            '<script src="/jquery.js"></script><script type="text/javascript" src="/ui.js"></script></body></html>')
    weight = html_weight(SimpleNamespace(html=html))
    assert weight["render_blocking_js_count"] == 0
    assert weight["script_tag_count"] == 2          # still counted as scripts


def test_a_plain_script_in_the_head_still_blocks_alongside_body_ones():
    html = '<html><head><script src="/a.js"></script></head><body><script src="/b.js"></script></body></html>'
    assert html_weight(SimpleNamespace(html=html))["render_blocking_js_count"] == 1
