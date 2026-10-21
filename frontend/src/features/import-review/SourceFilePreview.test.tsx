import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SourceFilePreview } from "./SourceFilePreview";

function previewResponse(value: string): Response {
  return {
    json: () => Promise.resolve({
      encoding: "utf-8",
      headers: ["sku", "sales"],
      row_count: 1,
      rows: [[value, value === "FIRST" ? "10" : "20"]],
      truncated: false,
    }),
    ok: true,
    status: 200,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SourceFilePreview", () => {
  it("loads the newly selected batch instead of retaining the previous file", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path === "/api/imports/11/raw-file/preview?encoding=utf-8&row_limit=200") return Promise.resolve(previewResponse("FIRST"));
      if (path === "/api/imports/12/raw-file/preview?encoding=utf-8&row_limit=200") return Promise.resolve(previewResponse("SECOND"));
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { rerender } = render(
      <SourceFilePreview batchId={11} encoding="utf-8" fileName="first.csv" />,
    );

    await user.click(screen.getByRole("button", { name: "查看上传源表" }));
    expect(await screen.findByText("FIRST")).toBeVisible();

    rerender(<SourceFilePreview batchId={12} encoding="utf-8" fileName="second.csv" />);
    expect(screen.queryByText("FIRST")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看上传源表" }));

    expect(await screen.findByText("SECOND")).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/imports/12/raw-file/preview?encoding=utf-8&row_limit=200",
      { credentials: "same-origin" },
    ));
  });
});

it("keeps original data-row numbers when searching the preview", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({encoding:"utf-8",headers:["sku"],row_count:3,rows:[["A"],["B"],["TARGET"]],truncated:false}),{headers:{"Content-Type":"application/json"}})));
  const user=userEvent.setup();
  render(<SourceFilePreview batchId={11} encoding="utf-8" fileName="source.csv"/>);
  await user.click(screen.getByRole("button",{name:"查看上传源表"}));
  await screen.findByText("TARGET");
  await user.type(screen.getByRole("searchbox",{name:"搜索预览行"}),"TARGET");
  expect(screen.getByRole("rowheader",{name:"3"})).toBeVisible();
  expect(screen.queryByRole("rowheader",{name:"1"})).not.toBeInTheDocument();
});
