import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../api/client";
import { keys, useMonitor } from "../api/hooks";
import type { Monitor, MonitorInput } from "../api/types";
import { PageHeader } from "../components/Layout";
import { DEFAULT_MONITOR, MonitorForm } from "../components/MonitorForm";
import { useToast } from "../components/Toast";
import { PageLoader } from "../components/ui";

export function MonitorNewPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: (body: MonitorInput) => api<Monitor>("/api/monitors", { method: "POST", body }),
    onSuccess: (m) => {
      qc.invalidateQueries({ queryKey: keys.monitors });
      qc.invalidateQueries({ queryKey: keys.dashboard });
      toast(`'${m.name}' 모니터를 추가했습니다. 곧 첫 검사가 실행됩니다.`);
      navigate(`/monitors/${m.id}`);
    },
    onError: (err) => {
      setError(errorMessage(err));
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
  });
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="새 모니터" description="확인할 웹사이트와 검사·장애 판정 기준을 설정하세요." />
      <MonitorForm initial={DEFAULT_MONITOR} submitting={create.isPending} serverError={error} onSubmit={(v) => create.mutate(v)} onCancel={() => navigate(-1)} />
    </div>
  );
}

export function MonitorEditPage() {
  const id = Number(useParams().id);
  const monitor = useMonitor(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const update = useMutation({
    mutationFn: (body: MonitorInput) => {
      const { is_active: _ignored, ...rest } = body;
      return api<Monitor>(`/api/monitors/${id}`, { method: "PATCH", body: rest });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.monitors });
      qc.invalidateQueries({ queryKey: keys.monitor(id) });
      toast("변경 사항을 저장했습니다.");
      navigate(`/monitors/${id}`);
    },
    onError: (err) => {
      setError(errorMessage(err));
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
  });
  if (monitor.isLoading || !monitor.data) return <PageLoader />;
  const m = monitor.data;
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="모니터 수정" description={m.name} />
      <MonitorForm
        isEdit
        initial={{
          name: m.name,
          description: m.description,
          url: m.url,
          method: m.method,
          interval_seconds: m.interval_seconds,
          timeout_seconds: m.timeout_seconds,
          expected_status: m.expected_status,
          failure_threshold: m.failure_threshold,
          recovery_threshold: m.recovery_threshold,
          follow_redirects: m.follow_redirects,
        }}
        submitting={update.isPending}
        serverError={error}
        onSubmit={(v) => update.mutate(v)}
        onCancel={() => navigate(-1)}
      />
    </div>
  );
}
