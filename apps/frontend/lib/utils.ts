import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(num: number | null | undefined): string {
  if (num === null || num === undefined) return "0";
  return new Intl.NumberFormat("en-US").format(num);
}

export function getGradeColor(grade: string): { bg: string; text: string; stroke: string } {
  switch (grade?.toUpperCase()) {
    case "A":
      return { bg: "bg-emerald-500/10 dark:bg-emerald-500/20", text: "text-emerald-600 dark:text-emerald-400", stroke: "#10B981" };
    case "B":
      return { bg: "bg-lime-500/10 dark:bg-lime-500/20", text: "text-lime-600 dark:text-lime-400", stroke: "#84CC16" };
    case "C":
      return { bg: "bg-amber-500/10 dark:bg-amber-500/20", text: "text-amber-600 dark:text-amber-400", stroke: "#EAB308" };
    case "D":
      return { bg: "bg-orange-500/10 dark:bg-orange-500/20", text: "text-orange-600 dark:text-orange-400", stroke: "#F97316" };
    case "F":
    default:
      return { bg: "bg-rose-500/10 dark:bg-rose-500/20", text: "text-rose-600 dark:text-rose-400", stroke: "#EF4444" };
  }
}

export function getStatusCodeBadge(code: number | null): { variant: string; className: string } {
  if (!code) return { variant: "outline", className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" };
  if (code >= 200 && code < 300) {
    return { variant: "default", className: "bg-emerald-500/15 text-emerald-700 border-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-400 dark:border-emerald-800" };
  }
  if (code >= 300 && code < 400) {
    return { variant: "default", className: "bg-blue-500/15 text-blue-700 border-blue-300 dark:bg-blue-950/40 dark:text-blue-400 dark:border-blue-800" };
  }
  return { variant: "destructive", className: "bg-rose-500/15 text-rose-700 border-rose-300 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-800" };
}

export function getSeverityBadge(severity: "critical" | "warning" | "info" | string) {
  switch (severity?.toLowerCase()) {
    case "critical":
      return { label: "CRITICAL", className: "bg-rose-500/15 text-rose-700 border-rose-200 dark:border-rose-900 dark:text-rose-400" };
    case "warning":
      return { label: "WARNING", className: "bg-amber-500/15 text-amber-700 border-amber-200 dark:border-amber-900 dark:text-amber-400" };
    case "info":
    default:
      return { label: "INFO", className: "bg-slate-500/15 text-slate-700 border-slate-200 dark:border-slate-800 dark:text-slate-400" };
  }
}
