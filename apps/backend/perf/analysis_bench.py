"""Time page analysis on the harness's synthetic pages.

    cd apps/backend
    python perf/analysis_bench.py

Wall-clock medians on one machine: compare before/after on the same machine,
never across machines.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crawl_harness import _page_html  # noqa: E402
from app.analysis import minhash  # noqa: E402
from app.services import page_pipeline  # noqa: E402


def _payloads(count: int):
    return [
        page_pipeline.PagePayload(
            url=f"http://127.0.0.1/page{i}.html", final_url=f"http://127.0.0.1/page{i}.html",
            status_code=200, headers={"Content-Type": "text/html"},
            html=_page_html(i, count).decode("utf-8"), response_time_ms=5.0,
            content_type="text/html", compute_signature=True,
        )
        for i in range(count)
    ]


def _median_ms_per_item(fn, items, repeats: int) -> float:
    runs = []
    for _ in range(repeats):
        started = time.perf_counter()
        for item in items:
            fn(item)
        runs.append((time.perf_counter() - started) / len(items) * 1000)
    return statistics.median(runs)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=200)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args(argv)

    payloads = _payloads(args.pages)
    texts = [page_pipeline.analyze_page(p).dupe_row["text"] for p in payloads]

    print(f"analyze_page median: {_median_ms_per_item(page_pipeline.analyze_page, payloads, args.repeats):.2f} ms/page")
    print(f"signature median:    {_median_ms_per_item(minhash.signature, texts, args.repeats):.2f} ms/page")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
