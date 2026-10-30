"use client";

import React from "react";

export function ChartFrame({ title, asTable, onToggle, children }: { title: string; asTable: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-[18px] border bg-card p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="font-semibold tracking-tight">{title}</h2>
        <button type="button" onClick={onToggle} className="shrink-0 rounded-full border px-3 py-1 text-xs active:scale-95">{asTable ? "Show as chart" : "Show as table"}</button>
      </div>
      {children}
    </section>
  );
}
