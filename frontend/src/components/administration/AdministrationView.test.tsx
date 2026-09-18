import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EvalCase } from "@/types";

/** Administering the test set.
 *
 *  What is worth holding here is the behaviour that follows from the case
 *  store's rules, because the screen is where somebody meets them:
 *
 *    an approved version is never edited — asking to change one adds a new
 *    version, and the screen has to say so rather than appearing to edit in
 *    place
 *
 *    a Grenzfall has no correct source, and must not be pushed into inventing
 *    one. That was #130 from the other end, and it made technique 4.4
 *    unreachable
 *
 *    withdrawal is not deletion. The Test-ID stays spent
 */

const APPROVED: EvalCase = {
  test_id: "TF-GO-001",
  kategorie: "GO",
  created_at: "2026-09-18T10:00:00Z",
  zurueckgezogen_at: null,
  versions: [
    {
      version: 1,
      status: "freigegeben",
      ausgangsfrage: "Wie lange darf ein Redner im Plenum sprechen?",
      abteilung: "Hotline",
      erwartete_antwort: "15 Minuten je Fraktion nach § 35 GOBT.",
      referenz_korrekt: "GOBT § 35",
      referenz_falsch: "",
      referenz_korrekt_az: "WD 3 - 3000 - 029/23",
      referenz_falsch_az: "",
      grund_fuer_aufnahme: "Häufigste Frage.",
      grenzfall: false,
      created_at: "2026-09-18T10:00:00Z",
      freigegeben_at: "2026-09-18T10:05:00Z",
    },
  ],
};

const DRAFT: EvalCase = {
  ...APPROVED,
  test_id: "TF-AR-001",
  kategorie: "AR",
  versions: [
    {
      ...APPROVED.versions[0],
      status: "entwurf",
      freigegeben_at: null,
      ausgangsfrage: "Mondtagegeldpauschale zum Mars?",
      erwartete_antwort: "Keine Antwort.",
      referenz_korrekt: "",
      referenz_korrekt_az: "",
      grenzfall: true,
    },
  ],
};

const WITHDRAWN: EvalCase = {
  ...APPROVED,
  test_id: "TF-GV-001",
  zurueckgezogen_at: "2026-09-18T11:00:00Z",
};

const fetchCases = vi.fn();
const createCase = vi.fn();
const updateCase = vi.fn();
const approveCase = vi.fn();
const withdrawCase = vi.fn();

vi.mock("@/lib/evalApi", () => ({
  fetchCases: (...a: unknown[]) => fetchCases(...a),
  createCase: (...a: unknown[]) => createCase(...a),
  updateCase: (...a: unknown[]) => updateCase(...a),
  approveCase: (...a: unknown[]) => approveCase(...a),
  withdrawCase: (...a: unknown[]) => withdrawCase(...a),
  fetchRuns: () => Promise.resolve([]),
  fetchRun: () => Promise.resolve({}),
  importSheet: () => Promise.resolve({}),
  startRun: () => Promise.resolve({}),
}));

const { AdministrationView } = await import(
  "@/components/administration/AdministrationView"
);

