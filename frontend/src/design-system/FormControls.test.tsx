import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FormField } from "./FormField";
import { Input } from "./Input";
import { Select } from "./Select";

describe("shared form controls", () => {
  it("associates an input with its label and hint", () => {
    render(
      <FormField hint="可搜索款号或名称" label="搜索产品">
        <Input defaultValue="2301" />
      </FormField>,
    );

    const input = screen.getByRole("textbox", { name: "搜索产品" });
    expect(input).toHaveValue("2301");
    expect(input).toHaveAccessibleDescription("可搜索款号或名称");
  });

  it("exposes field errors to a native select", () => {
    render(
      <FormField error="请选择状态" label="日期状态">
        <Select defaultValue="">
          <option value="">请选择</option>
          <option value="complete">完整发布</option>
        </Select>
      </FormField>,
    );

    const select = screen.getByRole("combobox", { name: "日期状态" });
    expect(select).toHaveAttribute("aria-invalid", "true");
    expect(select).toHaveAccessibleDescription("请选择状态");
  });
});
