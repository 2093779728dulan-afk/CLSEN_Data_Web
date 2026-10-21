import GlideSelect, { type GlideSelectProps } from "./react-bits/GlideSelect";
import styles from "./GlideSelectField.module.css";

export type GlideSelectFieldProps = Pick<GlideSelectProps,
  "options" | "value" | "onChange" | "disabled" | "ariaLabel" | "id" | "aria-describedby" | "aria-invalid"
>;

/** Official JS-CSS interaction using the shared catalog theme. */
export function GlideSelectField(props: GlideSelectFieldProps) {
  return <GlideSelect {...props} className={styles.field} showTags={false}
    accentColor="var(--color-primary)" surfaceColor="var(--color-surface)"
    highlightColor="var(--color-info-bg)" textColor="var(--color-text)"
    size="md" radius={10} menuWidth={176} placement="bottom" align="left"
    popDuration={180} glideDuration={220} rememberPosition />;
}
