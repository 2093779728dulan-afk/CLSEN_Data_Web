import { LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import styles from "./Button.module.css";

type ButtonVariant = "primary" | "secondary" | "danger" | "quiet";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon?: ReactNode;
  loading?: boolean;
  variant?: ButtonVariant;
};

export function Button({
  children,
  className,
  disabled,
  icon,
  loading = false,
  type = "button",
  variant = "secondary",
  ...props
}: ButtonProps) {
  const classes = [styles.button, styles[variant], className].filter(Boolean).join(" ");

  return (
    <button
      {...props}
      aria-busy={loading || undefined}
      className={classes}
      disabled={disabled || loading}
      type={type}
    >
      {loading ? (
        <LoaderCircle aria-hidden="true" className={`${styles.icon} ${styles.loadingIcon}`} />
      ) : icon ? (
        <span aria-hidden="true" className={styles.icon}>{icon}</span>
      ) : null}
      <span>{children}</span>
    </button>
  );
}
