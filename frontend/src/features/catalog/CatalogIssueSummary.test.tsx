import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CatalogIssueSummary } from "./CatalogIssueSummary";

it("locates a server issue including its row and section", () => {
  const issue = { section: "skus" as const, row_key: "sku:2", field: "/standard_size", severity: "blocking", reason_code: "required" };
  const locate = vi.fn();
  render(<CatalogIssueSummary status="needs_attention" issues={[issue]} onLocate={locate} />);
  expect(screen.getByText("SKU 标准化 · 标准尺码：尚未填写或确认")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "定位问题 1" }));
  expect(locate).toHaveBeenCalledWith(issue);
});

it("distinguishes file correction from retrying a recoverable parse failure", () => {
  render(<CatalogIssueSummary status="parse_failed" failureReason="invalid_headers" />);
  expect(screen.getByText(/修正原文件并到批量维护重新上传/)).toBeVisible();
  expect(screen.getByText("原因代码：invalid_headers")).toBeVisible();
});
