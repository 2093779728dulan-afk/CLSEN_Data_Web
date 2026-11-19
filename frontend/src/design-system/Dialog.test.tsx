import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { Dialog } from "./Dialog";

afterEach(cleanup);

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

it("renders in the supplied native modal container", () => {
  const container = document.createElement("dialog");
  container.setAttribute("open", "");
  document.body.append(container);
  const view = render(<Dialog portalContainer={container} open onOpenChange={() => undefined} title="原生窗口中的确认"><button>继续填写</button></Dialog>);
  expect(container.querySelector('[role="dialog"]')).toBe(screen.getByRole("dialog", { name: "原生窗口中的确认" }));
  view.unmount();
  container.remove();
});
