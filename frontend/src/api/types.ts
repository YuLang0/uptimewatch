export type MonitorStatus = "pending" | "up" | "down" | "paused";
export type Outcome = "up" | "down" | "error";

export interface User {
  id: number;
  email: string;
  display_name: string;
  created_at: string;
}

export interface Me {
  user: User;
  csrf_token: string;
}

export interface Monitor {
  id: number;
  name: string;
  description: string;
  url: string;
  method: "GET" | "HEAD";
  interval_seconds: number;
  timeout_seconds: number;
  expected_status: string;
  failure_threshold: number;
  recovery_threshold: number;
  follow_redirects: boolean;
  is_active: boolean;
  status: MonitorStatus;
  status_changed_at: string | null;
  consecutive_failures: number;
  consecutive_successes: number;
  last_checked_at: string | null;
  last_outcome: Outcome | null;
  last_status_code: number | null;
  last_response_time_ms: number | null;
  last_error_type: string | null;
  last_error_message: string | null;
  next_check_at: string | null;
  manual_check_requested_at: string | null;
  tls_expires_at: string | null;
  created_at: string;
  updated_at: string;
  uptime_24h?: number | null;
  avg_response_24h?: number | null;
  open_incident_id?: number | null;
}

export interface MonitorInput {
  name: string;
  description: string;
  url: string;
  method: "GET" | "HEAD";
  interval_seconds: number;
  timeout_seconds: number;
  expected_status: string;
  failure_threshold: number;
  recovery_threshold: number;
  follow_redirects: boolean;
  is_active?: boolean;
}

export interface CheckResult {
  id: number;
  checked_at: string;
  outcome: Outcome;
  status_code: number | null;
  response_time_ms: number | null;
  error_type: string | null;
  error_message: string | null;
  redirect_count: number;
  is_manual: boolean;
}

export interface WindowStats {
  window: "24h" | "7d" | "30d";
  start: string;
  end: string;
  up_checks: number;
  down_checks: number;
  unknown_checks: number;
  uptime_pct: number | null;
  coverage_pct: number | null;
  avg_response_ms: number | null;
  max_response_ms: number | null;
  min_response_ms: number | null;
  p95_response_ms: number | null;
  incidents: number;
  downtime_seconds: number;
}

export type StatsResponse = Record<"24h" | "7d" | "30d", WindowStats>;

export interface SeriesPoint {
  t: string;
  avg_ms: number | null;
  max_ms: number | null;
  min_ms: number | null;
  up: number;
  down: number;
  unknown: number;
  uptime_pct: number | null;
}

export interface DailyPoint {
  date: string;
  up?: number;
  down?: number;
  unknown?: number;
  uptime_pct: number | null;
  avg_ms?: number | null;
  incidents: number;
}

export interface Incident {
  id: number;
  monitor_id: number;
  monitor_name: string;
  started_at: string;
  detected_at: string;
  resolved_at: string | null;
  duration_seconds: number | null;
  ongoing_seconds: number | null;
  cause_type: string | null;
  cause_message: string | null;
  failed_checks: number;
}

export interface Dashboard {
  counts: { total: number; up: number; down: number; paused: number; pending: number };
  uptime_24h: number | null;
  avg_response_24h: number | null;
  incidents_24h: number;
  open_incidents: Incident[];
  unread_notifications: number;
  worker: { status: "ok" | "stale" | "never"; last_seen_at: string | null };
  email: { configured: boolean };
}

export interface AppNotification {
  id: number;
  monitor_id: number | null;
  incident_id: number | null;
  kind: "down" | "up" | "reminder" | "tls_expiring" | "test";
  title: string;
  message: string;
  created_at: string;
  read_at: string | null;
}

export type DeliveryStatus = "pending" | "sent" | "failed" | "skipped" | "suppressed";

export interface Delivery {
  id: number;
  notification_id: number;
  monitor_id: number | null;
  kind: string;
  channel: string;
  recipient: string;
  status: DeliveryStatus;
  attempts: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface Channels {
  dashboard: { configured: boolean };
  email: {
    configured: boolean;
    status: "connected" | "not_configured";
    from: string | null;
    enabled: boolean;
    recipient: string;
    required_env: string[];
  };
}

export interface NotificationSettings {
  email_enabled: boolean;
  email_to: string | null;
  email_cooldown_minutes: number;
  reminder_interval_minutes: number;
  tls_warning_days: number;
}

export interface TestNotificationResult {
  dashboard: { status: string; notification_id: number };
  email: { status: DeliveryStatus | "disabled"; error: string | null; recipient?: string };
}

export interface StatusPageItem {
  monitor_id: number;
  display_name: string;
  sort_order?: number;
}

export interface StatusPage {
  id: number;
  slug: string;
  title: string;
  description: string;
  is_published: boolean;
  show_uptime: boolean;
  show_response_times: boolean;
  show_incidents: boolean;
  items: StatusPageItem[];
  created_at: string;
  updated_at: string;
}

export type StatusPageInput = Omit<StatusPage, "id" | "created_at" | "updated_at">;

export type PublicStatus = "up" | "down" | "paused" | "unknown";

export interface PublicStatusPage {
  title: string;
  description: string;
  overall: "operational" | "partial_outage" | "major_outage" | "unknown";
  generated_at: string;
  show_uptime: boolean;
  show_response_times: boolean;
  show_incidents: boolean;
  components: {
    key: string;
    name: string;
    status: PublicStatus;
    last_checked_at: string | null;
    uptime?: Record<"24h" | "7d" | "30d", number | null>;
    daily?: DailyPoint[];
    response_times?: { t: string; avg_ms: number | null }[];
  }[];
  incidents: {
    component: string;
    started_at: string;
    resolved_at: string | null;
    duration_seconds: number | null;
    ongoing: boolean;
  }[];
}
