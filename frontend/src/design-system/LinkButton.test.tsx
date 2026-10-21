import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";
import { LinkButton } from "./LinkButton";

it("keeps navigation as a link with its destination and target", () => {
  render(<MemoryRouter><LinkButton icon={<svg />} target="_blank" to="/ledger/published-details?mode=rows" variant="primary">查看明细</LinkButton></MemoryRouter>);
  const link = screen.getByRole("link", { name: "查看明细" });
  expect(link).toHaveAttribute("href", "/ledger/published-details?mode=rows");
  expect(link).toHaveAttribute("target", "_blank");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
