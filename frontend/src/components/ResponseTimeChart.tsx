import { useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { TooltipProps } from "recharts";
import type { Range } from "../api/hooks";
import { formatMs, formatPercent } from "../lib/format";
import { Icon } from "./Icon";

interface Point {
  t: string;
  avg_ms: number | null;
  max_ms?: number | null;
  min_ms?: number | null;
  up?: number;
  down?: number;
  uptime_pct?: number | null;
}

const tickFmt: Record<Range, Intl.DateTimeFormat> = {
  "24h": new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false }),
  "7d": new Intl.DateTimeFormat("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", hour12: false }),
  "30d": new Intl.DateTimeFormat("ko-KR", { month: "numeric", day: "numeric" }),
};
const fullFmt = new Intl.DateTimeFormat("ko-KR", {
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function ChartTooltip({ active, payload, range }: TooltipProps<number, string> & { range: Range }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as Point;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="text-base font-semibold text-ink tabular">
        {p.avg_ms === null ? "데이터 없음" : formatMs(p.avg_ms)}
      </div>
      <div className="flex items-center gap-1.5 text-ink-muted">
        <span className="inline-block h-0.5 w-3 rounded bg-brand" />
        평균 응답 시간 · {range === "30d" ? new Date(p.t).toLocaleDateString("ko-KR") : fullFmt.format(new Date(p.t))}
      </div>
      {p.avg_ms !== null && p.max_ms !== undefined && (
        <div className="mt-1 text-ink-faint tabular">
          최소 {formatMs(p.min_ms)} · 최대 {formatMs(p.max_ms)}
        </div>
      )}
      {p.uptime_pct !== undefined && p.uptime_pct !== null && (
        <div className="text-ink-faint tabular">
          가동률 {formatPercent(p.uptime_pct)} ({p.up}/{(p.up ?? 0) + (p.down ?? 0)})
        </div>
      )}
    </div>
  );
}

/**
 * 응답 시간 그래프(단일 시리즈 → 범례 없음, 제목이 시리즈를 설명).
 * 측정이 없는 구간은 선을 끊어 공백으로 표시합니다(0 이나 보간값으로 채우지 않음).
 * '표로 보기'로 같은 데이터를 표로 확인할 수 있습니다.
 */
export function ResponseTimeChart({
  points,
  range,
  height = 240,
  loading = false,
}: {
  points: Point[];
  range: Range;
  height?: number;
  loading?: boolean;
}) {
  const [asTable, setAsTable] = useState(false);
  const hasData = useMemo(() => points.some((p) => p.avg_ms !== null), [points]);

  return (
    <div className="relative">
      <div className="mb-2 flex justify-end">
        <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => setAsTable((v) => !v)}>
          <Icon name={asTable ? "chart" : "table"} className="h-3.5 w-3.5" />
          {asTable ? "그래프로 보기" : "표로 보기"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-72 overflow-auto rounded-lg border border-line">
          <table className="w-full text-left text-xs tabular">
            <thead className="sticky top-0 bg-surface-sunken text-ink-muted">
              <tr>
                <th className="px-3 py-2 font-medium">시각</th>
                <th className="px-3 py-2 text-right font-medium">평균</th>
                <th className="px-3 py-2 text-right font-medium">최대</th>
                <th className="px-3 py-2 text-right font-medium">가동률</th>
              </tr>
            </thead>
            <tbody>
              {[...points].reverse().map((p) => (
                <tr key={p.t} className="border-t border-line">
                  <td className="px-3 py-1.5 text-ink-muted">{fullFmt.format(new Date(p.t))}</td>
                  <td className="px-3 py-1.5 text-right">{p.avg_ms === null ? "—" : formatMs(p.avg_ms)}</td>
                  <td className="px-3 py-1.5 text-right">{formatMs(p.max_ms ?? null)}</td>
                  <td className="px-3 py-1.5 text-right">
                    {p.uptime_pct === undefined || p.uptime_pct === null ? "—" : formatPercent(p.uptime_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ height }} className={loading ? "opacity-60 transition-opacity" : "transition-opacity"}>
          {hasData ? (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="rt-wash" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgb(var(--brand))" stopOpacity={0.14} />
                    <stop offset="100%" stopColor="rgb(var(--brand))" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="rgb(var(--grid))" strokeWidth={1} />
                <XAxis
                  dataKey="t"
                  tickFormatter={(v: string) => tickFmt[range].format(new Date(v))}
                  tick={{ fill: "rgb(var(--ink-faint))", fontSize: 11 }}
                  axisLine={{ stroke: "rgb(var(--line))" }}
                  tickLine={false}
                  minTickGap={32}
                />
                <YAxis
                  tickFormatter={(v: number) => formatMs(v)}
                  tick={{ fill: "rgb(var(--ink-faint))", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  width={52}
                  allowDecimals={false}
                />
                <Tooltip
                  content={<ChartTooltip range={range} />}
                  cursor={{ stroke: "rgb(var(--ink-faint))", strokeWidth: 1 }}
                  isAnimationActive={false}
                />
                <Area
                  type="monotone"
                  dataKey="avg_ms"
                  stroke="none"
                  fill="url(#rt-wash)"
                  connectNulls={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="avg_ms"
                  stroke="rgb(var(--brand))"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  dot={(props: { cx?: number; cy?: number; index?: number }) => {
                    // 앞뒤가 비어 있는 고립된 측정점은 선으로 이어지지 않으므로 점으로 표시
                    const i = props.index ?? 0;
                    const isolated =
                      points[i]?.avg_ms !== null &&
                      (points[i - 1]?.avg_ms ?? null) === null &&
                      (points[i + 1]?.avg_ms ?? null) === null;
                    if (!isolated || props.cx === undefined || props.cy === undefined) return <g key={`d${i}`} />;
                    return (
                      <circle key={`d${i}`} cx={props.cx} cy={props.cy} r={4} fill="rgb(var(--brand))" stroke="rgb(var(--surface))" strokeWidth={2} />
                    );
                  }}
                  activeDot={{ r: 4, fill: "rgb(var(--brand))", stroke: "rgb(var(--surface))", strokeWidth: 2 }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-line text-sm text-ink-faint">
              {loading ? "불러오는 중…" : "이 기간에 측정된 응답이 없습니다."}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
