import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "旅游规划助手 | Tourism Agent",
  description: "基于大语言模型的智慧文旅规划系统，AI 驱动的个性化旅行规划体验",
  keywords: ["旅游规划", "AI助手", "智慧文旅", "行程规划", "旅行攻略"],
  authors: [{ name: "Tourism Agent Team" }],
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "旅游规划助手",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
    { media: "(prefers-color-scheme: dark)", color: "#0f172a" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // 读取 APP_MODE 环境变量，控制开发/展示模式
  // 设为 "demo" 时隐藏 Next.js 开发浮层，适合答辩/演示
  const appMode = process.env.NEXT_PUBLIC_APP_MODE;
  const isDemoMode = appMode === "demo";

  return (
    <html lang="zh-CN" suppressHydrationWarning className={isDemoMode ? "demo-mode" : ""}>
      <body className={inter.className}>
        {children}
      </body>
    </html>
  );
}
