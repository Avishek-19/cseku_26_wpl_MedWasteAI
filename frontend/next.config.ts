import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  output: "standalone",
  reactStrictMode: true,
  // Same-origin REST proxy: the browser receives mw_session for the website
  // hostname, so Next's dashboard proxy can read it as well. WebSocket
  // upgrades must be separately configured at the deployment reverse proxy.
  async rewrites() {
    const backend = (process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
    if (!/^https?:\/\//.test(backend)) throw new Error("BACKEND_INTERNAL_URL must be an HTTP(S) URL");
    return [{ source: "/api/v1/:path*", destination: `${backend}/api/v1/:path*` }];
  },
  async headers() {
    return [{
      source: "/(.*)",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=(self)" },
      ],
    }];
  },
};

export default nextConfig;
