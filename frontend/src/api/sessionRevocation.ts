type SessionRevocationListener = () => void;

let boundary = 0;
let active = false;
let revoked = false;
const listeners = new Set<SessionRevocationListener>();

export function establishSessionBoundary(): number {
  boundary += 1;
  active = true;
  revoked = false;
  return boundary;
}
export function closeSessionBoundary(): void {
  active = false;
  revoked = true;
}

export function hasActiveSessionBoundary(): boolean {
  return active && !revoked;
}

export function revokeSessionBoundary(): boolean {
  if (!active || revoked) return false;
  revoked = true;
  for (const listener of [...listeners]) listener();
  return true;
}

export function onSessionRevoked(listener: SessionRevocationListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function sessionBoundaryForTest(): number {
  return boundary;
}
