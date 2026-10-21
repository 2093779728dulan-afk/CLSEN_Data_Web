import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Pagination } from "./Pagination";

describe("Pagination", () => {
  it("reports position and requests adjacent pages", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    render(<Pagination itemLabel="商品" onPageChange={onPageChange} page={2} totalItems={64} totalPages={3} />);

    expect(screen.getByText("共 64 个商品")).toBeVisible();
    expect(screen.getByLabelText("第 2 / 3 页")).toHaveAttribute("aria-current", "page");
    await user.click(screen.getByRole("button", { name: "上一页" }));
    await user.click(screen.getByRole("button", { name: "下一页" }));

    expect(onPageChange).toHaveBeenNthCalledWith(1, 1);
    expect(onPageChange).toHaveBeenNthCalledWith(2, 3);
  });

  it("disables unavailable directions while loading", () => {
    render(<Pagination loading onPageChange={() => undefined} page={1} totalItems={12} totalPages={1} />);

    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });
});
