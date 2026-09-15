import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PromptDialog } from "./PromptDialog";

const DEFAULT = "Du bist ein Assistent der Wissenschaftlichen Dienste.";

function setup(props: Partial<React.ComponentProps<typeof PromptDialog>> = {}) {
  const onApply = vi.fn();
  const onDraftChange = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <PromptDialog
      open
      onOpenChange={onOpenChange}
      draft={DEFAULT}
      onDraftChange={onDraftChange}
      defaultPrompt={DEFAULT}
      onApply={onApply}
      {...props}
    />,
  );
  return { onApply, onDraftChange, onOpenChange };
}

describe("PromptDialog", () => {
  it("renders nothing while closed", () => {
    const { onApply } = setup({ open: false });
    expect(screen.queryByText("KI-Anweisungen")).not.toBeInTheDocument();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("shows the draft for editing", () => {
    setup({ draft: "Meine eigenen Anweisungen" });
    expect(screen.getByRole("textbox")).toHaveValue("Meine eigenen Anweisungen");
  });

  it("reports edits as they are typed", async () => {
    const { onDraftChange } = setup({ draft: "" });
    await userEvent.type(screen.getByRole("textbox"), "X");
    expect(onDraftChange).toHaveBeenCalledWith("X");
  });

  it("restores the default without applying it", async () => {
    const { onDraftChange, onApply } = setup({ draft: "etwas anderes" });
    await userEvent.click(screen.getByRole("button", { name: /Standard wiederherstellen/ }));

    expect(onDraftChange).toHaveBeenCalledWith(DEFAULT);
    expect(onApply).not.toHaveBeenCalled();
  });

  it("cancelling applies nothing", async () => {
    const { onApply, onOpenChange } = setup({ draft: "etwas anderes" });
    await userEvent.click(screen.getByRole("button", { name: "Abbrechen" }));

    expect(onApply).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  describe("what Übernehmen reports", () => {
    // The distinction that matters. null means no system_prompt is sent and
    // the server applies its own default, so a later change to that default
    // reaches this user. Sending back text equal to the default would pin
    // them to today's copy of it forever.
    it("text unchanged from the default reports null", async () => {
      const { onApply } = setup({ draft: DEFAULT });
      await userEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
      expect(onApply).toHaveBeenCalledWith(null);
    });

    it("whitespace-only differences still count as unchanged", async () => {
      const { onApply } = setup({ draft: `  ${DEFAULT}\n` });
      await userEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
      expect(onApply).toHaveBeenCalledWith(null);
    });

    it("edited text is reported as it was typed", async () => {
      const edited = `${DEFAULT} Antworte knapp.`;
      const { onApply } = setup({ draft: edited });
      await userEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
      expect(onApply).toHaveBeenCalledWith(edited);
    });

    it("closes afterwards", async () => {
      const { onOpenChange } = setup({ draft: "etwas anderes" });
      await userEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });
});
