import { securityHeaders } from "./lib/security-headers.mjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ['recharts'],
  async headers() {
    const headers = securityHeaders({
      apiUrl: process.env.NEXT_PUBLIC_API_URL || process.env.VITE_API_URL || "http://127.0.0.1:5000",
      wsUrl: process.env.NEXT_PUBLIC_WS_URL || process.env.VITE_WS_URL || "ws://localhost:5000/ws",
      dev: process.env.NODE_ENV !== "production",
    });
    return [{ source: "/:path*", headers }];
  },
};

export default nextConfig;
