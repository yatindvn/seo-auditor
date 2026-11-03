// Response headers for every page (used by next.config.mjs). Plain JS so the
// Next config can import it; tested in lib/__tests__/security-headers.test.ts.

function origin(url) {
  try {
    return url ? new URL(url).origin : null;
  } catch {
    return null;
  }
}

/** @param {{ apiUrl?: string, wsUrl?: string, dev?: boolean }} opts */
export function securityHeaders({ apiUrl, wsUrl, dev }) {
  // The only places the page talks to: itself and the backend (HTTP + WebSocket).
  const connect = ["'self'", origin(apiUrl), origin(wsUrl)].filter(Boolean).join(" ");
  const csp = [
    "default-src 'self'",
    // Next inlines its bootstrap scripts; its dev server also evaluates code.
    `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",        // Recharts and Next set inline styles
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${connect}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
  return [
    { key: "Content-Security-Policy", value: csp },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  ];
}
