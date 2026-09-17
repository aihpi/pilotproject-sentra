import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EvalRun, MachineVerdicts, QueueEntry, VorlageOptions } from "@/types";

/** The review screen, and mostly one property of it.
 *
 *  Section 6 of the Vorlage makes the disagreement between the automatic
 *  verdict and the human one the most important number in the process. It
 *  measures nothing if the reviewer saw the machine's answer first, so the
 *  screen must not show — or even fetch — a machine verdict before a sheet is
 *  submitted. The harness helps by keeping them out of the queue entirely, but
 *  a screen that fetched them early would defeat that, and only a test on this
 *  side can say it does not.
 */

const RUN: EvalRun = {
  id: "run-1",
  label: "Runde 2026-09",
  status: "abgeschlossen",
  sentra_base_url: "http://sentra",
  repeats: 2,
  started_at: "2026-09-17T10:00:00Z",
  completed_at: "2026-09-17T11:00:00Z",
  fehler: "",
  total: 3,
  done: 3,
  failed: 0,
  audit_ok: true,
};

const ENTRY: QueueEntry = {
  test_id: "TF-GO-001",
  kategorie: "GO",
  case_version_id: "cv-1",
  version: 1,
  ausgangsfrage: "Wie lange darf ein Redner im Plenum sprechen?",
  erwartete_antwort: "Grundsatz 15 Minuten je Fraktion nach § 35 GOBT.",
  referenz_korrekt: "GOBT § 35",
  referenz_falsch: "GOBT § 35 a. F.",
  grenzfall: false,
  gefunden_ueber: "Stufe 2 (auffällig markiert)",
  assessed: false,
  calls: [
    {
      id: "call-1",
      variant_key: "original",
      repeat_index: 0,
      text: "Nach § 35 GOBT gilt eine Redezeit von 15 Minuten [1].",
      sources: [
        {
          aktenzeichen: "WD 3 - 3000 - 029/23",
          title: "Redezeit im Plenum",
          source_file: "WD 3-029-23.pdf",
        },
      ],
      http_status: 200,
      dauer_ms: 24000,
    },
    {
      id: "call-2",
      variant_key: "original",
      repeat_index: 1,
      text: "Die Redezeit beträgt 15 Minuten je Fraktion [1].",
      sources: [
        {
          aktenzeichen: "WD 3 - 3000 - 029/23",
          title: "Redezeit im Plenum",
          source_file: "WD 3-029-23.pdf",
        },
      ],
      http_status: 200,
      dauer_ms: 25000,
    },
  ],
};

const OPTIONS: VorlageOptions = {
  quelle_4_3a: ["existiert & stimmt überein", "weicht ab", "existiert nicht", "entfällt"],
  quelle_4_3b: ["korrekte Quelle", "falsche bzw. veraltete Quelle"],
  quelle_4_3c: ["Quelle stützt Aussage", "stützt Aussage nicht"],
  reproduzierbar: ["einmalig", "wiederholt", "entfällt"],
  gefunden_ueber: ["Stufe 2 (auffällig markiert)"],
  schweregrad: { "1": "geringfügig", "2": "moderat", "3": "erheblich", "4": "kritisch" },
};

const VERDICTS: MachineVerdicts = {
  per_call: [
    {
      pruefung: "quellenauswahl",
      ergebnis: "falsche bzw. veraltete Quelle",
      auffaellig: true,
      belege: {},
    },
  ],
  per_group: [
    { pruefung: "wiederholbarkeit", ergebnis: "abweichend", auffaellig: false, belege: {} },
  ],
};

const fetchMachineVerdicts = vi.fn();
const submitVerdict = vi.fn();

vi.mock("@/lib/evalApi", () => ({
  fetchRuns: () => Promise.resolve([RUN]),
  fetchQueue: () => Promise.resolve([ENTRY]),
  fetchVorlageOptions: () => Promise.resolve(OPTIONS),
  submitVerdict: (...args: unknown[]) => submitVerdict(...args),
  fetchMachineVerdicts: (...args: unknown[]) => fetchMachineVerdicts(...args),
}));

const { EvaluationView } = await import("@/components/evaluation/EvaluationView");

async function renderAndWait() {
  render(<EvaluationView />);
  // The Test-ID appears twice on purpose: once in the queue, once on the case
  // pane beside the answer.
  await screen.findAllByText("TF-GO-001");
}

beforeEach(() => {
  fetchMachineVerdicts.mockReset().mockResolvedValue(VERDICTS);
  submitVerdict.mockReset().mockResolvedValue({});
});

describe("the review screen", () => {
  it("shows the case beside the answer", async () => {
    await renderAndWait();

    expect(screen.getByText(/Grundsatz 15 Minuten je Fraktion/)).toBeInTheDocument();
    expect(screen.getByText(/Nach § 35 GOBT gilt eine Redezeit/)).toBeInTheDocument();
  });

  it("offers a tab per repeat", async () => {
    await renderAndWait();

    expect(screen.getByRole("tab", { name: "W1" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "W2" })).toBeInTheDocument();
  });

  it("switches the answer when a tab is picked", async () => {
    await renderAndWait();

    await userEvent.click(screen.getByRole("tab", { name: "W2" }));

    expect(screen.getByText(/Die Redezeit beträgt 15 Minuten/)).toBeInTheDocument();
  });

  it("has one assessment form for the case, not one per repeat", async () => {
    await renderAndWait();

    // One Kernbefund box per answer, inside a single sheet.
    expect(screen.getAllByRole("button", { name: /Bewertung abschicken/ })).toHaveLength(1);
    expect(screen.getByText("Reproduzierbar?")).toBeInTheDocument();
  });
});

