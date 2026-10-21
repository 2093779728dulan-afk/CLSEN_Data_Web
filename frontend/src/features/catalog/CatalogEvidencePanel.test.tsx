import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { CatalogEvidencePanel } from "./CatalogEvidencePanel";

afterEach(() => vi.unstubAllGlobals());
it("shows safe evidence without rendering raw source", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ items: [{ digest: `sha256:${"a".repeat(64)}`, is_truncated: true, is_unsafe: true, preview: "safe", source_ref_id: "3" }] }), { status: 200 }))));
  render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["data_manager"], siteConfigVersionId: 1, siteId: 1 }} onRevoked={vi.fn()}><CatalogEvidencePanel importId={2} workflowRevision={1} /></AuthzGenerationProvider>);
  expect(await screen.findByText("safe")).toBeVisible();
  expect(document.body.innerHTML).not.toContain("raw source");
});

it("shows a failed source read and retries only after an explicit action", async () => {
  const read = vi.fn().mockRejectedValueOnce(new Error("虚构来源读取失败")).mockResolvedValue({ items: [] });
  render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["data_manager"], siteConfigVersionId: 1, siteId: 1 }} onRevoked={vi.fn()}><CatalogEvidencePanel importId={2} workflowRevision={1} loadSources={read} /></AuthzGenerationProvider>);
  expect(await screen.findByRole("alert")).toHaveTextContent("虚构来源读取失败"); expect(read).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "重新读取来源" }));
  expect(await screen.findByRole("heading", { name: "暂无来源证据" })).toBeVisible(); expect(read).toHaveBeenCalledTimes(2);
});
