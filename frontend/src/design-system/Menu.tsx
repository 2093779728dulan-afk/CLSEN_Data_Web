import * as MenuPrimitive from "@radix-ui/react-dropdown-menu";
import { MoreHorizontal } from "lucide-react";

import { Button } from "./Button";
import styles from "./Menu.module.css";

export type MenuItem = { danger?: boolean; disabled?: boolean; id: string; label: string; onSelect: () => void };
export type MenuProps = { items: MenuItem[]; label: string };

export function Menu({ items, label }: MenuProps) {
  return <MenuPrimitive.Root modal={false}>
    <MenuPrimitive.Trigger asChild><Button aria-label={label} icon={<MoreHorizontal />}>{label}</Button></MenuPrimitive.Trigger>
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content align="end" className={styles.content} sideOffset={5}>
        {items.map((item) => <MenuPrimitive.Item className={`${styles.item}${item.danger ? ` ${styles.danger}` : ""}`} disabled={item.disabled} key={item.id} onSelect={item.onSelect}>{item.label}</MenuPrimitive.Item>)}
      </MenuPrimitive.Content>
    </MenuPrimitive.Portal>
  </MenuPrimitive.Root>;
}
