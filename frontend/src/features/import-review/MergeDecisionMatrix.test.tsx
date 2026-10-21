import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MergeDecisionMatrix,
  type MergeDecisionState,
} from "./MergeDecisionMatrix";

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
  });
}

describe("MergeDecisionMatrix", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("prefills each selected conflict decision with operator and row provenance", async () => {
    const onStateChange = vi.fn<(state: MergeDecisionState) => void>();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      report_type: "business_report",
      target_version_id: 51,
      source_kind: "parse_baseline",
      source_id: 61,
      conflicts: [{
        target_row_id: 101,
        target_row_ordinal: 1,
        target_values: { sku: "A-01", sales: "42.00" },
        source_row_id: 201,
        source_row_ordinal: 4,
        source_values: { sku: "A-01", sales: "42.00" },
      }],
    })));
    const user = userEvent.setup();

    render(<MergeDecisionMatrix onStateChange={onStateChange} operator={{ id: 3, username: "manager", display_name: "录入审核" }} sourceId={61} sourceKind="parse_baseline" targetVersionId={51} />);
    expect(await screen.findByText(/子 ASIN \+ SKU/)).toBeVisible();
    expect(screen.getByText("字段完全相同")).toBeVisible();
    expect(screen.getByLabelText("重复记录 1 处理方式")).toHaveValue("keep_target");
    await waitFor(() => expect(onStateChange.mock.calls.at(-1)?.[0].ready).toBe(true));
    await user.selectOptions(await screen.findByLabelText("重复记录 1 处理方式"), "keep_source");

    expect(screen.getByLabelText("重复记录 1 决定依据")).toHaveValue(
      "操作人：录入审核（manager / 用户 #3）；操作：重复记录采用来源行；来源：目标版本 #51 · 目标第 1 行 · 来源第 4 行。",
    );
    await waitFor(() => expect(onStateChange.mock.calls.at(-1)?.[0].ready).toBe(true));
  });

  it("requires and returns one explicit decision for every conflict pair", async () => {
    const onStateChange = vi.fn<(state: MergeDecisionState) => void>();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      report_type: "business_report",
      target_version_id: 51,
      source_kind: "parse_baseline",
      source_id: 61,
      conflicts: [
        {
          target_row_id: 101,
          target_row_ordinal: 1,
          target_values: { sku: "A-01", sales: "42.00" },
          source_row_id: 201,
          source_row_ordinal: 4,
          source_values: { sku: "A-01", sales: "43.00" },
        },
        {
          target_row_id: 102,
          target_row_ordinal: 2,
          target_values: { sku: "A-01", sales: "44.00" },
          source_row_id: 201,
          source_row_ordinal: 4,
          source_values: { sku: "A-01", sales: "43.00" },
        },
      ],
    }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<MergeDecisionMatrix onStateChange={onStateChange} sourceId={61} sourceKind="parse_baseline" targetVersionId={51} />);

    expect(await screen.findByText(/2 组重复记录/)).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/datasets/merge-preview?target_version_id=51&source_kind=parse_baseline&source_id=61",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    await user.selectOptions(screen.getByLabelText("重复记录 1 处理方式"), "keep_target");
    await user.type(screen.getByLabelText("重复记录 1 决定依据"), "目标行与原表一致");
    expect(onStateChange.mock.calls.at(-1)?.[0].ready).toBe(false);

    await user.selectOptions(screen.getByLabelText("重复记录 2 处理方式"), "keep_both");
    await user.type(screen.getByLabelText("重复记录 2 决定依据"), "原表确有两笔业务记录");

    await waitFor(() => expect(onStateChange.mock.calls.at(-1)?.[0]).toEqual({
      ready: true,
      decisions: [
        {
          action: "keep_target",
          reason: "目标行与原表一致",
          source_row_id: 201,
          target_row_id: 101,
        },
        {
          action: "keep_both",
          reason: "原表确有两笔业务记录",
          source_row_id: 201,
          target_row_id: 102,
        },
      ],
    }));
  });

  it("paginates long conflict lists and applies an auditable action to pending rows on the current page", async () => {
    const onStateChange = vi.fn<(state: MergeDecisionState) => void>();
    const conflicts = Array.from({ length: 6 }, (_, index) => ({
      target_row_id: 100 + index,
      target_row_ordinal: index + 1,
      target_values: { sku: `A-${index + 1}`, title: `目标商品 ${index + 1}` },
      source_row_id: 200 + index,
      source_row_ordinal: index + 11,
      source_values: { sku: `A-${index + 1}`, title: `来源商品 ${index + 1}` },
    }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      report_type: "business_report",
      target_version_id: 51,
      source_kind: "parse_baseline",
      source_id: 61,
      conflicts,
    })));
    const user = userEvent.setup();

    render(<MergeDecisionMatrix onStateChange={onStateChange} operator={{ id: 3, username: "manager", display_name: "录入审核" }} sourceId={61} sourceKind="parse_baseline" targetVersionId={51} />);

    expect(await screen.findByText("6 组重复记录 · 已处理 0/6")).toBeVisible();
    expect(screen.getByLabelText("重复记录 4 处理方式")).toBeVisible();
    expect(screen.queryByLabelText("重复记录 5 处理方式")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("当前页统一处理方式"), "keep_target");
    await user.click(screen.getByRole("button", { name: "应用到当前页未处理项" }));

    expect(screen.getByLabelText("重复记录 1 决定依据")).toHaveValue(
      "操作人：录入审核（manager / 用户 #3）；操作：重复记录保留目标行；来源：目标版本 #51 · 目标第 1 行 · 来源第 11 行。",
    );
    expect(screen.getByText("6 组重复记录 · 已处理 4/6")).toBeVisible();
    expect(onStateChange.mock.calls.at(-1)?.[0].ready).toBe(false);

    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByLabelText("重复记录 5 处理方式")).toBeVisible();
    expect(screen.queryByLabelText("重复记录 1 处理方式")).not.toBeInTheDocument();
  });

  it("defaults identical pairs across all pages but leaves hidden-field differences undecided", async () => {
    const onStateChange = vi.fn<(state: MergeDecisionState) => void>();
    const conflicts = Array.from({ length: 6 }, (_, i) => ({
      target_row_id: 100 + i, source_row_id: 200 + i,
      target_row_ordinal: i + 1, source_row_ordinal: i + 1,
      target_values: { child_asin: `ASIN${i}`, sku: `SKU${i}`, title: "Same", sales: "42.00" },
      source_values: { child_asin: `ASIN${i}`, sku: `SKU${i}`, title: "Same", sales: i === 5 ? "43.00" : "42.00" },
    }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ report_type: "business_report", conflicts })));
    const user = userEvent.setup();
    render(<MergeDecisionMatrix onStateChange={onStateChange} sourceId={61} sourceKind="parse_baseline" targetVersionId={51} />);
    expect(await screen.findByText("6 组重复记录 · 已处理 5/6")).toBeVisible();
    expect(onStateChange.mock.calls.at(-1)?.[0].ready).toBe(false);
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByLabelText("重复记录 5 处理方式")).toHaveValue("keep_target");
    expect(screen.getByLabelText("重复记录 6 处理方式")).toHaveValue("");
    await user.selectOptions(screen.getByLabelText("重复记录 6 处理方式"), "keep_source");
    await user.type(screen.getByLabelText("重复记录 6 决定依据"), "核对来源正确");
    await waitFor(() => expect(onStateChange.mock.calls.at(-1)?.[0].ready).toBe(true));
    expect(onStateChange.mock.calls.at(-1)?.[0].decisions.slice(0, 5).every((d) => d.action === "keep_target" && typeof d.reason === "string" && d.reason.includes("两侧全部字段完全相同"))).toBe(true);
  });

  it("marks a conflict-free server preview as ready", async () => {
    const onStateChange = vi.fn<(state: MergeDecisionState) => void>();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      report_type: "return_report",
      target_version_id: 71,
      source_kind: "dataset_version",
      source_id: 72,
      conflicts: [],
    })));

    render(<MergeDecisionMatrix onStateChange={onStateChange} sourceId={72} sourceKind="dataset_version" targetVersionId={71} />);

    expect(await screen.findByText("没有重复业务键，可以安全保留两侧记录。")).toBeVisible();
    await waitFor(() => expect(onStateChange.mock.calls.at(-1)?.[0]).toEqual({
      decisions: [],
      ready: true,
    }));
  });
});
