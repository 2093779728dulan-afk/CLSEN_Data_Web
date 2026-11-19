import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ContentReveal } from "./ContentReveal";
import { PageTransition } from "./PageTransition";

afterEach(cleanup);
it.each([PageTransition, ContentReveal])("shows content immediately instead of starting transparent: %s", Component => {
  const { container } = render(<Component><button>查看内容</button></Component>);
  expect(screen.getByRole("button", { name: "查看内容" })).toBeVisible();
  expect(container.firstElementChild).not.toHaveStyle({ opacity: "0" });
});
