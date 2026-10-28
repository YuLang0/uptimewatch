import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/Layout";
import { PageLoader } from "./components/ui";

// 공개 상태 페이지와 관리자 화면은 별도 청크로 분리됩니다.
const PublicStatusPage = lazy(() => import("./pages/PublicStatusPage").then((m) => ({ default: m.PublicStatusPage })));
const LoginPage = lazy(() => import("./pages/AuthPages").then((m) => ({ default: m.LoginPage })));
const RegisterPage = lazy(() => import("./pages/AuthPages").then((m) => ({ default: m.RegisterPage })));
const DashboardPage = lazy(() => import("./pages/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const MonitorDetailPage = lazy(() => import("./pages/MonitorDetailPage").then((m) => ({ default: m.MonitorDetailPage })));
const MonitorNewPage = lazy(() => import("./pages/MonitorEditPage").then((m) => ({ default: m.MonitorNewPage })));
const MonitorEditPage = lazy(() => import("./pages/MonitorEditPage").then((m) => ({ default: m.MonitorEditPage })));
const IncidentsPage = lazy(() => import("./pages/IncidentsPage").then((m) => ({ default: m.IncidentsPage })));
const NotificationsPage = lazy(() => import("./pages/NotificationsPage").then((m) => ({ default: m.NotificationsPage })));
const StatusPagesPage = lazy(() => import("./pages/StatusPagesPage").then((m) => ({ default: m.StatusPagesPage })));

function NotFound() {
  return (
    <div className="py-24 text-center">
      <h1 className="text-xl font-semibold">페이지를 찾을 수 없습니다</h1>
      <a href="/" className="mt-3 inline-block text-sm text-brand underline">
        대시보드로 이동
      </a>
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        {/* 공개 영역 (인증 불필요) */}
        <Route path="/status/:slug" element={<PublicStatusPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />

        {/* 관리자 영역 (로그인 필요) */}
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="monitors/new" element={<MonitorNewPage />} />
          <Route path="monitors/:id" element={<MonitorDetailPage />} />
          <Route path="monitors/:id/edit" element={<MonitorEditPage />} />
          <Route path="incidents" element={<IncidentsPage />} />
          <Route path="notifications" element={<NotificationsPage />} />
          <Route path="status-pages" element={<StatusPagesPage />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  );
}
