"use client";

import React from "react";
import { Skeleton } from "@/components/ui/skeleton";

export function DashboardSkeleton() {
  return (
    <div className="min-h-screen bg-background px-4 py-8 md:px-8 lg:px-12">
      {/* Header skeleton */}
      <div className="mb-8 space-y-4">
        <Skeleton className="h-6 w-48" />
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="space-y-2">
            <Skeleton className="h-8 w-72" />
            <Skeleton className="h-4 w-44" />
          </div>
          <Skeleton className="h-28 w-72 rounded-2xl" />
        </div>
      </div>

      {/* Stat cards */}
      <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="rounded-2xl border border-border/60 bg-card p-5">
            <Skeleton className="mb-3 h-8 w-8 rounded-xl" />
            <Skeleton className="mb-1.5 h-7 w-16" />
            <Skeleton className="h-3.5 w-20" />
          </div>
        ))}
      </div>

      {/* Charts row */}
      <div className="mb-8 grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="rounded-2xl border border-border/60 bg-card p-6">
          <Skeleton className="mb-4 h-5 w-36" />
          <Skeleton className="h-48 w-full rounded-xl" />
        </div>
        <div className="rounded-2xl border border-border/60 bg-card p-6">
          <Skeleton className="mb-4 h-5 w-40" />
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className={`h-16 w-full rounded-xl`} />
            ))}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-2xl border border-border/60 bg-card p-6">
        <Skeleton className="mb-4 h-5 w-24" />
        <Skeleton className="mb-4 h-10 w-full rounded-xl" />
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}
