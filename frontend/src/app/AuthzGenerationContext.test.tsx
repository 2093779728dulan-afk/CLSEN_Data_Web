import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { establishSessionBoundary, revokeSessionBoundary } from "../api/sessionRevocation";
import {
  AuthzGenerationProvider,
  useAuthzGeneration,
  type AuthzBoundary,
} from "./AuthzGenerationContext";

function Probe() {
  const { generation } = useAuthzGeneration();
  return <output>{generation}</output>;
}

const boundary: AuthzBoundary = {
  principalId: 3,
  roles: ["data_manager"],
  siteConfigVersionId: 7,
  siteId: 1,
};

describe("authorization generation", () => {
  it("increments for permission changes and session revocation", () => {
    const revoked = vi.fn();
    const view = render(
      <AuthzGenerationProvider boundary={boundary} onRevoked={revoked}>
        <Probe />
      </AuthzGenerationProvider>,
    );
    expect(screen.getByText("0")).toBeVisible();
    view.rerender(
      <AuthzGenerationProvider
        boundary={{ ...boundary, permissionsFingerprint: "changed" }}
        onRevoked={revoked}
      >
        <Probe />
      </AuthzGenerationProvider>,
    );
    expect(screen.getByText("1")).toBeVisible();
    establishSessionBoundary();
    act(() => {
      revokeSessionBoundary();
    });
    expect(revoked).toHaveBeenCalledTimes(1);
    expect(screen.getByText("2")).toBeVisible();
  });
});
