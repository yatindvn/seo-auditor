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
