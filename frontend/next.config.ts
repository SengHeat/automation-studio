import type { NextConfig } from "next";

const isProd = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = {
  ...(isProd ? { output: "export", trailingSlash: true } : {}),
  images: { unoptimized: true },
  async rewrites() {
    if (isProd) return [];
    return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
  },
};

export default nextConfig;
