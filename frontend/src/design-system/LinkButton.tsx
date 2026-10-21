import { Link, type LinkProps } from "react-router-dom";
import type { ReactNode } from "react";
import styles from "./Button.module.css";

export type LinkButtonProps = Omit<LinkProps, "className"> & {
  className?: string;
  icon?: ReactNode;
  variant?: "primary" | "secondary" | "quiet";
};

/** Navigation keeps native link behavior while sharing the button visual tokens. */
export function LinkButton({ children, className, icon, variant = "secondary", ...props }: LinkButtonProps) {
  return <Link {...props} className={[styles.button, styles.link, styles[variant], className].filter(Boolean).join(" ")}>
    {icon ? <span aria-hidden="true" className={`${styles.icon} ${styles.linkIcon}`}>{icon}</span> : null}
    <span>{children}</span>
  </Link>;
}
