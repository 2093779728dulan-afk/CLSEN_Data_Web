import { createRef, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FormField } from "./FormField";
import { SearchInput } from "./SearchInput";

describe("SearchInput", () => {
  it("preserves the native field/ref contract and returns focus when cleared", async () => {
    const ref = createRef<HTMLInputElement>();
    function Example() {
      const [value, setValue] = useState("DEMO-01");
      return <FormField error="请输入有效款号" label="搜索审核项"><SearchInput onValueChange={setValue} ref={ref} value={value} /></FormField>;
    }
    render(<Example />);
    const input = screen.getByRole("searchbox", { name: "搜索审核项" });
    expect(ref.current).toBe(input);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("请输入有效款号");
    await userEvent.setup().click(screen.getByRole("button", { name: "清空搜索" }));
    expect(input).toHaveValue("");
    expect(input).toHaveFocus();
    expect(screen.queryByRole("button", { name: "清空搜索" })).not.toBeInTheDocument();
  });
  it("keeps disabled and readonly fields non-editable", () => {
    const { rerender } = render(<SearchInput aria-label="搜索" disabled onValueChange={() => undefined} value="DEMO" />);
    expect(screen.getByRole("searchbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "清空搜索" })).toBeDisabled();
    rerender(<SearchInput aria-label="搜索" onValueChange={() => undefined} readOnly value="DEMO" />);
    expect(screen.getByRole("searchbox")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "清空搜索" })).not.toBeInTheDocument();
  });
});
