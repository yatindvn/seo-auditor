import type { Metadata } from "next";

/** The public address. Canonical and og:url values are paths resolved
 *  against it (Next's metadataBase). */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://seo-auditor-navy.vercel.app").replace(/\/$/, "");
export const SITE_NAME = "SEO Auditor";

/** public/og-image.png: the preview shown when a link is shared. */
export const SHARE_IMAGE = { url: "/og-image.png", width: 1200, height: 630, alt: "SEO Auditor — full-site technical SEO analysis" };

/** A public page: its own canonical, with og:url and share text to match. */
export function pageMetadata(path: string, title: string, description: string): Metadata {
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: { type: "website", siteName: SITE_NAME, url: path, title, description, images: [SHARE_IMAGE] },
    twitter: { card: "summary_large_image", title, description, images: [SHARE_IMAGE.url] },
  };
}

/** One audit's or project's data: kept out of search results. Clears the
 *  canonical a parent layout (e.g. /projects) would otherwise pass down. */
export const PRIVATE_PAGE: Metadata = {
  robots: { index: false, follow: false },
  alternates: { canonical: null },
  openGraph: { type: "website", siteName: SITE_NAME, images: [SHARE_IMAGE] },
};

export const SITE_DESCRIPTION =
  "Crawl any website and get a complete technical, on-page, performance, accessibility, and security SEO audit with a prioritized health score.";

/** JSON-LD for every page: the site and the app it hosts. Only facts we can
 *  stand behind -- no prices or ratings. */
export function structuredData(): Record<string, unknown> {
  const home = `${SITE_URL}/`;
  return {
    "@context": "https://schema.org",
    "@graph": [
      { "@type": "WebSite", "@id": `${SITE_URL}/#website`, url: home, name: SITE_NAME, description: SITE_DESCRIPTION, inLanguage: "en" },
      { "@type": "WebApplication", "@id": `${SITE_URL}/#app`, url: home, name: SITE_NAME, description: SITE_DESCRIPTION,
        applicationCategory: "DeveloperApplication", operatingSystem: "Any", browserRequirements: "Requires JavaScript",
        isPartOf: { "@id": `${SITE_URL}/#website` } },
    ],
  };
}

/** JSON for a <script type="application/ld+json"> tag: `<` is escaped so the
 *  content can never close the tag early. */
export function jsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\u003c");
}
