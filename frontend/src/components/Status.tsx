import clsx from "clsx";
import type { MonitorStatus, PublicStatus } from "../api/types";
import { monitorStatusView, type StatusView } from "../lib/format";
import { Icon } from "./Icon";

const dotColor: Record<StatusView["key"], string> = {
  up: "bg-up",
  down: "bg-down",
  degraded: "bg-warn",
  paused: "bg-ink-faint",
  pending: "bg-nodata",
};

const iconFor: Record<StatusView["key"], string> = {
  up: "check",
  down: "x",
  degraded: "alert",
  paused: "pause",
  pending: "clock",
};

export function StatusDot({ view, size = "md" }: { view: StatusView; size?: "sm" | "md" | "lg" }) {
  const dims = size === "lg" ? "h-3.5 w-3.5" : size === "sm" ? "h-2 w-2" : "h-2.5 w-2.5";
  return (
    <span className={clsx("relative inline-flex shrink-0", dims)} aria-hidden="true">
      {view.key === "down" && (
        <span className={clsx("absolute inline-flex h-full w-full rounded-full bg-down animate-pulse-ring")} />
      )}
      <span className={clsx("relative inline-flex rounded-full", dims, dotColor[view.key])} />
    </span>
  );
}

/** 상태 배지: 색상 + 아이콘 + 텍스트를 함께 사용(색상만으로 의미 전달하지 않음) */
export function StatusBadge({
  status,
  consecutiveFailures = 0,
  view: viewProp,
}: {
  status?: MonitorStatus;
  consecutiveFailures?: number;
  view?: StatusView;
}) {
  const view = viewProp ?? monitorStatusView(status ?? "pending", consecutiveFailures);
  return (
    <span
      data-testid="status-badge"
      data-status={view.key}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold",
        view.key === "up" && "border-up/30 bg-up/10 text-ink",
        view.key === "down" && "border-down/40 bg-down/10 text-ink",
        view.key === "degraded" && "border-warn/50 bg-warn/15 text-ink",
        (view.key === "paused" || view.key === "pending") && "border-line bg-surface-sunken text-ink-muted",
      )}
    >
      <span
        className={clsx(
          "inline-flex h-3.5 w-3.5 items-center justify-center rounded-full text-white",
          dotColor[view.key],
          view.key === "degraded" && "text-black",
        )}
      >
        <Icon name={iconFor[view.key]} className="h-2.5 w-2.5" strokeWidth={3.5} />
      </span>
      {view.label}
    </span>
  );
}

export function publicStatusView(status: PublicStatus): StatusView {
  switch (status) {
    case "up":
      return { key: "up", label: "정상 운영" };
    case "down":
      return { key: "down", label: "장애" };
    case "paused":
      return { key: "paused", label: "점검 중" };
    default:
      return { key: "pending", label: "확인 중" };
  }
}
