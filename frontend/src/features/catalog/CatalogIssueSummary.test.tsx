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
  const reason = screen.getByText("invalid_headers").closest("p");
  expect(reason).toBeVisible();
  expect(reason).toHaveTextContent("原因代码：invalid_headers");
});

it("explains an unconfirmed mapped Seller SKU in Chinese", () => {
  render(<CatalogIssueSummary status="needs_attention" issues={[{
    section: "skus",
    row_key: "sku-162",
    field: "/internal_display_sku",
    severity: "blocking",
    reason_code: "mapped_target_formal_code_required",
  }]} />);
  expect(screen.getByText("SKU 标准化 · 正式SKU：该Seller SKU已纳入目录，请先从来源下拉框确认正式SKU")).toBeVisible();
});

it('groups repetitive issues for category review while retaining every original issue',()=>{
 const issues=Array.from({length:58},(_,index)=>({section:'mappings' as const,row_key:`row-${index}`,field:'/identity_decision',severity:'blocking',reason_code:'required'}));const category=vi.fn();
 render(<CatalogIssueSummary status="needs_attention" issues={issues} onSection={category}/>);
 fireEvent.click(screen.getByRole('button',{name:'SKU 映射 · 映射决定 · 58项'}));expect(category).toHaveBeenCalledWith('mappings');
 expect(screen.queryByText('row-57')).not.toBeVisible();fireEvent.click(screen.getByText('查看全部逐行问题与证据位置'));expect(screen.getByText('row-57')).toBeVisible();
});
