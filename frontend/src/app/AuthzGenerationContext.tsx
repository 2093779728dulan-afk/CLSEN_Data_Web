/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { abortAllRequestGates } from "../api/requestGate";
import { onSessionRevoked } from "../api/sessionRevocation";

export type AuthzBoundary = {
  permissionsFingerprint?: string;
  principalId: number;
  roles: readonly string[];
  siteConfigVersionId: number;
  siteId: number;
};

type Purge = () => void;
type AuthzGenerationValue = {
  generation: number;
  purgeSensitiveState: () => void;
  registerSensitivePurge: (purge: Purge) => () => void;
};

const AuthzGenerationContext = createContext<AuthzGenerationValue | undefined>(undefined);

function fingerprint(boundary: AuthzBoundary): string {
  return JSON.stringify([
    boundary.principalId,
    [...boundary.roles].sort(),
    boundary.siteId,
    boundary.siteConfigVersionId,
    boundary.permissionsFingerprint ?? null,
  ]);
}

export function AuthzGenerationProvider({
  boundary,
  children,
  onRevoked,
}: {
  boundary: AuthzBoundary;
  children?: ReactNode;
  onRevoked: () => void;
}) {
  const [generation, setGeneration] = useState(0);
  const purges = useRef(new Set<Purge>());
  const previous = useRef(fingerprint(boundary));

  const purgeSensitiveState = useCallback(() => {
    abortAllRequestGates();
    for (const purge of [...purges.current]) purge();
  }, []);

  const registerSensitivePurge = useCallback((purge: Purge) => {
    purges.current.add(purge);
    return () => purges.current.delete(purge);
  }, []);

  useEffect(() => {
    const next = fingerprint(boundary);
    if (previous.current === next) return;
    previous.current = next;
    purgeSensitiveState();
    setGeneration((value) => value + 1);
  }, [boundary, purgeSensitiveState]);

  useEffect(
    () =>
      onSessionRevoked(() => {
        purgeSensitiveState();
        setGeneration((value) => value + 1);
        onRevoked();
      }),
    [onRevoked, purgeSensitiveState],
  );

  const value = useMemo(
    () => ({ generation, purgeSensitiveState, registerSensitivePurge }),
    [generation, purgeSensitiveState, registerSensitivePurge],
  );
  return <AuthzGenerationContext.Provider value={value}>{children}</AuthzGenerationContext.Provider>;
}

export function useAuthzGeneration(): AuthzGenerationValue {
  const value = useContext(AuthzGenerationContext);
  if (!value) throw new Error("AuthzGenerationProvider is required.");
  return value;
}
