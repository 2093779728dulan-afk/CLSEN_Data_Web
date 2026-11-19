import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DraftQuantityChange, SourceDraftReview } from "./SourceDraftReview";

afterEach(cleanup);

describe("source draft review controls", () => {
  it("locates the declared field without marking the item resolved", async () => {
    const user = userEvent.setup();
    render(<><input id="review-date" aria-label="候选日期" /><SourceDraftReview items={[{ key: "date", title: "日期待核实", detail: "填写后仍待核实。", targetId: "review-date", actionLabel: "定位日期" }]} changedCount={0} totalDifference="0" disabled={false} onRestoreAll={vi.fn()} /></>);
    await user.click(screen.getByRole("button", { name: "定位日期" }));
    expect(screen.getByLabelText("候选日期")).toHaveFocus();
    expect(screen.getByText("日期待核实")).toBeVisible();
  });
  it("cancels all-quantity restoration and returns to its trigger", async () => {
    const user = userEvent.setup(); const restore = vi.fn();
    render(<SourceDraftReview items={[]} changedCount={2} totalDifference="0" disabled={false} onRestoreAll={restore} />);
    await user.click(screen.getByRole("button", { name: "恢复全部原数量" }));
    expect(restore).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.getByRole("button", { name: "恢复全部原数量" })).toHaveFocus());
    expect(restore).not.toHaveBeenCalled();
  });
  it("requires explicit confirmation and restores focus when the trigger becomes disabled", async () => {
    const user = userEvent.setup(); const restore = vi.fn();
    function Harness() { const [count, setCount] = useState(2); return <SourceDraftReview items={[]} changedCount={count} totalDifference={count ? "3" : "0"} disabled={false} onRestoreAll={() => { restore(); setCount(0); }} />; }
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "恢复全部原数量" }));
    await user.click(screen.getByRole("button", { name: "确认恢复全部原数量" }));
    expect(restore).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByRole("heading", { name: "待核对清单与数量修改" })).toHaveFocus());
    expect(screen.getByRole("button", { name: "恢复全部原数量" })).toBeDisabled();
  });
  it("restores one quantity without submitting the enclosing form", async () => {
    const user = userEvent.setup(); const submit = vi.fn();
    function Harness() { const [value, setValue] = useState("12"); return <form onSubmit={submit}><input id="review-quantity" aria-label="草稿数量" value={value} readOnly /><DraftQuantityChange original="10" current={value} disabled={false} inputId="review-quantity" onRestore={() => setValue("10")} /></form>; }
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "恢复本行原数量" }));
    expect(screen.getByLabelText("草稿数量")).toHaveValue("10");
    expect(screen.getByLabelText("草稿数量")).toHaveFocus();
    expect(submit).not.toHaveBeenCalled();
  });
  it("cannot restore readonly, saving or unresolved-operation inputs", () => {
    const restore = vi.fn();
    render(<><SourceDraftReview items={[]} changedCount={1} totalDifference="2" disabled onRestoreAll={restore} /><DraftQuantityChange original="10" current="12" disabled inputId="unused" onRestore={restore} /></>);
    expect(screen.getByRole("button", { name: "恢复全部原数量" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "恢复本行原数量" })).toBeDisabled();
  });
});
