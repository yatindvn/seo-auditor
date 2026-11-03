import { describe, expect, it } from "vitest";
import type { Metadata } from "next";

import { metadata as root } from "@/app/layout";
import { metadata as home } from "@/app/(home)/layout";
import { metadata as projects } from "@/app/projects/layout";
import { metadata as keywords } from "@/app/keywords/layout";
import { metadata as content } from "@/app/content/layout";
import { metadata as dashboard } from "@/app/dashboard/layout";
import { metadata as liveCrawl } from "@/app/live-crawl/layout";
import { metadata as project } from "@/app/projects/[id]/layout";
import { SHARE_IMAGE, SITE_URL } from "@/lib/seo";

const og = (m: Metadata) => m.openGraph as Record<string, unknown>;

describe("SEO metadata", () => {
  it("sets the site address and site-wide share tags, but no canonical (it would point every page home)", () => {
    expect(String(root.metadataBase)).toBe(`${SITE_URL}/`);
    expect(og(root).type).toBe("website");
    expect((root.twitter as Record<string, unknown>).card).toBe("summary_large_image");
    expect(root.alternates?.canonical).toBeUndefined();
    expect(og(root).images).toEqual([SHARE_IMAGE]);
  });

  it.each([
    ["/", home], ["/projects", projects], ["/keywords", keywords], ["/content", content],
  ])("gives %s its own canonical and matching og:url", (path, m) => {
    expect(m.alternates?.canonical).toBe(path);
    expect(og(m).url).toBe(path);
    expect(og(m).type).toBe("website");
    expect(m.title).toBeTruthy();
    expect(m.robots).toBeUndefined();
    // A page's openGraph replaces its parent's, so each must carry the image itself.
    expect(og(m).images).toEqual([SHARE_IMAGE]);
    expect((m.twitter as Record<string, unknown>).images).toEqual([SHARE_IMAGE.url]);
  });

  it.each([["dashboard", dashboard], ["live crawl", liveCrawl], ["project", project]])(
    "keeps %s pages (one audit's or project's data) out of search results", (_, m) => {
      expect(m.robots).toEqual({ index: false, follow: false });
    });
});
