import { useId, type TableHTMLAttributes } from "react";

import styles from "./Table.module.css";

export type TableProps = Omit<TableHTMLAttributes<HTMLTableElement>, "title"> & {
  description?: string;
  title?: string;
};

export function Table({ children, className, description, title, ...props }: TableProps) {
  const generatedId = useId();
  const titleId = title ? `table-${generatedId}-title` : undefined;
  const descriptionId = description ? `table-${generatedId}-description` : undefined;
  return <section className={styles.frame}>
    {title || description ? <header className={styles.header}>
      {title ? <h3 id={titleId}>{title}</h3> : null}
      {description ? <p id={descriptionId}>{description}</p> : null}
    </header> : null}
    <div className={styles.scroller} tabIndex={0}>
      <table
        {...props}
        aria-describedby={descriptionId}
        aria-labelledby={titleId}
        className={[styles.table, className].filter(Boolean).join(" ")}
      >
        {children}
      </table>
    </div>
  </section>;
}
