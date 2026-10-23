"use client";

import { useCallback, useEffect, useState } from "react";

type AsyncState<T> =
  | { status: "loading"; data?: undefined; error?: undefined }
  | { status: "error"; data?: undefined; error: string }
  | { status: "success"; data: T; error?: undefined };

/** Runs `fn` on mount and whenever `fn` itself changes identity. Every
 * dashboard page shares this exact loading/error/data shape, so it lives
 * here once rather than being re-implemented per page.
 *
 * Callers must memoize `fn` with `useCallback` (with a literal deps array)
 * so its identity only changes when the inputs it actually depends on do:
 *   useAsync(useCallback(() => api.listReportsForAlert(id), [id]))
 */
export function useAsync<T>(fn: () => Promise<T>) {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });

  const load = useCallback(
    (signal: { cancelled: boolean }) => {
      setState({ status: "loading" });
      fn()
        .then((data) => {
          if (!signal.cancelled) setState({ status: "success", data });
        })
        .catch((err: unknown) => {
          if (!signal.cancelled) {
            setState({
              status: "error",
              error: err instanceof Error ? err.message : "Something went wrong.",
            });
          }
        });
    },
    [fn]
  );

  useEffect(() => {
    const signal = { cancelled: false };
    load(signal);
    return () => {
      signal.cancelled = true;
    };
  }, [load]);

  const refetch = useCallback(() => load({ cancelled: false }), [load]);

  return { ...state, refetch };
}
