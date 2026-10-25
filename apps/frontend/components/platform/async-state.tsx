"use client";

import React from "react";
import { AlertTriangle, Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { UseApiResult } from "@/lib/use-api";
import { ApiError } from "@/services/platform";

function errorTitle(error: Error): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return "Can't reach the server";
    if (error.status === 503) return "Project data is unavailable right now";
    if (error.status === 404) return "Not found";
  }
  return "Something went wrong";
}

export function EmptyState({ title, text, action }: { title: string; text?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[18px] border border-dashed bg-card px-6 py-12 text-center">
      <Inbox className="h-6 w-6 text-muted-foreground" aria-hidden />
      <p className="font-semibold tracking-tight">{title}</p>
      {text && <p className="max-w-md text-sm text-muted-foreground">{text}</p>}
      {action}
    </div>
  );
}

interface AsyncStateProps<T> {
  state: UseApiResult<T>;
  isEmpty?: (data: T) => boolean;
  emptyTitle?: string;
  emptyText?: string;
  emptyAction?: React.ReactNode;
  children: (data: T) => React.ReactNode;
}

export function AsyncState<T>({ state, isEmpty, emptyTitle = "Nothing here yet", emptyText, emptyAction, children }: AsyncStateProps<T>) {
  if (state.isLoading && state.data === null) {
    return (
      <div data-testid="async-loading" aria-busy="true" className="space-y-3">
        <Skeleton className="h-6 w-1/3" />
        <Skeleton className="h-28 w-full rounded-[18px]" />
      </div>
    );
  }
  if (state.error) {
    return (
      <div role="alert" className="flex flex-col items-start gap-3 rounded-[18px] border border-rose-200 bg-rose-50/60 p-6 dark:border-rose-900 dark:bg-rose-950/30">
        <div className="flex items-center gap-2 font-semibold tracking-tight text-rose-700 dark:text-rose-400">
          <AlertTriangle className="h-4 w-4" aria-hidden /> {errorTitle(state.error)}
        </div>
        <p className="text-sm text-muted-foreground">{state.error.message}</p>
        <Button variant="outline" size="sm" className="rounded-full active:scale-95" onClick={state.reload}>Retry</Button>
      </div>
    );
  }
  if (state.data === null) return null;
  if (isEmpty?.(state.data)) return <EmptyState title={emptyTitle} text={emptyText} action={emptyAction} />;
  return <>{children(state.data)}</>;
}
