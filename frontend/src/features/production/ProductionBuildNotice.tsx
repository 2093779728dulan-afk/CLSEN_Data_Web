import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { Button, StatusMessage } from "../../design-system";

/** Check on navigation/focus; never replace a working form or reload automatically. */
export function ProductionBuildNotice() {
  const { key } = useLocation();
  const [updated, setUpdated] = useState(false);
  useEffect(() => {
    const current = document.querySelector<HTMLScriptElement>('script[type="module"][src]')?.getAttribute("src");
    if (!current?.startsWith("/assets/")) return;
    let pending: AbortController | undefined;
    const check = async () => {
      pending?.abort();
      const request = new AbortController(); pending = request;
      try {
        const response = await fetch("/", { cache: "no-store", signal: request.signal });
        if (!response.ok) return;
        const html = new DOMParser().parseFromString(await response.text(), "text/html");
        const next = html.querySelector('script[type="module"][src]')?.getAttribute("src");
        if (!request.signal.aborted && next?.startsWith("/assets/")) setUpdated(next !== current);
      } catch { /* A failed version check does not block the current operation. */ }
    };
    const onFocus = () => { void check(); };
    void check();
    window.addEventListener("focus", onFocus);
    return () => { pending?.abort(); window.removeEventListener("focus", onFocus); };
  }, [key]);
  return updated ? <StatusMessage kind="info" title="体验版本已更新" action={<Button variant="secondary" onClick={() => window.location.reload()}>保存后刷新版本</Button>}>请先保存当前操作，再刷新加载最新功能。未保存内容会继续受到离开提示保护。</StatusMessage> : null;
}
