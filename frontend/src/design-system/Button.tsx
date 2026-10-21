import type { ComponentProps, ReactNode } from "react";
import { Spinner } from "./Spinner";

import styles from "./Button.module.css";

type ButtonVariant = "primary" | "secondary" | "danger" | "quiet";

export type ButtonProps = ComponentProps<"button"> & {
  icon?: ReactNode;
  loading?: boolean;
  /** Both labels share a grid cell, keeping the pending action's width stable. */
  loadingLabel?: ReactNode;
  variant?: ButtonVariant;
};

export function Button({
  children,
  className,
  disabled,
  icon,
  loading = false,
  loadingLabel,
  type = "button",
  variant = "secondary",
  ...props
}: ButtonProps) {
  const classes = [styles.button, styles[variant], className].filter(Boolean).join(" ");

  return (
    <button
      {...props}
      aria-busy={loading || undefined}
      data-loading={loading || undefined}
      className={classes}
      disabled={disabled || loading}
      type={type}
    >
      {loadingLabel !== undefined ? <span className={styles.labelStack}>
        <span aria-hidden={loading || undefined} className={styles.readyLabel}>{icon && <span aria-hidden="true" className={styles.icon}>{icon}</span>}{children}</span>
        <span aria-hidden={!loading} className={styles.busyLabel}><Spinner aria-hidden="true" />{loadingLabel}</span>
      </span> : <>
        {loading ? <Spinner aria-hidden="true" /> : icon ? <span aria-hidden="true" className={styles.icon}>{icon}</span> : null}
        <span>{children}</span>
      </>}
    </button>
  );
}
