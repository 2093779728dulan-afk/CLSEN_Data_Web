import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { ReactElement, ReactNode } from "react";

import styles from "./Tooltip.module.css";

export type TooltipProps = {
  children: ReactElement;
  content: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
};

export function Tooltip({ children, content, side = "top" }: TooltipProps) {
  return <TooltipPrimitive.Provider delayDuration={250} skipDelayDuration={100}>
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content className={styles.content} side={side} sideOffset={7}>
          {content}<TooltipPrimitive.Arrow className={styles.arrow} />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  </TooltipPrimitive.Provider>;
}
