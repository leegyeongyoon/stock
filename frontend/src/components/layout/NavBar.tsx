"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Flame, Brain, TrendingUp, ClipboardList, Crown, Filter } from "lucide-react";
import type { LucideIcon } from "lucide-react";

const TABS: { href: string; label: string; Icon: LucideIcon }[] = [
  { href: "/", label: "대시보드", Icon: LayoutDashboard },
  { href: "/themes", label: "테마 분석", Icon: Flame },
  { href: "/strategies", label: "전략 모니터링", Icon: Brain },
  { href: "/performance", label: "수익률 현황", Icon: TrendingUp },
  { href: "/trades", label: "거래내역", Icon: ClipboardList },
  { href: "/stockking", label: "홍인기 전략", Icon: Crown },
  { href: "/gylee", label: "경윤 수정", Icon: Filter },
];

export default function NavBar() {
  const pathname = usePathname();

  return (
    <nav className="bg-slate-900 border-b border-slate-700">
      <div className="max-w-7xl mx-auto px-3 sm:px-6">
        <div className="flex items-center gap-0.5 sm:gap-1 overflow-x-auto">
          {TABS.map((tab) => {
            const isActive =
              tab.href === "/"
                ? pathname === "/"
                : pathname.startsWith(tab.href);

            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={`flex items-center gap-1 sm:gap-1.5 px-2.5 sm:px-4 py-3 text-xs sm:text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                  isActive
                    ? "border-blue-500 text-blue-400"
                    : "border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-600"
                }`}
              >
                <tab.Icon size={16} className="flex-shrink-0" />
                <span className="hidden sm:inline">{tab.label}</span>
                <span className="sm:hidden">{tab.label.replace(" ", "\n").split("\n")[0]}</span>
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
