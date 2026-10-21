import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { Dialog } from "./Dialog";

function DialogHarness() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button onClick={() => setOpen(true)} type="button">打开商品信息</button>
      <Dialog closeLabel="关闭商品信息" onOpenChange={setOpen} open={open} title="基础款衬衫">
        <button type="button">查看变体</button>
      </Dialog>
    </>
  );
}

describe("Dialog", () => {
  it("closes with Escape and returns focus to the opener", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);

    const opener = screen.getByRole("button", { name: "打开商品信息" });
    await user.click(opener);

    expect(screen.getByRole("dialog", { name: "基础款衬衫" })).toBeVisible();
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(opener).toHaveFocus());
  });
});
