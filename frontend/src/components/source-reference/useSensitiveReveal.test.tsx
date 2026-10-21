import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "../../api/client";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { useSensitiveReveal } from "./useSensitiveReveal";

function Wrapper({ children }: { children: ReactNode }) {
  return createElement(
    AuthzGenerationProvider,
    {
      boundary: {
        principalId: 1,
        roles: ["data_manager"],
        siteConfigVersionId: 1,
        siteId: 1,
      },
      onRevoked: vi.fn(),
    },
    children,
  );
}

describe("sensitive reveal lifecycle", () => {
  it("purges decoded and encoded values after a bound-resource conflict", async () => {
    const { result } = renderHook(() => useSensitiveReveal(["draft", 1, 2]), {
      wrapper: Wrapper,
    });
    await act(async () => {
      await result.current.load(() => Promise.resolve({
        code_points: "U+5371 U+9669",
        utf8_base64url: "5Y2x6Zmp",
      }));
    });
    expect(result.current.decoded).toBe("危险");

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.load(() => Promise.reject(
          new ApiRequestError(409, "catalog_workflow_revision_conflict", "changed"),
        ));
      } catch (reason) {
        caught = reason;
      }
    });
    expect(caught).toBeInstanceOf(ApiRequestError);
    await waitFor(() => expect(result.current.decoded).toBeUndefined());
    expect(result.current.reveal).toBeUndefined();
  });
});
