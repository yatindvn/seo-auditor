/**
 * Server-side pagination for the panels that show rows.
 *
 * The dashboard used to receive every page row inside one audit payload and
 * slice it in the browser. At 5000 pages that payload is tens of megabytes, so
 * rows are fetched a page at a time instead.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";

import { usePaginated } from "@/lib/api-hooks";

function envelope(items: unknown[], total: number, offset = 0, limit = 50) {
  return { items, total, offset, limit };
}

describe("usePaginated", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("loads the first page and reports the unpaginated total", async () => {
    const fetcher = vi.fn().mockResolvedValue(envelope([{ url: "a" }, { url: "b" }], 120));

    const { result } = renderHook(() => usePaginated(fetcher, [], 2));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.items).toHaveLength(2);
    expect(result.current.total).toBe(120);
    expect(fetcher).toHaveBeenCalledWith(0, 2);
  });

  it("asks for the next window by offset, not by re-slicing", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(envelope([{ url: "a" }], 3, 0, 1))
      .mockResolvedValueOnce(envelope([{ url: "b" }], 3, 1, 1));

    const { result } = renderHook(() => usePaginated(fetcher, [], 1));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.next());

    await waitFor(() => expect(result.current.items[0]).toEqual({ url: "b" }));
    expect(fetcher).toHaveBeenLastCalledWith(1, 1);
  });

  it("does not page past the end", async () => {
    const fetcher = vi.fn().mockResolvedValue(envelope([{ url: "a" }], 1, 0, 50));

    const { result } = renderHook(() => usePaginated(fetcher, [], 50));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.next());

    await waitFor(() => expect(result.current.offset).toBe(0));
    expect(result.current.hasNext).toBe(false);
  });

  it("surfaces a failure instead of rendering an empty table", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("backend is down"));

    const { result } = renderHook(() => usePaginated(fetcher, [], 50));

    await waitFor(() => expect(result.current.error).toBe("backend is down"));
    expect(result.current.isLoading).toBe(false);
  });

  it("refetches from the first page when its dependencies change", async () => {
    const fetcher = vi.fn().mockResolvedValue(envelope([{ url: "a" }], 10));
    let filter = "blog";

    const { result, rerender } = renderHook(() => usePaginated(fetcher, [filter], 5));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.next());
    await waitFor(() => expect(result.current.offset).toBe(5));

    filter = "shop";
    rerender();

    await waitFor(() => expect(result.current.offset).toBe(0));
  });
});
