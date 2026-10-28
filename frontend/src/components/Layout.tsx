import { NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api, setCsrfToken } from "../api/client";
import { useDashboard, useMe } from "../api/hooks";
import { useTheme } from "../lib/theme";
import { Icon } from "./Icon";
import { PageLoader } from "./ui";

const NAV = [
  { to: "/", label: "대시보드", icon: "dashboard", end: true },
  { to: "/incidents", label: "장애 기록", icon: "incident" },
  { to: "/notifications", label: "알림", icon: "bell" },
  { to: "/status-pages", label: "상태 페이지", icon: "globe" },
];

export function Logo({ className }: { className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-2 font-semibold tracking-tight text-ink", className)}>
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-ink text-surface">
        <Icon name="pulse" className="h-4 w-4 text-up" strokeWidth={2.6} />
      </span>
      UptimeWatch
    </span>
  );
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <button
      type="button"
      onClick={toggle}
      className="btn-ghost h-9 w-9 p-0"
      aria-label={theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환"}
      title={theme === "dark" ? "라이트 모드" : "다크 모드"}
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} className="h-4.5 w-4.5 h-[18px] w-[18px]" />
    </button>
  );
}

/** 로그인 필요 영역의 레이아웃 (공개 상태 페이지와 완전히 분리) */
export function AppLayout() {
  const me = useMe();
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const dashboard = useDashboard();
  const unread = dashboard.data?.unread_notifications ?? 0;

  if (me.isLoading) return <PageLoader />;
  if (me.isError || !me.data) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  setCsrfToken(me.data.csrf_token);

  const logout = async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      setCsrfToken(null);
      qc.clear();
      navigate("/login", { replace: true });
    }
  };

  return (
    <div className="min-h-screen md:flex">
      {/* 데스크톱 사이드바 */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-surface md:flex">
        <div className="px-5 py-5">
          <Logo />
        </div>
        <nav className="flex-1 space-y-0.5 px-3" aria-label="주 메뉴">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition",
                  isActive ? "bg-surface-sunken text-ink" : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
                )
              }
            >
              <Icon name={n.icon} className="h-4 w-4" />
              {n.label}
              {n.to === "/notifications" && unread > 0 && (
                <span className="ml-auto rounded-full bg-down px-1.5 text-[11px] font-semibold text-white tabular" data-testid="unread-badge">
                  {unread > 99 ? "99+" : unread}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-line p-3">
          <div className="truncate px-2 text-xs text-ink-faint" title={me.data.user.email}>
            {me.data.user.email}
          </div>
          <div className="mt-2 flex items-center justify-between">
            <ThemeToggle />
            <button type="button" onClick={logout} className="btn-ghost text-xs">
              <Icon name="logout" className="h-4 w-4" />
              로그아웃
            </button>
          </div>
        </div>
      </aside>

      {/* 모바일 상단 바 */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-surface/95 px-4 py-2.5 backdrop-blur md:hidden">
        <Logo />
        <div className="flex items-center gap-1">
          <ThemeToggle />
          <button type="button" onClick={logout} className="btn-ghost h-9 w-9 p-0" aria-label="로그아웃">
            <Icon name="logout" className="h-[18px] w-[18px]" />
          </button>
        </div>
      </header>

      <main className="min-w-0 flex-1 px-4 pb-24 pt-5 sm:px-6 md:pb-10 lg:px-8">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>

      {/* 모바일 하단 탭 */}
      <nav
        aria-label="모바일 메뉴"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
      >
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              clsx(
                "relative flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium",
                isActive ? "text-ink" : "text-ink-faint",
              )
            }
          >
            <Icon name={n.icon} className="h-5 w-5" />
            {n.label}
            {n.to === "/notifications" && unread > 0 && (
              <span className="absolute right-[calc(50%-18px)] top-1 h-2 w-2 rounded-full bg-down" aria-label={`읽지 않은 알림 ${unread}개`} />
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 text-sm text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
