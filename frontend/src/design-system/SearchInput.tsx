import { forwardRef, useImperativeHandle, useRef, type InputHTMLAttributes } from "react";
import { Search, X } from "lucide-react";
import { Input } from "./Input";
import styles from "./SearchInput.module.css";

export type SearchInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "onChange"> & { value: string; onValueChange: (value: string) => void; clearLabel?: string };

/** shadcn InputGroup composition adapted to the existing native Input. */
export const SearchInput = forwardRef<HTMLInputElement, SearchInputProps>(function SearchInput({ className, clearLabel = "清空搜索", disabled, onValueChange, readOnly, value, ...props }, ref) {
  const input = useRef<HTMLInputElement>(null);
  useImperativeHandle(ref, () => input.current!, []);
  return <div className={[styles.group, className].filter(Boolean).join(" ")}>
    <Search aria-hidden="true" className={styles.searchIcon} />
    <Input {...props} className={styles.input} disabled={disabled} onChange={event => onValueChange(event.target.value)} readOnly={readOnly} ref={input} type="search" value={value} />
    {value && !readOnly && <button aria-label={clearLabel} className={styles.clear} disabled={disabled} onClick={() => { onValueChange(""); input.current?.focus(); }} type="button"><X aria-hidden="true" /></button>}
  </div>;
});
