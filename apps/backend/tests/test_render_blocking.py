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
