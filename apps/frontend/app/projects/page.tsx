import Link from "next/link";
import type { ProjectSummary } from "@seo-auditor/shared";

import { EmptyState } from "@/components/platform/async-state";
import { ErrorState } from "@/components/platform/error-state";
import { PageHeader } from "@/components/platform/page-header";
import { PageGuide } from "@/components/platform/page-guide";
import { PROJECTS_GUIDE } from "@/lib/page-guides";
import { errorTitle } from "@/lib/api-errors";
import { Platform } from "@/services/platform";

// Rendered on the server for each request, so the project links are in the HTML
// (crawlers see them without running JavaScript) and new audits show at once.
export const dynamic = "force-dynamic";

const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

function ProjectCard({ p }: { p: ProjectSummary }) {
  return (
    <Link href={`/projects/${p.id}`}
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
          {p.latest_audit && <><br />last {shortDate(p.latest_audit.finished_at)}</>}
        </p>
      </div>
    </Link>
  );
}

export default async function ProjectsPage() {
  let items: ProjectSummary[] | null = null;
  let failure: Error | null = null;
  try {
    items = (await Platform.listProjects()).items;
  } catch (err) {
    failure = err instanceof Error ? err : new Error(String(err));
  }

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader title="Projects" description="One project per site. Audits and rank checks are filed under their domain." />
      {failure ? (
        <ErrorState title={errorTitle(failure)} message={failure.message}
                    action={<Link href="/projects" className="rounded-full border px-3 py-1.5 text-sm hover:bg-muted active:scale-95">Retry</Link>} />
      ) : items && items.length === 0 ? (
        <EmptyState title="No projects yet" text="A project is created automatically the first time you audit a site."
                    action={<Link href="/" className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95">Run your first audit</Link>} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items?.map((p) => <ProjectCard key={p.id} p={p} />)}
        </div>
      )}
      <PageGuide {...PROJECTS_GUIDE} />
    </main>
  );
}
