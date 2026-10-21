import { useId, type InputHTMLAttributes, type ReactNode } from "react";

import styles from "./SelectionControl.module.css";

export type RadioProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  description?: ReactNode;
  error?: ReactNode;
  label: ReactNode;
};

export function Radio({ description, error, id, label, ...props }: RadioProps) {
  const generatedId = useId();
  const controlId = id ?? `radio-${generatedId}`;
  const labelId = `${controlId}-label`;
  const descriptionId = description != null || error != null ? `${controlId}-description` : undefined;
  return <label className={styles.control} htmlFor={controlId}>
    <input {...props} aria-describedby={descriptionId} aria-invalid={error != null || undefined} aria-labelledby={labelId} id={controlId} type="radio" />
    <span className={styles.copy}><span className={styles.label} id={labelId}>{label}</span>{descriptionId ? <span className={error != null ? styles.error : styles.description} id={descriptionId}>{error ?? description}</span> : null}</span>
  </label>;
}
