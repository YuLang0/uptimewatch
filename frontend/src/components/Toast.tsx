import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import clsx from "clsx";
import { Icon } from "./Icon";

type Kind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: Kind;
  message: string;
}

const Ctx = createContext<(message: string, kind?: Kind) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((message: string, kind: Kind = "success") => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev.slice(-3), { id, kind, message }]);
    window.setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 4500);
  }, []);

  return (
    <Ctx.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4 md:bottom-6 md:items-end md:pr-6"
      >
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            className={clsx(
              "pointer-events-auto flex max-w-md items-start gap-2 rounded-lg border bg-surface px-4 py-3 text-sm shadow-lg",
              t.kind === "error" ? "border-down/40" : "border-line",
            )}
          >
            <Icon
              name={t.kind === "error" ? "alert" : t.kind === "info" ? "info" : "check"}
              className={clsx("mt-0.5 h-4 w-4 shrink-0", t.kind === "error" ? "text-down" : t.kind === "info" ? "text-brand" : "text-up")}
            />
            <span className="text-ink">{t.message}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
