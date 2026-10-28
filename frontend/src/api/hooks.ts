import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type {
  AppNotification,
  Channels,
  CheckResult,
  DailyPoint,
  Dashboard,
  Delivery,
  Incident,
  Me,
  Monitor,
  NotificationSettings,
  PublicStatusPage,
  SeriesPoint,
  StatsResponse,
  StatusPage,
} from "./types";

export type Range = "24h" | "7d" | "30d";

export const keys = {
  me: ["me"] as const,
  dashboard: ["dashboard"] as const,
  monitors: ["monitors"] as const,
  monitor: (id: number) => ["monitors", id] as const,
  incidents: (state: string) => ["incidents", state] as const,
  notifications: ["notifications"] as const,
  deliveries: (status: string) => ["deliveries", status] as const,
  channels: ["channels"] as const,
  notificationSettings: ["notification-settings"] as const,
  statusPages: ["status-pages"] as const,
};

export const useMe = () =>
  useQuery({ queryKey: keys.me, queryFn: () => api<Me>("/api/auth/me"), retry: false, staleTime: 60_000 });

export const useDashboard = () =>
  useQuery({ queryKey: keys.dashboard, queryFn: () => api<Dashboard>("/api/dashboard"), refetchInterval: 15_000 });

export const useMonitors = () =>
  useQuery({ queryKey: keys.monitors, queryFn: () => api<Monitor[]>("/api/monitors"), refetchInterval: 15_000 });

export const useMonitor = (id: number, fast = false) =>
  useQuery({
    queryKey: keys.monitor(id),
    queryFn: () => api<Monitor>(`/api/monitors/${id}`),
    refetchInterval: fast ? 2_000 : 15_000,
  });

export const useMonitorStats = (id: number) =>
  useQuery({
    queryKey: [...keys.monitor(id), "stats"],
    queryFn: () => api<StatsResponse>(`/api/monitors/${id}/stats`),
    refetchInterval: 30_000,
  });

export const useResponseTimes = (id: number, range: Range, enabled = true) =>
  useQuery({
    queryKey: [...keys.monitor(id), "series", range],
    queryFn: () => api<{ range: Range; points: SeriesPoint[] }>(`/api/monitors/${id}/response-times?range=${range}`),
    refetchInterval: 60_000,
    placeholderData: (prev) => prev,
    enabled,
  });

export const useDailyUptime = (id: number, days: number) =>
  useQuery({
    queryKey: [...keys.monitor(id), "daily", days],
    queryFn: () => api<{ days: DailyPoint[] }>(`/api/monitors/${id}/daily-uptime?days=${days}`),
    refetchInterval: 60_000,
  });

export const useMonitorIncidents = (id: number) =>
  useQuery({
    queryKey: [...keys.monitor(id), "incidents"],
    queryFn: () => api<Incident[]>(`/api/monitors/${id}/incidents?limit=50`),
    refetchInterval: 30_000,
  });

export const useChecks = (id: number, outcome: "all" | "down") =>
  useQuery({
    queryKey: [...keys.monitor(id), "checks", outcome],
    queryFn: () => api<CheckResult[]>(`/api/monitors/${id}/checks?limit=50${outcome === "down" ? "&outcome=down" : ""}`),
    refetchInterval: 15_000,
  });

export const useIncidents = (state: "all" | "ongoing" | "resolved") =>
  useQuery({
    queryKey: keys.incidents(state),
    queryFn: () => api<Incident[]>(`/api/incidents?state=${state}&limit=200`),
    refetchInterval: 30_000,
  });

export const useNotifications = () =>
  useQuery({
    queryKey: keys.notifications,
    queryFn: () => api<AppNotification[]>("/api/notifications?limit=100"),
    refetchInterval: 20_000,
  });

export const useDeliveries = (status: string) =>
  useQuery({
    queryKey: keys.deliveries(status),
    queryFn: () => api<Delivery[]>(`/api/notifications/deliveries?limit=100${status !== "all" ? `&status=${status}` : ""}`),
    refetchInterval: 30_000,
  });

export const useChannels = () =>
  useQuery({ queryKey: keys.channels, queryFn: () => api<Channels>("/api/notifications/channels") });

export const useNotificationSettings = () =>
  useQuery({
    queryKey: keys.notificationSettings,
    queryFn: () => api<NotificationSettings>("/api/notifications/settings"),
  });

export const useStatusPages = () =>
  useQuery({ queryKey: keys.statusPages, queryFn: () => api<StatusPage[]>("/api/status-pages") });

export const usePublicStatus = (slug: string) =>
  useQuery({
    queryKey: ["public-status", slug],
    queryFn: () => api<PublicStatusPage>(`/api/public/status/${encodeURIComponent(slug)}`),
    refetchInterval: 60_000,
    retry: false,
  });
