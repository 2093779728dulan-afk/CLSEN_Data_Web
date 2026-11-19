import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ProductionBuildNotice } from "./ProductionBuildNotice";

afterEach(() => { cleanup(); document.querySelectorAll('script[data-build-test]').forEach(node => node.remove()); vi.unstubAllGlobals(); });
function mountBuild() {
  const script = document.createElement("script"); script.type = "module"; script.src = "/assets/current.js"; script.dataset.buildTest = "true"; document.head.append(script);
  render(<MemoryRouter><ProductionBuildNotice /></MemoryRouter>);
}
it("announces an updated build on focus without replacing the page or reloading", async () => {
  const fetchBuild = vi.fn().mockResolvedValueOnce(new Response('<script type="module" src="/assets/current.js"></script>')).mockResolvedValueOnce(new Response('<script type="module" src="/assets/updated.js"></script>'));
  vi.stubGlobal("fetch", fetchBuild); mountBuild();
  await waitFor(() => expect(fetchBuild).toHaveBeenCalledTimes(1));
  expect(screen.queryByText("体验版本已更新")).not.toBeInTheDocument();
  act(() => { window.dispatchEvent(new Event("focus")); });
  expect(await screen.findByText("体验版本已更新")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存后刷新版本" })).toBeEnabled();
  expect(document.querySelector('script[data-build-test]')).toHaveAttribute("src", "/assets/current.js");
});
it("keeps the page usable when the version check fails", async () => {
  const fetchBuild = vi.fn().mockRejectedValue(new TypeError("offline")); vi.stubGlobal("fetch", fetchBuild); mountBuild();
  await waitFor(() => expect(fetchBuild).toHaveBeenCalledTimes(1));
  expect(screen.queryByText("体验版本已更新")).not.toBeInTheDocument();
});
