"use client";

import Link from "next/link";

import { AsyncState } from "@/components/platform/async-state";
import { PageHeader } from "@/components/platform/page-header";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

export default function ProjectsPage() {
  const projects = useApi(() => Platform.listProjects(), []);
  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader title="Projects" description="One project per site. Audits and rank checks are filed under their domain." />
      <AsyncState
        state={projects}
        isEmpty={(d) => d.items.length === 0}
        emptyTitle="No projects yet"
        emptyText="A project is created automatically the first time you audit a site."
        emptyAction={<Link href="/" className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95">Run your first audit</Link>}
      >
        {(data) => (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.items.map((p) => (
              <Link key={p.id} href={`/projects/${p.id}`} aria-label={p.name}
                    className="group rounded-[18px] border bg-card p-5 transition-colors hover:border-primary/40">
                <p className="truncate font-semibold tracking-tight group-hover:text-primary">{p.name}</p>
                <p className="truncate text-xs text-muted-foreground">{p.domain}</p>
                <div className="mt-4 flex items-end justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">Health</p>
                    <p className="text-2xl font-semibold tabular-nums">{p.latest_audit?.health_score ?? "—"}</p>
                  </div>
                  <p className="text-right text-xs text-muted-foreground">
                    {p.audit_count} audits
                    {p.latest_audit && <><br />last {new Date(p.latest_audit.finished_at).toLocaleDateString()}</>}
                  </p>
                </div>
              </Link>
            ))}
          </div>
        )}
      </AsyncState>
    </main>
  );
}
