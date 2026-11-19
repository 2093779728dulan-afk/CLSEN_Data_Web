import * as MenuPrimitive from "@radix-ui/react-dropdown-menu";
import { MoreHorizontal } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "./Button";
import styles from "./Menu.module.css";

export type MenuItem = { danger?: boolean; disabled?: boolean; id: string; label: string } & ({ onSelect: () => void; href?: never; reloadDocument?: never } | { href: string; reloadDocument?: boolean; onSelect?: never });
export type MenuProps = { items: MenuItem[]; label: string; portalContainer?: HTMLElement | null };

export function Menu({ items, label, portalContainer }: MenuProps) {
  return <MenuPrimitive.Root modal={false}>
    <MenuPrimitive.Trigger asChild><Button aria-label={label} icon={<MoreHorizontal />}>{label}</Button></MenuPrimitive.Trigger>
    <MenuPrimitive.Portal container={portalContainer ?? undefined}>
      <MenuPrimitive.Content align="end" collisionBoundary={portalContainer ?? undefined} className={styles.content} sideOffset={5}>
        {items.map((item) => item.href !== undefined ? <MenuPrimitive.Item asChild className={`${styles.item}${item.danger ? ` ${styles.danger}` : ""}`} disabled={item.disabled} key={item.id}><Link to={item.href} reloadDocument={item.reloadDocument} onClick={event => { if (item.disabled) event.preventDefault(); }}>{item.label}</Link></MenuPrimitive.Item> : <MenuPrimitive.Item className={`${styles.item}${item.danger ? ` ${styles.danger}` : ""}`} disabled={item.disabled} key={item.id} onSelect={item.onSelect}>{item.label}</MenuPrimitive.Item>)}
      </MenuPrimitive.Content>
    </MenuPrimitive.Portal>
  </MenuPrimitive.Root>;
}
