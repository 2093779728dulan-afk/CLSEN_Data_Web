import { cloneElement, useId, type ReactElement, type ReactNode } from "react";

import styles from "./FormField.module.css";

type FieldControlProps = {
  id?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean | "true" | "false";
};

export type FormFieldProps = {
  children: ReactElement<FieldControlProps>;
  className?: string;
  error?: ReactNode;
  hint?: ReactNode;
  label: ReactNode;
  required?: boolean;
};

export function FormField({ children, className, error, hint, label, required = false }: FormFieldProps) {
  const generatedId = useId();
  const controlId = children.props.id ?? `field-${generatedId}`;
  const descriptionId = hint != null || error != null ? `${controlId}-description` : undefined;
  const describedBy = [children.props["aria-describedby"], descriptionId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={[styles.field, className].filter(Boolean).join(" ")}>
      <label className={styles.label} htmlFor={controlId}>
        {label}{required ? <span aria-hidden="true" className={styles.required}> *</span> : null}
      </label>
      {cloneElement(children, {
        "aria-describedby": describedBy,
        "aria-invalid": error != null ? true : children.props["aria-invalid"],
        id: controlId,
      })}
      {descriptionId ? (
        <p className={error != null ? styles.error : styles.hint} id={descriptionId}>
          {error ?? hint}
        </p>
      ) : null}
    </div>
  );
}
