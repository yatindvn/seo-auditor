import { RankTarget } from "@seo-auditor/shared";

export interface RankTargetRow {
  url: string;
  keywords: string;
}

const MAX_KEYWORDS_PER_TARGET = 10;

/** Convert UI rows into API payload shape, dropping incomplete rows. */
export function buildRankTargets(rows: RankTargetRow[]): RankTarget[] {
  return rows
    .map(row => ({
      url: row.url.trim(),
      keywords: row.keywords
        .split(",")
        .map(k => k.trim())
        .filter(Boolean)
        .slice(0, MAX_KEYWORDS_PER_TARGET),
    }))
    .filter(t => t.url.length > 0 && t.keywords.length > 0);
}

/** One Google CSE query is spent per keyword per page. */
export function countQueries(rows: RankTargetRow[]): number {
  return buildRankTargets(rows).reduce((sum, t) => sum + t.keywords.length, 0);
}
