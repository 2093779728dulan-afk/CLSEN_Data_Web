import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NoteRevisionEditor } from "./NoteRevisionEditor";
const note = { note_key: "synthetic-1", note_id: 801, revision_number: 1, body: "原说明", visibility: "internal" as const };
describe("NoteRevisionEditor", () => {
  it("locks inputs during its own pending request and keeps the exact note/values", async () => {
    const revise = vi.fn(() => new Promise<void>(() => {})); const user = userEvent.setup();
    render(<NoteRevisionEditor busy={false} note={note} onRevise={revise} />);
    await user.click(screen.getByRole("button", { name: "修订备注" }));
    await user.clear(screen.getByRole("textbox")); await user.type(screen.getByRole("textbox"), " 新说明 ");
    await user.selectOptions(screen.getByRole("combobox"), "viewer_visible");
    await user.click(screen.getByRole("button", { name: "保存新修订" }));
    expect(screen.getByRole("textbox")).toBeDisabled(); expect(screen.getByRole("combobox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消修订" })).toBeDisabled();
    expect(revise).toHaveBeenCalledExactlyOnceWith(note, " 新说明 ", "viewer_visible");
  });
  it("retains rejected content, forces batch visibility, and returns focus on explicit retry", async () => {
    const revise = vi.fn().mockRejectedValueOnce(new Error("虚构保存失败")).mockResolvedValue(undefined); const user = userEvent.setup();
    render(<NoteRevisionEditor busy={false} internalOnly note={{ ...note, visibility: "viewer_visible" }} onRevise={revise} />);
    await user.click(screen.getByRole("button", { name: "修订备注" }));
    await user.clear(screen.getByRole("textbox")); await user.type(screen.getByRole("textbox"), "保留的修订");
    await user.click(screen.getByRole("button", { name: "保存新修订" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("修订内容已保留");
    expect(screen.getByRole("textbox")).toHaveValue("保留的修订"); expect(revise).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "保存新修订" }));
    expect(revise.mock.calls[0]).toEqual(revise.mock.calls[1]); expect(revise.mock.calls[1]?.[2]).toBe("internal");
    expect(screen.getByRole("button", { name: "修订备注" })).toHaveFocus();
  });
});
