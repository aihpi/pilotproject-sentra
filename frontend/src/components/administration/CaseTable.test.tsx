import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EvalCase } from "@/types";
import { CaseTable } from "./CaseTable";

/** Sorting the Testfälle table (#252).
 *
 *  What is easy to get wrong here is the order itself rather than the click:
 *  Case numbers are numbers, and the statuses have a workflow order that the
 *  alphabet does not know about. */

function testCase(
  tag: string,
  frage: string,
  status: "entwurf" | "freigegeben",
  withdrawn = false,
): EvalCase {
  return {
    // The tag's running number doubles as the case number here, so number
    // order and tag order agree and the expected orders stay readable.
    nummer: Number(tag.split("-")[1]),
    tag,
    kategorie: tag.split("-")[0],
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
  testCase("WI-010", "Was ist Strom?", "freigegeben"),
  testCase("WI-002", "Ökonomische Wirkungen?", "entwurf"),
  testCase("FI-001", "Arbeitsvolumen?", "freigegeben", true),
  testCase("WI-009", "Biomethan?", "entwurf"),
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

/** The tag in each row, in the order shown. */
function shownIds(): string[] {
  const rows = screen.getAllByRole("row").slice(1);
  return rows.map(
    (row) => within(row).getAllByRole("cell")[0].querySelector("span")?.textContent ?? "",
  );
}

function header(name: string) {
  return screen.getByRole("button", { name: new RegExp(`^${name}`) });
}

describe("sorting the Testfälle", () => {
  it("starts by number, counting it as a number rather than as characters", () => {
    renderTable();

    expect(shownIds()).toEqual(["FI-001", "WI-002", "WI-009", "WI-010"]);
  });

  it("reverses when the same header is clicked again", async () => {
    renderTable();

    await userEvent.click(header("Nr\\."));

    expect(shownIds()).toEqual(["WI-010", "WI-009", "WI-002", "FI-001"]);
    expect(screen.getByRole("columnheader", { name: /Nr\./ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  it("sorts by Kategorie, with the number deciding within one", async () => {
    renderTable();

    await userEvent.click(header("Kategorie"));

    expect(shownIds()).toEqual(["FI-001", "WI-002", "WI-009", "WI-010"]);
  });

  it("sorts the questions alphabetically, umlauts where a German reader expects them", async () => {
    renderTable();

    await userEvent.click(header("Ausgangsfrage"));

    // Arbeitsvolumen, Biomethan, Ökonomische, Was
    expect(shownIds()).toEqual(["FI-001", "WI-009", "WI-002", "WI-010"]);
  });

  it("sorts the status in workflow order, drafts first and withdrawn last", async () => {
    renderTable();

    await userEvent.click(header("Status"));

    expect(shownIds()).toEqual(["WI-002", "WI-009", "WI-010", "FI-001"]);
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
      ...testCase("WI-001", "Biomethan?", "entwurf"),
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
      ...testCase("WI-001", "Biomethan?", "entwurf"),
      freigabe_hindernisse: [],
    });

    expect(screen.queryByRole("list", { name: "Vor der Freigabe fehlt" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Freigeben" }));
    expect(onApprove).toHaveBeenCalledWith(1);
  });
});

describe("variants", () => {
  it("are offered for an approved case only (#265)", () => {
    render(
      <CaseTable
        cases={[
          testCase("WI-001", "Biomethan?", "freigegeben"),
          testCase("WI-002", "Strom?", "entwurf"),
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
