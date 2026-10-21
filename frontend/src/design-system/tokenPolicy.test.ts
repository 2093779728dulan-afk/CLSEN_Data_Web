import { describe, expect, it } from "vitest";

import { checkTokenPolicy, type TokenPolicyAllowlist } from "../../scripts/tokenPolicy";

const emptyAllowlist: TokenPolicyAllowlist = { schema_version: 1, exceptions: [] };

describe("design-system token policy", () => {
  it("reports raw colors and motion durations in component CSS", () => {
    expect(checkTokenPolicy([{
      path: "src/design-system/Example.module.css",
      content: [
        ".root { color: #fff; }",
        ".overlay { background: rgb(16 38 58 / 54%); }",
        ".enter { animation: fade-in 180ms ease; }",
      ].join("\n"),
    }], emptyAllowlist)).toEqual([
      { file: "src/design-system/Example.module.css", line: 1, rule: "raw-color", value: "#fff" },
      { file: "src/design-system/Example.module.css", line: 2, rule: "raw-color", value: "rgb(16 38 58 / 54%)" },
      { file: "src/design-system/Example.module.css", line: 3, rule: "raw-motion-duration", value: "180ms" },
    ]);
  });

  it("accepts semantic tokens and non-motion layout dimensions", () => {
    expect(checkTokenPolicy([{
      path: "src/design-system/Example.module.css",
      content: ".root { color: var(--color-text); width: 180px; transition: color var(--motion-duration-fast); }",
    }], emptyAllowlist)).toEqual([]);
  });

  it("requires reviewer metadata for every exception", () => {
    expect(() => checkTokenPolicy([], {
      schema_version: 1,
      exceptions: [{
        file: "src/design-system/Example.module.css",
        rule: "raw-color",
        value: "#fff",
        reason: "",
        approved_by: "",
      }],
    })).toThrow("reason and approved_by");
  });

  it("applies a fully recorded exact exception", () => {
    expect(checkTokenPolicy([{
      path: "src/design-system/Example.module.css",
      content: ".root { color: #fff; }",
    }], {
      schema_version: 1,
      exceptions: [{
        file: "src/design-system/Example.module.css",
        rule: "raw-color",
        value: "#fff",
        reason: "第三方品牌色无法映射语义 Token",
        approved_by: "项目负责人管理员",
      }],
    })).toEqual([]);
  });
});
