"use client";

import React from "react";
import { Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { UseApiResult } from "@/lib/use-api";
import { ErrorState } from "@/components/platform/error-state";
import { errorTitle } from "@/lib/api-errors";


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
      <ErrorState title={errorTitle(state.error)} message={state.error.message}
                  action={<Button variant="outline" size="sm" className="rounded-full active:scale-95" onClick={state.reload}>Retry</Button>} />
    );
  }
  if (state.data === null) return null;
  if (isEmpty?.(state.data)) return <EmptyState title={emptyTitle} text={emptyText} action={emptyAction} />;
  return <>{children(state.data)}</>;
}
