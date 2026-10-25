"use client";

import { DependencyList, useCallback, useEffect, useRef, useState } from "react";

export interface UseApiResult<T> {
  data: T | null;
  error: Error | null;
  isLoading: boolean;
  reload: () => void;
}

/** Fetch on mount and whenever `deps` change. A response that arrives after a
 *  newer request started is dropped, so fast tab or filter changes never show
 *  stale data. A null fetcher means "don't fetch yet". */
export function useApi<T>(fetcher: (() => Promise<T>) | null, deps: DependencyList): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setLoading] = useState(fetcher !== null);
  const [nonce, setNonce] = useState(0);
  const latest = useRef(0);

  useEffect(() => {
    if (!fetcher) {
      setLoading(false);
      return;
    }
    const id = ++latest.current;
    setLoading(true);
    setError(null);
    fetcher()
      .then((result) => {
        if (id === latest.current) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (id === latest.current) {
          setError(e instanceof Error ? e : new Error(String(e)));
          setLoading(false);
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, isLoading, reload };
}
