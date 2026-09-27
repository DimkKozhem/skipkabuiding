import type { ReactNode } from "react";
import { Icon } from "./Icon";
export function LoadingState({ text = "Загрузка…" }: { text?: string }) {
  return (
    <div className="loading-state drawing" role="status" aria-busy="true">
      <span className="sr-only">{text}</span>
      <DrawingSheet />
      <p className="caption">{text}</p>
    </div>
  );
}

function DrawingSheet() {
  return (
    <svg className="drawing-sheet" viewBox="0 0 640 220" aria-hidden="true">
      <g className="drawing-lines">
        <path d="M32 28 H608" />
        <path d="M32 28 V196" />
        <path d="M32 196 H608" />
        <path d="M608 28 V196" />
        <path d="M32 92 H420" />
        <path d="M180 28 V196" />
        <path d="M420 28 V196" />
        <path d="M180 140 H420" />
        <path d="M48 48 H96" />
        <path d="M48 48 V72" />
      </g>
      <circle className="drawing-mark" cx="420" cy="140" r="3.5" />
    </svg>
  );
}
export function ErrorState({ text, onRetry }: { text: string; onRetry?: () => void }) {
  const friendly = /\{|zone|uuid|traceback|exception|status code|http/i.test(text)
    ? "Не удалось получить данные. Проверьте соединение и попробуйте снова."
    : text;
  return (
    <div className="error-state" role="alert">
      <Icon name="signal" />
      <h3>Не удалось загрузить данные</h3>
      <p>{friendly}</p>
      <button type="button" className="btn ghost" onClick={onRetry || (() => window.location.reload())}>Повторить</button>
    </div>
  );
}
export function EmptyState({ title, text, action }: { title: string; text: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <DrawingSheet />
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
export function DemoSourceBanner() {
  return <p className="source-banner" role="note">Кадры учебные: разметка-аннотации, не полевая модель. Решение по-прежнему принимает инспектор.</p>;
}
