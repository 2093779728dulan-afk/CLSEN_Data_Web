import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CatalogChangeReview } from "./CatalogChangeReview";
import type { CatalogStyle, CatalogStyleChangePreview } from "./catalogApi";

const style = { style_id: 13, style_code: "QA-RESTORE", standard_name: "原商品", category_id: null } as CatalogStyle;
const category = { category_id: null, code: null, display_name: null };
const preview: CatalogStyleChangePreview = { style_id: 13, draft_id: 91, draft_revision: 1, status: "draft", style_code: style.style_code, base_catalog_publication_revision: 10, before: { standard_name: "原商品", category }, after: { standard_name: "已保存名称", category } };

it("restores the saved preview without creating another draft and blocks a stale approval", async () => {
  const services = { categories: vi.fn().mockResolvedValue([]), prepare: vi.fn(), approve: vi.fn(), load: vi.fn().mockResolvedValue(preview) };
  const result = render(<CatalogChangeReview restoredDraftId={91} catalogPublicationRevision={10} onApproved={vi.fn()} style={style} services={services} />);
  expect(await screen.findByText("已保存名称")).toBeVisible();
  expect(screen.getByRole("button", { name: "批准并生成新目录版本" })).toBeEnabled();
  expect(services.prepare).not.toHaveBeenCalled();
  result.rerender(<CatalogChangeReview restoredDraftId={91} catalogPublicationRevision={11} onApproved={vi.fn()} style={style} services={services} />);
  expect(await screen.findByText("原草稿基准已变化")).toBeVisible();
  expect(screen.getByRole("button", { name: "批准并生成新目录版本" })).toBeDisabled();
  expect(services.load).toHaveBeenCalledTimes(1);
});

it("rejects a saved draft for a different stable style", async () => {
  const services = { categories: vi.fn().mockResolvedValue([]), prepare: vi.fn(), approve: vi.fn(), load: vi.fn().mockResolvedValue({ ...preview, style_id: 14 }) };
  render(<CatalogChangeReview restoredDraftId={91} catalogPublicationRevision={10} onApproved={vi.fn()} style={style} services={services} />);
  await waitFor(() => expect(screen.getByText(/此草稿不属于当前商品/)).toBeVisible());
  expect(screen.getByRole("button", { name: "生成变更预览" })).toBeDisabled();
  expect(services.prepare).not.toHaveBeenCalled();
});
