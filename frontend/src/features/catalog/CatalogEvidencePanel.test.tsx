import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { CatalogEvidencePanel } from "./CatalogEvidencePanel";

afterEach(() => vi.unstubAllGlobals());
it("shows safe evidence without rendering raw source", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ items: [{ digest: `sha256:${"a".repeat(64)}`, is_truncated: true, is_unsafe: true, preview: "safe", source_ref_id: "3" }] }), { status: 200 }))));
  render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["data_manager"], siteConfigVersionId: 1, siteId: 1 }} onRevoked={vi.fn()}><CatalogEvidencePanel importId={2} workflowRevision={1} /></AuthzGenerationProvider>);
  expect(await screen.findByText("safe")).toBeVisible();
  expect(document.body.innerHTML).not.toContain("raw source");
});
