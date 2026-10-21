// Adapted from shadcn/ui Spinner (MIT); see THIRD_PARTY_NOTICES.md.
import { LoaderCircle } from "lucide-react";
import type { ComponentProps } from "react";
import styles from "./Spinner.module.css";

export function Spinner({ className, ...props }: ComponentProps<typeof LoaderCircle>) {
  return <LoaderCircle role="status" aria-label="正在加载" className={[styles.spinner, className].filter(Boolean).join(" ")} {...props} />;
}
