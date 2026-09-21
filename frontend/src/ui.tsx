import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonIntent = "primary" | "neutral" | "warning" | "danger";
type ButtonEmphasis = "solid" | "outline" | "ghost";

export function ActivitySpinner({
  label = "Lädt",
  size = "md",
}: {
  label?: string;
  size?: "sm" | "md";
}) {
  return (
    <span className={`uiSpinner uiSpinner-${size}`} role="status" aria-label={label}>
      <span aria-hidden="true" />
    </span>
  );
}

export function ActionButton({
  busy = false,
  intent = "neutral",
  emphasis = "outline",
  children,
  className = "",
  disabled,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  busy?: boolean;
  intent?: ButtonIntent;
  emphasis?: ButtonEmphasis;
}) {
  const classes = [
    "uiButton",
    `uiButton-${intent}`,
    `uiButton-${emphasis}`,
    busy ? "is-busy" : "",
    className,
  ].filter(Boolean).join(" ");

  return (
    <button
      {...props}
      type={type}
      className={classes}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
    >
      <span className="uiButtonLabel">{children}</span>
      {busy ? <ActivitySpinner label="Aktion läuft" size="sm" /> : null}
    </button>
  );
}

export function LoadingBlock({
  label = "Daten werden geladen",
  compact = false,
}: {
  label?: string;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "uiLoadingBlock compact" : "uiLoadingBlock"} aria-live="polite">
      <ActivitySpinner label={label} />
      <span>{label}</span>
    </div>
  );
}

export function InlineNotice({
  tone = "info",
  title,
  children,
  action,
  className = "",
}: {
  tone?: "info" | "warning" | "error" | "success";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const role = tone === "error" ? "alert" : "status";
  return (
    <div className={`uiNotice uiNotice-${tone} ${className}`.trim()} role={role}>
      <div className="uiNoticeCopy">
        <strong>{title}</strong>
        {children ? <span>{children}</span> : null}
      </div>
      {action ? <div className="uiNoticeAction">{action}</div> : null}
    </div>
  );
}
