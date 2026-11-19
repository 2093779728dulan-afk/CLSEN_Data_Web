import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { requestApi } from "../../api/client";
import { CatalogImportHistory } from "./CatalogImportHistory";
vi.mock("../../api/client", () => ({ requestApi: vi.fn() }));
afterEach(() => {cleanup();vi.resetAllMocks();});
it("recovers approved and unfinished batches without creating candidates", async () => {
  vi.mocked(requestApi).mockResolvedValue({ items: [{ import_id: 1, status: "approved", source_kind: "online", workflow_revision: 3 }, { import_id: 2, status: "needs_attention", source_kind: "xlsx", workflow_revision: 1 }], has_next: false });
  render(<MemoryRouter><CatalogImportHistory /></MemoryRouter>);
  expect(await screen.findByRole("link", { name: "批次 #1 · 查看批准结果" })).toHaveAttribute("href", "/catalog/imports/1");
  expect(screen.getByRole("link", { name: "批次 #2 · 继续审核" })).toHaveAttribute("href", "/catalog/imports/2");
  expect(requestApi).toHaveBeenCalledWith("/api/catalog/imports?page=1");
});

it('keeps source-specific links, page navigation and read recovery',async()=>{
 vi.mocked(requestApi).mockResolvedValueOnce({items:[{import_id:8,source_kind:'production',record_kind:'listing_source',source_name:'产品信息.xlsx',review_path:'/catalog/production-sources?listing=8',status:'validated',workflow_revision:1}],has_next:true}).mockRejectedValueOnce(Error('连接中断')).mockResolvedValueOnce({items:[],has_next:false});
 render(<MemoryRouter><CatalogImportHistory/></MemoryRouter>);
 expect(await screen.findByRole('link',{name:'批次 #8 · 查看清单／继续未核记录'})).toHaveAttribute('href','/catalog/production-sources?listing=8');
 await userEvent.click(screen.getByRole('button',{name:'下一页'}));expect(await screen.findByRole('alert')).toHaveTextContent('连接中断');
 await userEvent.click(screen.getByRole('button',{name:'刷新批次'}));expect(await screen.findByText('当前页没有审核批次')).toBeVisible();
 expect(screen.getByRole('button',{name:'上一页'})).toBeEnabled();expect(requestApi).toHaveBeenLastCalledWith('/api/catalog/imports?page=2');
});
