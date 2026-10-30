import { FlaskConical } from "lucide-react";

export function DryRunBanner({ show, message = "Preview data. DataForSEO is not live, so these numbers are made up." }: { show: boolean; message?: string }) {
  if (!show) return null;
  return (
    <div role="note" className="flex items-center gap-2 rounded-[18px] border border-amber-200 bg-amber-50/70 px-4 py-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
      <FlaskConical className="h-4 w-4 shrink-0" aria-hidden />
      {message}
    </div>
  );
}
