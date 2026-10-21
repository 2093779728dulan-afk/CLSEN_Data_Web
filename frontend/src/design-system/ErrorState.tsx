import { CircleAlert } from "lucide-react";
import type { ReactNode } from "react";

import styles from "./StatePanel.module.css";

export type ErrorStateProps = {
  action?: ReactNode;
  description?: ReactNode;
  title: ReactNode;
};

export function ErrorState({ action, description, title }: ErrorStateProps) {
  return <section className={`${styles.panel} ${styles.error}`} role="alert">
    <span aria-hidden="true" className={styles.icon}><CircleAlert /></span>
    <div className={styles.copy}>
      <h3>{title}</h3>
      {description != null ? <p>{description}</p> : null}
    </div>
    {action != null ? <div className={styles.action}>{action}</div> : null}
  </section>;
}
