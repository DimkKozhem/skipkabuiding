import { useEffect, useId, useState } from "react";
import { fmtDotDate } from "../labels";

function isoDay(value?: string | null) {
  const day = String(value || "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : "";
}

function ruToIso(value: string) {
  const match = value.trim().match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (!match) return "";
  const day = Number(match[1]);
  const month = Number(match[2]);
  const year = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return "";
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return "";
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Дата `дд.мм.гггг` одинаково во всех браузерах. Календарь открывается системной кнопкой. */
export function RuDateField({
  name,
  id,
  required,
  value,
  defaultValue,
  onChange,
  onBlur,
  className,
  label,
}: {
  name?: string;
  id?: string;
  required?: boolean;
  value?: string;
  defaultValue?: string;
  onChange?: (iso: string) => void;
  onBlur?: (iso: string) => void;
  className?: string;
  label?: string;
}) {
  const autoId = useId();
  const fieldId = id || autoId;
  const controlled = value !== undefined;
  const [iso, setIso] = useState(isoDay(value ?? defaultValue));
  const [text, setText] = useState(isoDay(value ?? defaultValue) ? fmtDotDate(isoDay(value ?? defaultValue)) : "");

  useEffect(() => {
    if (!controlled) return;
    const next = isoDay(value);
    setIso(next);
    setText(next ? fmtDotDate(next) : "");
  }, [controlled, value]);

  function apply(next: string) {
    setIso(next);
    setText(next ? fmtDotDate(next) : "");
    onChange?.(next);
  }

  return (
    <span className={className ? `ru-date ${className}` : "ru-date"}>
      <input
        id={fieldId}
        className="ru-date-text"
        inputMode="numeric"
        autoComplete="off"
        placeholder="дд.мм.гггг"
        aria-label={label}
        value={text}
        onChange={event => {
          const raw = event.target.value;
          setText(raw);
          const parsed = ruToIso(raw);
          if (parsed) {
            setIso(parsed);
            onChange?.(parsed);
          } else if (!raw.trim()) {
            setIso("");
            onChange?.("");
          }
        }}
        onBlur={() => {
          const parsed = ruToIso(text);
          if (parsed) apply(parsed);
          else if (!text.trim()) apply("");
          else setText(iso ? fmtDotDate(iso) : "");
          onBlur?.(parsed || (text.trim() ? iso : ""));
        }}
      />
      <input
        className="ru-date-native"
        type="date"
        name={name}
        required={required}
        value={iso}
        aria-label={label ? `${label}, календарь` : "Календарь"}
        onChange={event => {
          apply(event.target.value);
          onBlur?.(event.target.value);
        }}
      />
    </span>
  );
}
