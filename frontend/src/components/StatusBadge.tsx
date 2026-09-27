import type { ReactNode } from "react";
import type { Tone } from "../labels";

export function StatusBadge({
  tone = "muted",
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
