import { useId, type InputHTMLAttributes, type ReactNode } from "react";
import { Check, Minus } from "lucide-react";

import styles from "./SelectionControl.module.css";

export type CheckboxProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  description?: ReactNode;
  error?: ReactNode;
  label: ReactNode;
};

export function Checkbox({ description, error, id, label, ...props }: CheckboxProps) {
  const generatedId = useId();
  const controlId = id ?? `checkbox-${generatedId}`;
  const labelId = `${controlId}-label`;
  const descriptionId = description != null || error != null ? `${controlId}-description` : undefined;
  return <label className={styles.control} htmlFor={controlId}>
    <span className={styles.checkmark}>
      <input {...props} aria-describedby={descriptionId} aria-invalid={error != null || undefined} aria-labelledby={labelId} id={controlId} type="checkbox" />
      <Check aria-hidden="true" className={styles.check} />
      <Minus aria-hidden="true" className={styles.partial} />
    </span>
    <span className={styles.copy}><span className={styles.label} id={labelId}>{label}</span>{descriptionId ? <span className={error != null ? styles.error : styles.description} id={descriptionId}>{error ?? description}</span> : null}</span>
  </label>;
}
