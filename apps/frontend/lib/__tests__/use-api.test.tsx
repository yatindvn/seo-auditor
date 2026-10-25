import { describe, expect, it } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

import { useApi } from "@/lib/use-api";

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

describe("useApi", () => {
  it("goes loading -> data", async () => {
    const { result } = renderHook(() => useApi(() => Promise.resolve(42), []));
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.data).toBe(42));
    expect(result.current.isLoading).toBe(false);
  });

  it("captures errors and retries on reload", async () => {
    let calls = 0;
    const fetcher = () => (++calls === 1 ? Promise.reject(new Error("down")) : Promise.resolve("ok"));
    const { result } = renderHook(() => useApi(fetcher, []));
    await waitFor(() => expect(result.current.error?.message).toBe("down"));
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.data).toBe("ok"));
    expect(result.current.error).toBeNull();
  });

  it("ignores a stale response when deps change", async () => {
    const slow = deferred<string>();
    const { result, rerender } = renderHook(
      ({ id }) => useApi(() => (id === 1 ? slow.promise : Promise.resolve("second")), [id]),
      { initialProps: { id: 1 } },
    );
    rerender({ id: 2 });
    await waitFor(() => expect(result.current.data).toBe("second"));
    await act(async () => slow.resolve("first"));
    expect(result.current.data).toBe("second");
  });

  it("does nothing when the fetcher is null", () => {
    const { result } = renderHook(() => useApi(null, []));
    expect(result.current.isLoading).toBe(false);
    expect(result.current.data).toBeNull();
  });
});
