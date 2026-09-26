"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * A window of rows fetched from the server, with the unpaginated total.
 *
 * The dashboard used to receive every page row inside one audit payload and
 * slice it in the browser. At 5000 pages that payload is tens of megabytes --
 * more than the tab can hold, let alone parse -- so rows are fetched a window
 * at a time and `total` is what sizes the pager.
 */
export interface Paginated<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface UsePaginatedResult<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
  page: number;
  pageCount: number;
  hasNext: boolean;
  hasPrevious: boolean;
  isLoading: boolean;
  error: string | null;
  next: () => void;
  previous: () => void;
  goTo: (offset: number) => void;
  reload: () => void;
}

export function usePaginated<T>(
  fetcher: (offset: number, limit: number) => Promise<Paginated<T>>,
  deps: unknown[] = [],
  limit = 50,
): UsePaginatedResult<T> {
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  // A slow response for an earlier window must not overwrite a later one.
  const requestId = useRef(0);
  const serialisedDeps = JSON.stringify(deps);

  // A filter or sort change makes the current offset meaningless: page 4 of the
  // old result set is not page 4 of the new one.
  useEffect(() => {
    setOffset(0);
  }, [serialisedDeps]);

  useEffect(() => {
    const id = ++requestId.current;
    let cancelled = false;
    setIsLoading(true);

    fetcher(offset, limit)
      .then((page) => {
        if (cancelled || id !== requestId.current) return;
        setItems(page.items ?? []);
        setTotal(page.total ?? 0);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled || id !== requestId.current) return;
        // Surfaced rather than swallowed: an empty table and a failed request
        // look identical to the reader, and only one of them is the truth.
        setError(err instanceof Error ? err.message : String(err));
        setItems([]);
        setTotal(0);
      })
      .finally(() => {
        if (!cancelled && id === requestId.current) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset, limit, serialisedDeps, nonce]);

  const pageCount = Math.max(1, Math.ceil(total / limit));
  const hasNext = offset + limit < total;
  const hasPrevious = offset > 0;

  const next = useCallback(() => {
    setOffset((current) => (current + limit < total ? current + limit : current));
  }, [limit, total]);

  const previous = useCallback(() => {
    setOffset((current) => Math.max(0, current - limit));
  }, [limit]);

  const goTo = useCallback((target: number) => {
    setOffset(Math.max(0, target));
  }, []);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  return {
    items, total, offset, limit,
    page: Math.floor(offset / limit) + 1,
    pageCount, hasNext, hasPrevious, isLoading, error,
    next, previous, goTo, reload,
  };
}
