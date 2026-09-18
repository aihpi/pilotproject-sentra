import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Agreement, Sheet, Trend, TriageSummary, Verdict } from "@/types";

/** What a round concluded, and mostly one property of it.
 *
 *  A disagreement rate of zero and no rate at all are different facts. Zero
 *  means the checks and the reviewers agreed on everything they both looked
 *  at; null means nobody has looked. Rendering null as "0 %" would report
 *  perfect agreement from a round nobody has reviewed — the most flattering
 *  possible way to be wrong about the number that calibrates the Prüfschwelle,
 *  and the kind of wrong nobody goes looking for.
 */

const TRIAGE: TriageSummary = {
  gesamt: 2,
  stufe_2: 1,
  stufe_3: 0,
  grenzfaelle: 1,
  unauffaellig: 0,
};

const NOBODY_LOOKED: Agreement = {
  einig: 0,
  zu_streng: 0,
  zu_grosszuegig: 0,
  nicht_bewertet: 2,
  abweichungsquote: null,
};

const EVERYONE_AGREED: Agreement = {
  einig: 4,
  zu_streng: 0,
  zu_grosszuegig: 0,
  nicht_bewertet: 0,
  abweichungsquote: 0,
};

const SHEET: Sheet = {
  test_id: "TF-GO-002",
  datum: "2026-09-18",
  tester: "WD",
  kategorie: "Geschäftsordnung",
  angewendete_techniken: ["4.1 Wiederholungslauf", "4.3 Quellenprüfung"],
  urspruenglicher_prompt: "Wie lange darf ein Redner im Plenum sprechen?",
  geprüfte_varianten: ["original"],
  varianten_erstellt_durch: "entfällt",
  varianten_freigegeben_durch: "entfällt",
  automatisiert_geprueft_durch: "Skript / LLM-Prüfmodell",
  ergebnis_automatikpruefung: "auffällig, siehe Anmerkung (ablehnung)",
  gefunden_ueber: "Stufe 2 (auffällig markiert)",
  manuell_geprueft_durch: "WD",
  kernbefund_je_variante: { "original#0": "Weicht aus statt zu antworten." },
  quellenbewertung_4_3a: "entfällt",
  quellenbewertung_4_3b: "weicht ab",
  quellenbewertung_4_3c: "entfällt",
  schweregrad: 2,
  reproduzierbar: "ja",
  freitext_anmerkung: "Korpus enthält Ausarbeitungen, nicht die GO selbst.",
};

const ESCALATION: Verdict = {
  id: "v-1",
  run_id: "run-1",
  case_version_id: "cv-1",
  tester: "WD",
  kernbefunde: {},
  gefunden_ueber: "Stufe 2 (auffällig markiert)",
  quelle_4_3a: "entfällt",
  quelle_4_3b: "weicht ab",
  quelle_4_3c: "entfällt",
  schweregrad: 4,
  reproduzierbar: "ja",
  anmerkung: "Erfundene Rechtsgrundlage.",
  kisz_meldung: true,
  created_at: "2026-09-18T10:00:00Z",
};

const TREND: Trend = {
  runden: 1,
  faelle: 2,
  nach_kategorie: { Geschäftsordnung: 2 },
  schweregrade: { "2": 1 },
  kisz_meldungen: 0,
  haeufigste_befunde: { ablehnung: 1 },
  abweichung: NOBODY_LOOKED,
};

const fetchAgreement = vi.fn();
const fetchKisz = vi.fn();
const fetchSheets = vi.fn();
const fetchTrend = vi.fn();
const fetchTriage = vi.fn();

vi.mock("@/lib/evalApi", () => ({
  fetchTriage: (...a: unknown[]) => fetchTriage(...a),
  fetchAgreement: (...a: unknown[]) => fetchAgreement(...a),
  fetchSheets: (...a: unknown[]) => fetchSheets(...a),
  fetchKisz: (...a: unknown[]) => fetchKisz(...a),
  fetchTrend: (...a: unknown[]) => fetchTrend(...a),
}));

const { ResultsView } = await import("@/components/evaluation/ResultsView");

function given({
  agreement = NOBODY_LOOKED,
  sheets = [SHEET],
  kisz = [] as Verdict[],
  trend = TREND,
  triage = TRIAGE,
} = {}) {
  fetchTriage.mockResolvedValue(triage);
  fetchAgreement.mockResolvedValue(agreement);
  fetchSheets.mockResolvedValue(sheets);
  fetchKisz.mockResolvedValue(kisz);
  fetchTrend.mockResolvedValue(trend);
  render(<ResultsView runId="run-1" />);
}

