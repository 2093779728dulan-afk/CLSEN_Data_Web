import { useEffect, useRef } from "react";
import { useBlocker } from "react-router-dom";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button } from "../../design-system";
import { ProductionConfirmDialog } from "./ProductionConfirmDialog";

export function useProductionLeave(dirty: boolean, busy: boolean, unknown = false, preservedSearchParams: readonly string[] = []) {
  const { generation } = useAuthzGeneration();
  const startGeneration = useRef(generation);
  const bypass = useRef(false);
  const guarded = generation === startGeneration.current && !bypass.current && (dirty || busy || unknown);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => {
    const searchFor = (search: string) => {
      if (!preservedSearchParams.length) return search;
      const params = new URLSearchParams(search);
      for (const key of preservedSearchParams) params.delete(key);
      return params.toString();
    };
    return generation === startGeneration.current && !bypass.current && (dirty || busy || unknown) && `${currentLocation.pathname}?${searchFor(currentLocation.search)}${currentLocation.hash}` !== `${nextLocation.pathname}?${searchFor(nextLocation.search)}${nextLocation.hash}`;
  });
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => { if (guarded) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [guarded]);
  const title = unknown ? "先核实保存结果" : "还有未保存的内容";
  const description = unknown ? "当前操作结果尚未确认。请查询原操作结果或重发原操作，避免重复登记。" : "离开后，本页尚未保存的输入将被放弃。";
  const actions = <>
    <Button variant="primary" onClick={() => { if (blocker.state === "blocked") blocker.reset(); }}>{unknown ? "继续核实" : "继续填写"}</Button>
    {!unknown && <Button variant="danger" disabled={busy} onClick={() => { if (blocker.state === "blocked") { bypass.current = true; blocker.proceed(); } }}>放弃并离开</Button>}
  </>;
  return {
    allowLeave: () => { bypass.current = true; },
    blocked: blocker.state === "blocked",
    prompt: <ProductionConfirmDialog open={blocker.state === "blocked"} onOpenChange={open => { if (!open && blocker.state === "blocked") blocker.reset(); }} title={title} description={description}>{actions}</ProductionConfirmDialog>,
  };
}
