"use client";

import {
  Zap,
  Clock,
  ShieldAlert,
  TrendingUp,
  TrendingDown,
  Target,
  Ban,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Layers,
  Users,
  BarChart3,
  Crosshair,
} from "lucide-react";
import { useState } from "react";

function Section({
  icon: Icon,
  title,
  color,
  children,
  defaultOpen = true,
}: {
  icon: typeof Zap;
  title: string;
  color: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-slate-700/50 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 bg-slate-800/80 hover:bg-slate-800 transition-colors"
      >
        <Icon size={14} className={color} />
        <span className="text-xs font-semibold text-white flex-1 text-left">{title}</span>
        {open ? <ChevronUp size={12} className="text-slate-500" /> : <ChevronDown size={12} className="text-slate-500" />}
      </button>
      {open && <div className="px-3 py-2.5 space-y-2 bg-slate-900/30">{children}</div>}
    </div>
  );
}

function ConditionRow({ label, value, badge }: { label: string; value: string; badge?: string }) {
  return (
    <div className="flex items-start gap-2 text-[11px]">
      <span className="text-slate-500 shrink-0 w-16">{label}</span>
      <span className="text-slate-300 flex-1">{value}</span>
      {badge && (
        <span className="text-[9px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400 shrink-0">
          {badge}
        </span>
      )}
    </div>
  );
}

