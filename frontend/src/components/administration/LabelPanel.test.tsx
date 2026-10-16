import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EvalCase, LabelValues } from "@/types";

/** Editing a case's tag and labels (#288).
 *
 *  What matters: only what changed is sent, labels before the tag so a tag
 *  typed in is the last word, an empty tag asks for a generated one, and a
 *  refusal (a tag already taken) is shown rather than swallowed. */

const setLabels = vi.fn();
const setTag = vi.fn();

vi.mock("@/lib/evalApi", () => ({
  setLabels: (...a: unknown[]) => setLabels(...a),
  setTag: (...a: unknown[]) => setTag(...a),
}));

const { LabelPanel } = await import("@/components/administration/LabelPanel");

const CASE: EvalCase = {
  nummer: 7,
  tag: "FI-007",
  tag_manuell: false,
  kategorie: "FI",
  testart: "",
  frageform: "konkret",
  herkunft: "Prüfer-Vorlage",
  created_at: "2026-10-16T10:00:00Z",
  zurueckgezogen_at: null,
  versions: [],
};

const OFFERED: LabelValues = {
  kategorie: ["GO", "FI", "WI"],
  testart: ["Regelfall", "Präzision"],
  frageform: ["allgemein", "konkret"],
  herkunft: ["Prüfer-Vorlage", "manuell"],
};

beforeEach(() => {
  setLabels.mockReset().mockResolvedValue(CASE);
  setTag.mockReset().mockResolvedValue(CASE);
});

function renderPanel(onSaved = vi.fn()) {
  render(<LabelPanel entry={CASE} offered={OFFERED} onSaved={onSaved} />);
  return onSaved;
}

describe("a case's labels", () => {
  it("sends only what changed, and says it is saved", async () => {
    const onSaved = renderPanel();

    await userEvent.type(screen.getByLabelText("Testart"), "Präzision");
    await userEvent.click(screen.getByRole("button", { name: "Speichern" }));

    expect(setLabels).toHaveBeenCalledWith(7, { testart: "Präzision" });
    expect(setTag).not.toHaveBeenCalled();
    expect(onSaved).toHaveBeenCalled();
  });

  it("accepts a value that is not offered yet", async () => {
    renderPanel();

    await userEvent.type(screen.getByLabelText("Testart"), "Rechenweg");
    await userEvent.click(screen.getByRole("button", { name: "Speichern" }));

    expect(setLabels).toHaveBeenCalledWith(7, { testart: "Rechenweg" });
  });

  it("sets the tag after the labels, so the typed tag wins", async () => {
    renderPanel();

    await userEvent.type(screen.getByLabelText("Testart"), "Präzision");
    await userEvent.clear(screen.getByLabelText("Tag"));
    await userEvent.type(screen.getByLabelText("Tag"), "FI-Rechnung");
    await userEvent.click(screen.getByRole("button", { name: "Speichern" }));

    expect(setLabels.mock.invocationCallOrder[0]).toBeLessThan(
      setTag.mock.invocationCallOrder[0],
    );
    expect(setTag).toHaveBeenCalledWith(7, "FI-Rechnung");
  });

  it("asks for a generated tag when the tag is emptied", async () => {
    renderPanel();

    await userEvent.clear(screen.getByLabelText("Tag"));
    await userEvent.click(screen.getByRole("button", { name: "Speichern" }));

    expect(setTag).toHaveBeenCalledWith(7, "");
  });

  it("offers nothing to save until something changed", () => {
    renderPanel();

    expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();
  });

  it("shows why a tag was refused", async () => {
    setTag.mockRejectedValue(new Error("Der Tag 'GO-001' ist schon vergeben."));
    const onSaved = renderPanel();

    await userEvent.clear(screen.getByLabelText("Tag"));
    await userEvent.type(screen.getByLabelText("Tag"), "GO-001");
    await userEvent.click(screen.getByRole("button", { name: "Speichern" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("schon vergeben");
    expect(onSaved).not.toHaveBeenCalled();
  });
});