async function renderWith(cases: EvalCase[]) {
  fetchCases.mockResolvedValue(cases);
  render(<AdministrationView />);
  await screen.findByText(/Testfälle \(/);
}

beforeEach(() => {
  [fetchCases, createCase, updateCase, approveCase, withdrawCase].forEach((m) => m.mockReset());
  createCase.mockResolvedValue(APPROVED);
  updateCase.mockResolvedValue(APPROVED);
  approveCase.mockResolvedValue(APPROVED);
  withdrawCase.mockResolvedValue(WITHDRAWN);
});

describe("the case list", () => {
  it("shows what state each case is in", async () => {
    await renderWith([APPROVED, DRAFT]);

    expect(screen.getByText("TF-GO-001")).toBeInTheDocument();
    expect(screen.getByText("freigegeben")).toBeInTheDocument();
    expect(screen.getByText("entwurf")).toBeInTheDocument();
  });

  it("offers approval only where there is a draft to approve", async () => {
    await renderWith([APPROVED, DRAFT]);

    expect(screen.getAllByRole("button", { name: "Freigeben" })).toHaveLength(1);
  });

  it("offers nothing on a withdrawn case", async () => {
    await renderWith([WITHDRAWN]);

    expect(screen.getByText("zurückgezogen")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zurückziehen/ })).not.toBeInTheDocument();
  });

  it("says that withdrawing is not deleting", async () => {
    await renderWith([APPROVED]);

    expect(screen.getByText(/nie erneut vergeben/)).toBeInTheDocument();
  });

  it("says what to do when there are no cases at all", async () => {
    await renderWith([]);

    expect(screen.getByText(/Erfassungsvorlage oben/)).toBeInTheDocument();
  });
});

describe("editing an approved case", () => {
  it("is offered as a new version, not as an edit", async () => {
    await renderWith([APPROVED]);

    expect(screen.getByRole("button", { name: "Neue Version" })).toBeInTheDocument();
  });

  it("says why, before anything is typed", async () => {
    await renderWith([APPROVED]);

    await userEvent.click(screen.getByRole("button", { name: "Neue Version" }));

    expect(screen.getByText(/abgeschlossene Runden gegen sie gemessen/)).toBeInTheDocument();
  });

  it("does not send the category, which the Test-ID is built from", async () => {
    await renderWith([APPROVED]);
    await userEvent.click(screen.getByRole("button", { name: "Neue Version" }));

    await userEvent.click(screen.getByRole("button", { name: "Neue Version anlegen" }));

    await waitFor(() => expect(updateCase).toHaveBeenCalled());
    expect(updateCase.mock.calls[0][1]).not.toHaveProperty("kategorie");
  });
});

describe("what a case cannot be saved without", () => {
  it("refuses an ordinary case with no correct source", async () => {
    await renderWith([]);
    await userEvent.click(screen.getByRole("button", { name: "Neuer Testfall" }));

    await userEvent.type(screen.getByLabelText("Ausgangsfrage"), "Eine Frage?");
    await userEvent.type(screen.getByLabelText("Erwartete Antwort"), "Eine Antwort.");

    expect(screen.getByText(/außer bei einem Grenzfall/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();
  });

  it("asks a Grenzfall for no source at all", async () => {
    /** #130 from the other end: demanding one made technique 4.4 unreachable,
     *  because a question the corpus does not cover has no correct source. */
    await renderWith([]);
    await userEvent.click(screen.getByRole("button", { name: "Neuer Testfall" }));

    await userEvent.type(screen.getByLabelText("Ausgangsfrage"), "Mars?");
    await userEvent.type(screen.getByLabelText("Erwartete Antwort"), "Keine Antwort.");
    await userEvent.click(screen.getByLabelText(/Grenzfall/));

    expect(screen.queryByText(/außer bei einem Grenzfall/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Speichern" })).toBeEnabled();
  });

  it("always requires an expected answer", async () => {
    await renderWith([]);
    await userEvent.click(screen.getByRole("button", { name: "Neuer Testfall" }));

    await userEvent.type(screen.getByLabelText("Ausgangsfrage"), "Eine Frage?");
    await userEvent.click(screen.getByLabelText(/Grenzfall/));

    expect(screen.getByText(/Ohne erwartete Antwort/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();
  });
});

describe("failures", () => {
  it("shows the server's reason for refusing approval", async () => {
    approveCase.mockRejectedValue(
      new Error("TF-AR-001 version 1 cannot be approved: erwartete Antwort is missing."),
    );
    await renderWith([DRAFT]);

    await userEvent.click(screen.getByRole("button", { name: "Freigeben" }));

    expect(await screen.findByText(/cannot be approved/)).toBeInTheDocument();
  });
});
