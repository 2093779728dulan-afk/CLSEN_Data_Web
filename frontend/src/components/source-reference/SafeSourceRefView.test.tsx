import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SafeSourceRefView } from "./SafeSourceRefView";

describe("SafeSourceRefView", () => {
  it("renders only safe preview, digest suffix, and safety badges", () => {
    const { container } = render(
      <SafeSourceRefView
        source={{
          digest: `sha256:${"a".repeat(56)}12345678`,
          is_truncated: true,
          is_unsafe: true,
          preview: "safe preview",
          source_ref_id: "raw-dangerous-value",
        }}
      />,
    );
    expect(screen.getByText("safe preview")).toBeVisible();
    expect(screen.getByText("12345678")).toBeVisible();
    expect(screen.getByText("含危险字符")).toBeVisible();
    expect(container.innerHTML).not.toContain("raw-dangerous-value");
  });

  it("fails closed when an upstream preview still contains structural characters", () => {
    const dangerous = 'LIVE-DANGER</script>&"RAW';
    const { container } = render(
      <SafeSourceRefView
        source={{
          digest: `sha256:${"b".repeat(64)}`,
          is_truncated: false,
          is_unsafe: false,
          preview: dangerous,
          source_ref_id: "src_structural",
        }}
      />,
    );

    expect(screen.getByText("[含危险字符的来源]")).toBeVisible();
    expect(screen.getByText("含危险字符")).toBeVisible();
    expect(container.textContent).not.toContain(dangerous);
  });
});
