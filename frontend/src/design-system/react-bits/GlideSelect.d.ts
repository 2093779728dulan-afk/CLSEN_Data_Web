import type { ReactElement, ReactNode } from "react";

export type GlideSelectOption = { value: string; label: ReactNode; tag?: string };
export type GlideSelectProps = {
  options?: ReadonlyArray<string | GlideSelectOption>;
  value?: string;
  defaultValue?: string;
  onChange?: (value: string, option: GlideSelectOption) => void;
  placeholder?: string;
  showTags?: boolean;
  accentColor?: string;
  surfaceColor?: string;
  highlightColor?: string;
  textColor?: string;
  size?: "sm" | "md" | "lg";
  radius?: number;
  menuWidth?: number;
  placement?: "bottom" | "top";
  align?: "left" | "right";
  popDuration?: number;
  glideDuration?: number;
  rememberPosition?: boolean;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
  /** Project additions connect the shared FormField label and descriptions. */
  id?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean | "true" | "false";
};

export default function GlideSelect(props: GlideSelectProps): ReactElement;
