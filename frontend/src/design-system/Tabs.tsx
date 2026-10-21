import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

import styles from "./Tabs.module.css";

export type TabItem = { content: ReactNode; disabled?: boolean; label: ReactNode; value: string };
export type TabsProps = {
  animate?: boolean;
  ariaLabel: string;
  defaultValue?: string;
  items: TabItem[];
  keepMounted?: boolean;
  onValueChange?: (value: string) => void;
  orientation?: "horizontal" | "vertical";
  value?: string;
};

export function Tabs({ animate = false, ariaLabel, defaultValue, items, keepMounted = false, onValueChange, orientation = "horizontal", value }: TabsProps) {
  return <TabsPrimitive.Root className={styles.root} defaultValue={defaultValue ?? items[0]?.value} onValueChange={onValueChange} orientation={orientation} value={value}>
    <TabsPrimitive.List aria-label={ariaLabel} className={styles.list}>
      {items.map((item) => <TabsPrimitive.Trigger className={styles.trigger} disabled={item.disabled} key={item.value} value={item.value}>{item.label}</TabsPrimitive.Trigger>)}
    </TabsPrimitive.List>
    {items.map((item) => <TabsPrimitive.Content className={[styles.content, animate && styles.animated].filter(Boolean).join(" ")} forceMount={keepMounted || undefined} key={item.value} value={item.value}>{item.content}</TabsPrimitive.Content>)}
  </TabsPrimitive.Root>;
}
