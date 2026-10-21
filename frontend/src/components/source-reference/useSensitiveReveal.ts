import { useCallback, useEffect, useRef, useState } from "react";

import { ApiRequestError } from "../../api/client";
import { RequestGate, type RequestTuple } from "../../api/requestGate";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";

export type SensitiveReveal = {
  code_points: string;
  utf8_base64url: string;
};

function decodeBase64Url(value: string): string {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const bytes = Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

export function useSensitiveReveal(resourceKey: RequestTuple) {
  const { generation, registerSensitivePurge } = useAuthzGeneration();
  const gate = useRef(new RequestGate());
  const [reveal, setReveal] = useState<SensitiveReveal>();
  const [decoded, setDecoded] = useState<string>();
  const clipboardStaging = useRef<string | undefined>(undefined);
  const key = JSON.stringify(resourceKey);

  const purge = useCallback(() => {
    gate.current.abortAll();
    clipboardStaging.current = undefined;
    setReveal(undefined);
    setDecoded(undefined);
  }, []);

  useEffect(() => registerSensitivePurge(purge), [purge, registerSensitivePurge]);
  useEffect(() => purge(), [generation, key, purge]);
  useEffect(() => () => gate.current.dispose(), []);

  const load = useCallback(
    async (loader: (signal: AbortSignal) => Promise<SensitiveReveal>) => {
      const ticket = gate.current.begin(resourceKey, generation);
      try {
        const result = await loader(ticket.signal);
        if (!ticket.isCurrent()) return;
        const raw = decodeBase64Url(result.utf8_base64url);
        if (!ticket.isCurrent()) return;
        clipboardStaging.current = raw;
        setReveal(result);
        setDecoded(raw);
      } catch (reason) {
        if (
          reason instanceof ApiRequestError &&
          (reason.status === 403 || reason.status === 404 || reason.status === 409)
        ) {
          purge();
        }
        throw reason;
      }
    },
    [generation, purge, resourceKey],
  );

  const copy = useCallback(async () => {
    if (!clipboardStaging.current) return false;
    await navigator.clipboard.writeText(clipboardStaging.current);
    return true;
  }, []);

  return { copy, decoded, load, purge, reveal };
}
