import { Activity, Clock, Link2, ExternalLink, RefreshCw, CheckCircle2, XCircle } from "lucide-react";

export function getActivityIcon(type: string) {
  switch (type) {
    case "internal_link": return <Link2 className="h-3.5 w-3.5 text-blue-500 shrink-0 mt-0.5" />;
    case "external_link": return <ExternalLink className="h-3.5 w-3.5 text-purple-500 shrink-0 mt-0.5" />;
    case "broken_link": return <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0 mt-0.5" />;
    case "timeout": return <Clock className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" />;
    case "redirect": return <RefreshCw className="h-3.5 w-3.5 text-orange-500 shrink-0 mt-0.5" />;
    case "page_crawled": return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0 mt-0.5" />;
    default: return <Activity className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />;
  }
}