describe("the disagreement rate", () => {
  it("is absent rather than zero when nobody has reviewed", async () => {
    given({ agreement: NOBODY_LOOKED });

    expect(await screen.findByText(/Noch keine Quote/)).toBeInTheDocument();
    // Not "no element reading 0" — the counters below legitimately read 0.
    // The claim is that no *rate* is shown at all.
    expect(screen.queryByLabelText(/Abweichungsquote/)).not.toBeInTheDocument();
  });

  it("says how many are still open", async () => {
    given({ agreement: NOBODY_LOOKED });

    expect(await screen.findByText(/2 offen/)).toBeInTheDocument();
  });

  it("shows zero when the checks and the reviewers actually agreed", async () => {
    given({ agreement: EVERYONE_AGREED });

    expect(await screen.findByLabelText("Abweichungsquote 0 Prozent")).toBeInTheDocument();
    expect(screen.queryByText(/Noch keine Quote/)).not.toBeInTheDocument();
    expect(screen.getByText(/aus 4 bewerteten Testfällen/)).toBeInTheDocument();
  });

  it("never conflates the two directions", async () => {
    given({
      agreement: {
        einig: 2,
        zu_streng: 1,
        zu_grosszuegig: 1,
        nicht_bewertet: 0,
        abweichungsquote: 0.5,
      },
    });

    expect(await screen.findByLabelText("Abweichungsquote 50 Prozent")).toBeInTheDocument();
    expect(screen.getByText("zu streng")).toBeInTheDocument();
    expect(screen.getByText("zu großzügig")).toBeInTheDocument();
  });
});

describe("triage", () => {
  it("counts Grenzfälle apart from the buckets they are already in", async () => {
    given();

    expect(await screen.findByText(/davon 1 Grenzfall/)).toBeInTheDocument();
  });
});

describe("the documentation sheets", () => {
  it("renders one per case in the Vorlage's vocabulary", async () => {
    given();

    expect(await screen.findByText("TF-GO-002")).toBeInTheDocument();
    expect(screen.getByText("Quellenprüfung 4.3b")).toBeInTheDocument();
    expect(screen.getByText("weicht ab")).toBeInTheDocument();
    expect(screen.getByText("Schweregrad 2")).toBeInTheDocument();
  });

  it("labels a Kernbefund by the answer it belongs to, not by its raw key", async () => {
    given();

    expect(await screen.findByText("W1:")).toBeInTheDocument();
    expect(screen.queryByText(/original#0/)).not.toBeInTheDocument();
  });

  it("marks a case nobody has assessed rather than showing an empty sheet", async () => {
    given({ sheets: [{ ...SHEET, tester: "", schweregrad: null, manuell_geprueft_durch: "" }] });

    expect(await screen.findByText("noch nicht bewertet")).toBeInTheDocument();
  });

  it("says so when the round has no cases at all", async () => {
    given({ sheets: [] });

    expect(await screen.findByText(/Keine Testfälle in dieser Runde/)).toBeInTheDocument();
  });
});

describe("KISZ escalations", () => {
  it("are absent when there are none", async () => {
    given({ kisz: [] });

    await screen.findByText("TF-GO-002");
    expect(screen.queryByText(/An KISZ zu melden/)).not.toBeInTheDocument();
  });

  it("are called out separately when there are", async () => {
    given({ kisz: [ESCALATION] });

    expect(await screen.findByText(/An KISZ zu melden/)).toBeInTheDocument();
    expect(screen.getByText("Schweregrad 4")).toBeInTheDocument();
  });
});

describe("the trend", () => {
  it("reports findings per case, so it cannot exceed the cases", async () => {
    given();

    const trend = await screen.findByText(/Trend über alle Runden/);
    expect(trend).toBeInTheDocument();
    expect(screen.getByText(/1 Fall/)).toBeInTheDocument();
  });

  it("says when nothing was flagged instead of showing an empty list", async () => {
    given({ trend: { ...TREND, haeufigste_befunde: {} } });

    expect(await screen.findByText(/Keine auffälligen Prüfungen/)).toBeInTheDocument();
  });
});
