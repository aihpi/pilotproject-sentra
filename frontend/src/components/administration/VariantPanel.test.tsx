import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EvalVariant } from "@/types";

/** The three rewordings of a question (4.2, #265).
 *
 *  What matters is the gate: a proposal can be corrected before it is
 *  approved, an approved one is frozen, and the approval carries the name of
 *  whoever is signed in. A judge model that fails has to say so. */

const fetchVariants = vi.fn();
const proposeVariants = vi.fn();
const editVariant = vi.fn();
const approveVariant = vi.fn();

vi.mock("@/lib/evalApi", () => ({
  fetchVariants: (...a: unknown[]) => fetchVariants(...a),
  proposeVariants: (...a: unknown[]) => proposeVariants(...a),
  editVariant: (...a: unknown[]) => editVariant(...a),
  approveVariant: (...a: unknown[]) => approveVariant(...a),
}));

const { VariantPanel } = await import("@/components/administration/VariantPanel");

function variant(stil: string, wortlaut: string, approved = false): EvalVariant {
  return {
    stil,
    wortlaut,
    status: approved ? "freigegeben" : "vorgeschlagen",
    erstellt_durch: "LLM (Erststellung)",
    freigegeben_durch: approved ? "mario" : "",
    freigegeben_at: approved ? "2026-10-16T10:00:00Z" : null,
  };
}

const PROPOSED = [
  variant("umgangssprachlich", "Muss man Dry Income versteuern?"),
  variant("fachsprachlich", "Unterliegt Dry Income der Einkommensteuer?"),
  variant("verkuerzt", "Dry Income Besteuerung"),
];

beforeEach(() => {
  fetchVariants.mockReset();
  proposeVariants.mockReset();
  editVariant.mockReset();
  approveVariant.mockReset();
});

describe("variants of a case", () => {
  it("are proposed on request", async () => {
    fetchVariants.mockResolvedValue([]);
    proposeVariants.mockResolvedValue(PROPOSED);
    render(<VariantPanel testId="TF-FI-001" approver="mario" />);

    await userEvent.click(await screen.findByRole("button", { name: "Varianten vorschlagen" }));

    expect(proposeVariants).toHaveBeenCalledWith("TF-FI-001");
    expect(await screen.findByDisplayValue("Dry Income Besteuerung")).toBeInTheDocument();
  });

  it("can be corrected before approval", async () => {
    fetchVariants.mockResolvedValue(PROPOSED);
    editVariant.mockResolvedValue(variant("verkuerzt", "Besteuerung Dry Income"));
    render(<VariantPanel testId="TF-FI-001" approver="mario" />);

    const box = await screen.findByLabelText("Variante Verkürzt");
    await userEvent.clear(box);
    await userEvent.type(box, "Besteuerung Dry Income");
    await userEvent.click(screen.getByRole("button", { name: "Speichern" }));

    expect(editVariant).toHaveBeenCalledWith("TF-FI-001", "verkuerzt", "Besteuerung Dry Income");
  });

  it("are approved in the name of whoever is signed in", async () => {
    fetchVariants.mockResolvedValue(PROPOSED);
    approveVariant.mockResolvedValue(
      variant("fachsprachlich", "Unterliegt Dry Income der Einkommensteuer?", true),
    );
    render(<VariantPanel testId="TF-FI-001" approver="mario" />);

    await screen.findByLabelText("Variante Fachsprachlich");
    await userEvent.click(screen.getAllByRole("button", { name: "Freigeben" })[1]);

    expect(approveVariant).toHaveBeenCalledWith("TF-FI-001", "fachsprachlich", "mario");
    expect(await screen.findByText("freigegeben von mario")).toBeInTheDocument();
  });

  it("are frozen once approved", async () => {
    fetchVariants.mockResolvedValue(PROPOSED.map((v) => ({ ...v, ...variant(v.stil, v.wortlaut, true) })));
    render(<VariantPanel testId="TF-FI-001" approver="mario" />);

    expect(await screen.findByText("Dry Income Besteuerung")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /vorschlagen/ })).toBeNull();
  });

  it("say why when the judge model cannot propose any", async () => {
    fetchVariants.mockResolvedValue([]);
    proposeVariants.mockRejectedValue(
      new Error("Die Varianten konnten nicht erzeugt werden: Judge nicht konfiguriert"),
    );
    render(<VariantPanel testId="TF-FI-001" approver="mario" />);

    await userEvent.click(await screen.findByRole("button", { name: "Varianten vorschlagen" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Judge nicht konfiguriert");
  });
});
