import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, setCsrfToken } from "../api/client";
import { keys, useMe } from "../api/hooks";
import type { Me } from "../api/types";
import { Logo, ThemeToggle } from "../components/Layout";
import { Banner, Spinner } from "../components/ui";

function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <div className="flex items-center justify-between px-4 py-4 sm:px-8">
        <Logo />
        <ThemeToggle />
      </div>
      <div className="flex flex-1 items-center justify-center px-4 pb-16">
        <div className="w-full max-w-sm">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-ink-muted">{subtitle}</p>
          <div className="card mt-6 p-5">{children}</div>
        </div>
      </div>
    </div>
  );
}

function useAuthSubmit(path: string) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (body: Record<string, string>) => {
    setBusy(true);
    setError(null);
    try {
      const me = await api<Me>(path, { method: "POST", body });
      setCsrfToken(me.csrf_token);
      qc.setQueryData(keys.me, me);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : "/", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return { submit, error, busy };
}

export function LoginPage() {
  const me = useMe();
  const { submit, error, busy } = useAuthSubmit("/api/auth/login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  if (me.data) return <Navigate to="/" replace />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit({ email, password });
  };
  return (
    <AuthShell title="로그인" subtitle="웹사이트 가동률과 장애를 한눈에 확인하세요.">
      <form onSubmit={onSubmit} className="space-y-4">
        {error && <Banner tone="down">{error}</Banner>}
        <div>
          <label htmlFor="email" className="label">
            이메일
          </label>
          <input id="email" type="email" autoComplete="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label htmlFor="password" className="label">
            비밀번호
          </label>
          <input id="password" type="password" autoComplete="current-password" required className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy && <Spinner />}
          로그인
        </button>
      </form>
      <p className="mt-4 text-center text-sm text-ink-muted">
        계정이 없나요?{" "}
        <Link to="/register" className="font-medium text-brand hover:underline">
          회원가입
        </Link>
      </p>
    </AuthShell>
  );
}

export function RegisterPage() {
  const me = useMe();
  const { submit, error, busy } = useAuthSubmit("/api/auth/register");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  if (me.data) return <Navigate to="/" replace />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (password.length < 8) {
      setLocalError("비밀번호는 8자 이상이어야 합니다.");
      return;
    }
    setLocalError(null);
    submit({ email, password, display_name: name });
  };
  return (
    <AuthShell title="회원가입" subtitle="계정을 만들고 첫 번째 모니터를 등록하세요.">
      <form onSubmit={onSubmit} className="space-y-4">
        {(localError || error) && <Banner tone="down">{localError || error}</Banner>}
        <div>
          <label htmlFor="name" className="label">
            이름 <span className="font-normal text-ink-faint">(선택)</span>
          </label>
          <input id="name" className="input" autoComplete="name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label htmlFor="email" className="label">
            이메일
          </label>
          <input id="email" type="email" autoComplete="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label htmlFor="password" className="label">
            비밀번호
          </label>
          <input id="password" type="password" autoComplete="new-password" required minLength={8} className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
          <p className="hint">8자 이상. Argon2id 로 해시해 저장합니다.</p>
        </div>
        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy && <Spinner />}
          가입하기
        </button>
      </form>
      <p className="mt-4 text-center text-sm text-ink-muted">
        이미 계정이 있나요?{" "}
        <Link to="/login" className="font-medium text-brand hover:underline">
          로그인
        </Link>
      </p>
    </AuthShell>
  );
}
