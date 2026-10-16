import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EvalCase } from "@/types";
import { CaseTable } from "./CaseTable";

/** Sorting the Testfälle table (#252).
 *
 *  What is easy to get wrong here is the order itself rather than the click:
 *  Test-IDs carry a number, and the statuses have a workflow order that the
 *  alphabet does not know about. */

function testCase(
  testId: string,
  frage: string,
  status: "entwurf" | "freigegeben",
  withdrawn = false,
): EvalCase {
  return {
    test_id: testId,
    kategorie: testId.split("-")[1],
    created_at: "2026-10-08T10:00:00Z",
    zurueckgezogen_at: withdrawn ? "2026-10-09T10:00:00Z" : null,
    versions: [
      {
        version: 1,
        status,
        ausgangsfrage: frage,
        abteilung: "",
        erwartete_antwort: "Antwort.",
        referenz_korrekt: "Quelle",
        referenz_falsch: "",
        referenz_korrekt_az: "",
        referenz_falsch_az: "",
        grund_fuer_aufnahme: "",
        grenzfall: false,
        created_at: "2026-10-08T10:00:00Z",
        freigegeben_at: status === "freigegeben" ? "2026-10-08T11:00:00Z" : null,
      },
    ],
  };
}

const CASES = [
  testCase("TF-WI-010", "Was ist Strom?", "freigegeben"),
  testCase("TF-WI-002", "Ökonomische Wirkungen?", "entwurf"),
  testCase("TF-FI-001", "Arbeitsvolumen?", "freigegeben", true),
  testCase("TF-WI-009", "Biomethan?", "entwurf"),
];

function renderTable() {
  render(
    <CaseTable
      cases={CASES}
      busy={false}
      onCreate={vi.fn()}
      onEdit={vi.fn()}
      onApprove={vi.fn()}
      onWithdraw={vi.fn()}
    />,
  );
}

function shownIds(): string[] {
  const rows = screen.getAllByRole("row").slice(1);
  return rows.map((row) => within(row).getAllByRole("cell")[0].textContent ?? "");
}

function header(name: string) {
  return screen.getByRole("button", { name: new RegExp(`^${name}`) });
}

describe("sorting the Testfälle", () => {
  it("starts by Test-ID, counting the number rather than the characters", () => {
    renderTable();

    expect(shownIds()).toEqual(["TF-FI-001", "TF-WI-002", "TF-WI-009", "TF-WI-010"]);
  });

  it("reverses when the same header is clicked again", async () => {
    renderTable();

    await userEvent.click(header("Test-ID"));

    expect(shownIds()).toEqual(["TF-WI-010", "TF-WI-009", "TF-WI-002", "TF-FI-001"]);
    expect(screen.getByRole("columnheader", { name: /Test-ID/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  it("sorts by Kategorie, with Test-ID deciding within one", async () => {
    renderTable();

    await userEvent.click(header("Kategorie"));

    expect(shownIds()).toEqual(["TF-FI-001", "TF-WI-002", "TF-WI-009", "TF-WI-010"]);
  });

  it("sorts the questions alphabetically, umlauts where a German reader expects them", async () => {
    renderTable();

    await userEvent.click(header("Ausgangsfrage"));

    // Arbeitsvolumen, Biomethan, Ökonomische, Was
    expect(shownIds()).toEqual(["TF-FI-001", "TF-WI-009", "TF-WI-002", "TF-WI-010"]);
  });

  it("sorts the status in workflow order, drafts first and withdrawn last", async () => {
    renderTable();

    await userEvent.click(header("Status"));

    expect(shownIds()).toEqual(["TF-WI-002", "TF-WI-009", "TF-WI-010", "TF-FI-001"]);
  });
});

describe("what a draft still needs before approval", () => {
  function renderWith(entry: EvalCase) {
    const onApprove = vi.fn();
    render(
      <CaseTable
        cases={[entry]}
        busy={false}
        onCreate={vi.fn()}
        onEdit={vi.fn()}
        onApprove={onApprove}
        onWithdraw={vi.fn()}
      />,
    );
    return onApprove;
  }

  it("lists the blockers and offers no working Freigeben", async () => {
    const onApprove = renderWith({
      ...testCase("TF-WI-001", "Biomethan?", "entwurf"),
      freigabe_hindernisse: ["WD 5 - 3000 - 074/26 ist nicht im Bestand, bitte erst einlesen"],
    });

    expect(screen.getByText(/074\/26 ist nicht im Bestand/)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Freigeben" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("leaves a complete draft as it was", async () => {
    const onApprove = renderWith({
      ...testCase("TF-WI-001", "Biomethan?", "entwurf"),
      freigabe_hindernisse: [],
    });

    expect(screen.queryByRole("list", { name: "Vor der Freigabe fehlt" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Freigeben" }));
    expect(onApprove).toHaveBeenCalledWith("TF-WI-001");
  });
});

describe("variants", () => {
  it("are offered for an approved case only (#265)", () => {
    render(
      <CaseTable
        cases={[
          testCase("TF-WI-001", "Biomethan?", "freigegeben"),
          testCase("TF-WI-002", "Strom?", "entwurf"),
        ]}
        busy={false}
        onCreate={vi.fn()}
        onEdit={vi.fn()}
        onApprove={vi.fn()}
        onWithdraw={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("button", { name: "Varianten" })).toHaveLength(1);
  });
});
