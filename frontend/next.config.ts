import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  experimental: {
    turbopackFileSystemCacheForDev: false,
  },
  // 隐藏左下角 "Made with Next.js" 徽标（展示模式友好）
  devIndicators: false,
};

export default nextConfig;
