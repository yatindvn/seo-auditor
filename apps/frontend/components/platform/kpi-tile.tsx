import React from "react";

export function KpiTile({ label, value, delta, hint }: {
  label: string; value: React.ReactNode; delta?: React.ReactNode; hint?: string;
}) {
  return (
    <div className="rounded-[18px] border bg-card p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-3xl font-semibold tracking-tight tabular-nums">{value}</span>
        {delta}
      </div>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
