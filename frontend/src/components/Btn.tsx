import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "ghost" | "danger" | "text";

export function Btn({
  children,
  title,
  hint,
  variant = "primary",
  busy,
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  title: string;
  hint?: string;
  variant?: Variant;
  busy?: boolean;
}) {
  const disabled = Boolean(props.disabled || busy);
  const reason = disabled ? hint || (busy ? "Дождитесь завершения действия" : title) : title;
  const kind = variant === "primary" ? "btn" : variant === "text" ? "text-link" : `btn ${variant}`;
  const { ["aria-label"]: ariaLabel, ...rest } = props;
  return (
    <button
      type={type}
      className={`${kind} ${busy ? "is-busy" : ""} ${className}`.trim()}
      title={reason}
      aria-label={ariaLabel || title}
      aria-busy={busy || undefined}
      {...rest}
      disabled={disabled}
    >
      {children}
    </button>
  );
}