function Tag({ children, color = "text-slate-400 bg-slate-700/50" }: { children: React.ReactNode; color?: string }) {
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded ${color}`}>{children}</span>
  );
}

export default function StrategyConditions() {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 space-y-3">
      <h3 className="text-sm font-semibold text-white flex items-center gap-2">
        <Layers size={16} className="text-purple-400" />
        전략 조건 총정리
      </h3>
      <p className="text-[10px] text-slate-500">
        홍인기 전략 기본 조건 + 경윤 3대 필터가 모두 적용됩니다
      </p>

      <div className="space-y-2">
        {/* 1. 종목 선별 */}
        <Section icon={Users} title="1단계: 종목 선별 (유니버스)" color="text-blue-400">
          <ConditionRow label="유니버스" value="거래대금 TOP100 또는 당일 등락률 +3% 이상 종목" />
          <ConditionRow label="리더선별" value="오전 모멘텀(거래량 × 상승률) TOP20 대장주" />
          <ConditionRow label="끼 점수" value="KI ≥ 20점 (90일 최대수익률 + 최대거래량비율)" badge="필수" />
          <ConditionRow label="집중투자" value="확신도 상위 5종목만 진입, 최대 2종목 보유" />
        </Section>

        {/* 2. 경윤 3대 필터 */}
        <Section icon={ShieldAlert} title="2단계: 경윤 3대 필터" color="text-purple-400">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-[11px]">
              <Tag color="text-purple-400 bg-purple-500/20">필터1</Tag>
              <span className="text-slate-300">시가총액 ≥ 5,000억원</span>
              <span className="text-[9px] text-green-400 ml-auto">WR +10%p</span>
            </div>
            <div className="flex items-center gap-2 text-[11px]">
              <Tag color="text-blue-400 bg-blue-500/20">필터2</Tag>
              <span className="text-slate-300">전일 기관 순매수 50~200억</span>
              <span className="text-[9px] text-green-400 ml-auto">WR +5%p</span>
            </div>
            <div className="flex items-center gap-2 text-[11px]">
              <Tag color="text-emerald-400 bg-emerald-500/20">필터3</Tag>
              <span className="text-slate-300">눌림매매 시: 깊이 ≥ 5% + 오전거래량 ≥ 중간값</span>
              <span className="text-[9px] text-green-400 ml-auto">48건 제거</span>
            </div>
          </div>
        </Section>

        {/* 3. 진입 조건 (돌파) */}
        <Section icon={Zap} title="3단계: 돌파매매 진입 (09:30~11:00)" color="text-yellow-400" defaultOpen={false}>
          <div className="flex gap-1.5 mb-1.5">
            <Tag color="text-yellow-400 bg-yellow-500/20">오전 전용</Tag>
            <Tag>확신도 0.7~0.8</Tag>
          </div>
          <ConditionRow label="신고가" value="52주/역대 고점 98%+ 돌파 → 확신도 0.8" />
          <ConditionRow label="전고점" value="20~60일 저항선 돌파 → 확신도 0.75" />
          <ConditionRow label="빈집" value="거래량 하위 25% 구간(매물대 없음) 돌파 → 확신도 0.7" />
          <div className="text-[10px] text-slate-500 mt-1">
            * 5봉 고점 돌파 + 거래량 1.2배 이상 확인
          </div>
        </Section>

        {/* 4. 진입 조건 (눌림) */}
        <Section icon={TrendingDown} title="3단계: 눌림매매 진입 (13:00~14:30)" color="text-cyan-400" defaultOpen={false}>
          <div className="flex gap-1.5 mb-1.5">
            <Tag color="text-cyan-400 bg-cyan-500/20">오후 전용</Tag>
            <Tag>확신도 0.6</Tag>
          </div>
          <ConditionRow label="바닥반등" value="20%+ 하락 후 MA20 돌파 확인" />
          <ConditionRow label="95%깊이" value="오전고점 대비 5% 이상 눌림만 진입" badge="경윤 필터" />
          <ConditionRow label="거래량" value="오전 거래량이 당일 리더 종목 중간값 이상" badge="경윤 필터" />
          <div className="text-[10px] text-slate-500 mt-1">
            * 오전고점 50% 되돌림선 위에서 반등 + 전일저가 미이탈
          </div>
        </Section>

        {/* 5. 시간대 전략 */}
        <Section icon={Clock} title="시간대 전략" color="text-orange-400" defaultOpen={false}>
          <div className="space-y-1">
            {[
              { time: "09:00~09:30", action: "시장 관찰", desc: "주도 섹터 확인, 변동성 파악" },
              { time: "09:30~11:00", action: "돌파매매", desc: "골든타임 - 돌파 시그널만 진입", color: "text-yellow-400" },
              { time: "11:00~13:00", action: "점심 휴식", desc: "신규 진입 금지, 보유 모니터링만" },
              { time: "13:00~14:30", action: "눌림매매", desc: "오후 눌림 반등 진입", color: "text-cyan-400" },
              { time: "14:30~15:20", action: "마감 정리", desc: "보유 포지션 모니터링, D+1 후보 선정" },
            ].map((row) => (
              <div key={row.time} className="flex items-center gap-2 text-[11px]">
                <span className="text-slate-500 font-mono w-[90px] shrink-0">{row.time}</span>
                <span className={`font-medium w-16 shrink-0 ${row.color ?? "text-slate-400"}`}>{row.action}</span>
                <span className="text-slate-500">{row.desc}</span>
              </div>
            ))}
          </div>
        </Section>

        {/* 6. 위험 패턴 */}
        <Section icon={Ban} title="위험 패턴 스킵 (6개)" color="text-red-400" defaultOpen={false}>
          <div className="grid grid-cols-2 gap-1.5">
            {[
              { name: "뉴스빵", desc: "비주도 섹터 뉴스 급등 (50% 실패)" },
              { name: "깊은눌림", desc: "50%+ 되돌림 (매물벽)" },
              { name: "끼소진", desc: "변동성 80%+ 소진" },
              { name: "3파동", desc: "3번째 상승파 완성" },
              { name: "가분수", desc: "3연속 양봉 + 거래량 3배" },
              { name: "거래량고점", desc: "최대거래량 + 윗꼬리 음봉" },
            ].map((p) => (
              <div key={p.name} className="flex items-start gap-1.5 text-[10px] p-1.5 rounded bg-red-500/5 border border-red-500/10">
                <AlertTriangle size={10} className="text-red-400 shrink-0 mt-0.5" />
                <div>
                  <span className="text-red-400 font-medium">{p.name}</span>
                  <span className="text-slate-500 ml-1">{p.desc}</span>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* 7. 리스크 관리 */}
        <Section icon={Target} title="리스크 관리" color="text-emerald-400" defaultOpen={false}>
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-[11px]">
              <Tag color="text-red-400 bg-red-500/20">손절</Tag>
              <span className="text-slate-300">-4% 전량 매도 (전저점 이탈 또는 고정)</span>
            </div>
            <div className="flex items-center gap-2 text-[11px]">
              <Tag color="text-green-400 bg-green-500/20">1차익절</Tag>
              <span className="text-slate-300">+5% 도달 시 70% 물량 매도</span>
            </div>
            <div className="flex items-center gap-2 text-[11px]">
              <Tag color="text-yellow-400 bg-yellow-500/20">본전컷</Tag>
              <span className="text-slate-300">1차 익절 후 원가 복귀 → 잔여 30% 전량 청산</span>
            </div>
            <div className="flex items-center gap-2 text-[11px]">
              <Tag color="text-orange-400 bg-orange-500/20">당일종료</Tag>
              <span className="text-slate-300">2연속 손절 시 당일 매매 전면 중지</span>
            </div>
          </div>
          <div className="mt-2 pt-2 border-t border-slate-700/50">
            <ConditionRow label="배분" value="확신 종목 50% / 보통 종목 30% (최대 80%)" />
            <ConditionRow label="확신기준" value="confidence ≥ 70% AND KI ≥ 50점" />
          </div>
        </Section>

        {/* 8. 패턴기반 청산 - 미검증 */}
        <Section icon={Crosshair} title="패턴 기반 청산" color="text-pink-400" defaultOpen={false}>
          <div className="flex items-center gap-1.5 mb-2 p-1.5 rounded bg-orange-500/10 border border-orange-500/20">
            <AlertTriangle size={10} className="text-orange-400 shrink-0" />
            <span className="text-[10px] text-orange-400">미검증 — 백테스트에 미포함. 홍인기 이론 기반 규칙 (현재 미적용)</span>
          </div>
          <div className="space-y-1.5 text-[11px] opacity-70">
            <div className="text-slate-300">보유 중 아래 패턴 감지 시 <span className="text-red-400 font-medium">즉시 전량 매도</span>:</div>
            <div className="flex gap-1.5 flex-wrap">
              <Tag color="text-red-400 bg-red-500/15">거래량고점</Tag>
              <Tag color="text-red-400 bg-red-500/15">끼소진</Tag>
              <Tag color="text-red-400 bg-red-500/15">가분수</Tag>
            </div>
            <div className="text-slate-300 mt-1">3파동 완성 감지 시 <span className="text-yellow-400 font-medium">50% 부분 매도</span> (수익 +2% 이상)</div>
          </div>
        </Section>
      </div>
    </div>
  );
}
