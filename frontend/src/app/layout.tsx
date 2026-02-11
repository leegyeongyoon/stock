import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import Header from "@/components/layout/Header";
import NavBar from "@/components/layout/NavBar";

export const metadata: Metadata = {
  title: "Auto-Trading Dashboard",
  description: "한국 주식 5분봉 인트라데이 자동매매 대시보드",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body className="min-h-screen bg-[#0f172a] text-slate-100">
        <Providers>
          <Header />
          <NavBar />
          <main className="p-6 max-w-7xl mx-auto">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