describe("the machine verdict is withheld until submit", () => {
  it("is not in the DOM before submitting", async () => {
    await renderAndWait();

    // Asserted on the check name and the auffällig badge, not on the verdict
    // text. The machine verdict and the assessment form share the Vorlage's
    // vocabulary — "falsche bzw. veraltete Quelle" is also an option in the
    // 4.3b dropdown, and has to be — so the presence of that string says
    // nothing about whether a verdict leaked.
    expect(screen.queryByText("quellenauswahl")).not.toBeInTheDocument();
    expect(screen.queryByText("auffällig")).not.toBeInTheDocument();
    expect(screen.queryByText("wiederholbarkeit")).not.toBeInTheDocument();
  });

  it("is not even fetched before submitting", async () => {
    await renderAndWait();
    await userEvent.click(screen.getByRole("tab", { name: "W2" }));

    expect(fetchMachineVerdicts).not.toHaveBeenCalled();
  });

  it("explains why the pane is empty", async () => {
    await renderAndWait();

    expect(screen.getByText(/zentrale Kennzahl des Verfahrens/)).toBeInTheDocument();
  });

  it("appears once a sheet is submitted", async () => {
    await renderAndWait();
    await submitSheet();

    await waitFor(() => expect(screen.getByText("quellenauswahl")).toBeInTheDocument());
    expect(fetchMachineVerdicts).toHaveBeenCalledWith("call-1");
  });
});

describe("the assessment form", () => {
  it("cannot be submitted without a name", async () => {
    await renderAndWait();
    await userEvent.selectOptions(
      screen.getByLabelText("4.3c Kontextprüfung"),
      "Quelle stützt Aussage",
    );

    expect(screen.getByRole("button", { name: /Bewertung abschicken/ })).toBeDisabled();
  });

  it("cannot be submitted without 4.3c, which is never prefilled", async () => {
    await renderAndWait();
    await userEvent.type(screen.getByLabelText("Tester/in"), "WD");

    expect(screen.getByRole("button", { name: /Bewertung abschicken/ })).toBeDisabled();
  });

  it("warns that severity 3 escalates to KISZ", async () => {
    await renderAndWait();

    await userEvent.selectOptions(screen.getByLabelText("Schweregrad"), "3");

    expect(screen.getByText(/gesondert an KISZ gemeldet/)).toBeInTheDocument();
  });

  it("sends one sheet with a finding per repeat", async () => {
    await renderAndWait();
    await submitSheet();

    await waitFor(() => expect(submitVerdict).toHaveBeenCalledTimes(1));
    const [runId, caseVersionId, verdict] = submitVerdict.mock.calls[0];
    expect(runId).toBe("run-1");
    expect(caseVersionId).toBe("cv-1");
    expect(verdict.kernbefunde).toEqual({ "original#0": "Stimmt." });
  });

  it("does not send gefunden_ueber, which the harness derives", async () => {
    await renderAndWait();
    await submitSheet();

    await waitFor(() => expect(submitVerdict).toHaveBeenCalled());
    expect(submitVerdict.mock.calls[0][2]).not.toHaveProperty("gefunden_ueber");
  });
});

async function submitSheet() {
  await userEvent.type(screen.getByLabelText("Tester/in"), "WD");
  await userEvent.selectOptions(
    screen.getByLabelText("4.3c Kontextprüfung"),
    "Quelle stützt Aussage",
  );
  await userEvent.type(screen.getAllByRole("textbox")[0], "Stimmt.");
  await userEvent.click(screen.getByRole("button", { name: /Bewertung abschicken/ }));
}

describe("the cited document", () => {
  it("is not shown until a source is picked", async () => {
    await renderAndWait();

    expect(screen.queryByTitle(/^PDF:/)).not.toBeInTheDocument();
  });

  it("opens in the same column as the answer, which stays visible", async () => {
    await renderAndWait();

    await userEvent.click(screen.getByRole("button", { name: /Redezeit im Plenum/ }));

    expect(screen.getByTitle("PDF: Redezeit im Plenum")).toBeInTheDocument();
    // 4.3c is a judgement about the claim and the passage together, so losing
    // the answer to open the source would defeat the point.
    expect(screen.getByText(/Nach § 35 GOBT gilt eine Redezeit/)).toBeInTheDocument();
  });

  it("closes again", async () => {
    await renderAndWait();
    await userEvent.click(screen.getByRole("button", { name: /Redezeit im Plenum/ }));

    await userEvent.click(screen.getByLabelText("Dokument schließen"));

    expect(screen.queryByTitle(/^PDF:/)).not.toBeInTheDocument();
  });
});
