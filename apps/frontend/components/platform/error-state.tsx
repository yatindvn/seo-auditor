import React from "react";
import { AlertTriangle } from "lucide-react";

/** The error box for a failed load. No hooks, so it renders on the server too;
 *  `action` is the retry control (a button in the browser, a link on the server). */
export function ErrorState({ title, message, action }: { title: string; message: string; action?: React.ReactNode }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-[18px] border border-rose-200 bg-rose-50/60 p-6 dark:border-rose-900 dark:bg-rose-950/30">
      <div className="flex items-center gap-2 font-semibold tracking-tight text-rose-700 dark:text-rose-400">
        <AlertTriangle className="h-4 w-4" aria-hidden /> {title}
      </div>
      <p className="text-sm text-muted-foreground">{message}</p>
      {action}
    </div>
  );
}
