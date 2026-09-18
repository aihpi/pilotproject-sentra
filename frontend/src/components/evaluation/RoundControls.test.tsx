import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EvalRun } from "@/types";

/** Getting a round going without a terminal.
 *
 *  Two properties are worth holding here. A round takes about an hour, so a
 *  running one has to look like it is running rather than like a hung page —
 *  otherwise somebody starts a second, or restarts the stack mid-round. And an
 *  upload that is refused has to say *why*, in the reader's own words: it
 *  names the row the way Excel numbers it, and "(HTTP 422)" would throw that
 *  away and leave somebody hunting through 200 rows.
 */

const importSheet = vi.fn();
const startRun = vi.fn();

vi.mock("@/lib/evalApi", () => ({
  importSheet: (...a: unknown[]) => importSheet(...a),
  startRun: (...a: unknown[]) => startRun(...a),
}));

const { RoundControls } = await import("@/components/evaluation/RoundControls");

const RUNNING: EvalRun = {
  id: "run-1",
  label: "Runde September",
  status: "laufend",
  sentra_base_url: "http://sentra",
  repeats: 3,
  started_at: "2026-09-18T10:00:00Z",
  completed_at: null,
  fehler: "",
  total: 180,
  done: 45,
  failed: 0,
  audit_ok: true,
};

function renderControls(running: EvalRun | null = null) {
  const onStarted = vi.fn();
  const onImported = vi.fn();
  render(<RoundControls running={running} onStarted={onStarted} onImported={onImported} />);
  return { onStarted, onImported };
}

function sheet(name = "SENTRA-Testfaelle-Erfassung.xlsx") {
  return new File([new Uint8Array([80, 75, 3, 4])], name, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

beforeEach(() => {
  importSheet.mockReset();
  startRun.mockReset();
});

describe("starting a round", () => {
  it("passes the label and the repeat count", async () => {
    startRun.mockResolvedValue({ ...RUNNING, done: 0 });
    const { onStarted } = renderControls();

    await userEvent.type(screen.getByLabelText(/Bezeichnung/), "Runde September");
    await userEvent.click(screen.getByRole("button", { name: /Testrunde starten/ }));

    await waitFor(() => expect(startRun).toHaveBeenCalledWith("Runde September", 3));
    expect(onStarted).toHaveBeenCalled();
  });

  it("is refused while one is already running, and says so", async () => {
    renderControls(RUNNING);

    const button = screen.getByRole("button", { name: /Eine Runde läuft bereits/ });

    expect(button).toBeDisabled();
    expect(startRun).not.toHaveBeenCalled();
  });

  it("shows the server's reason when it will not start", async () => {
    startRun.mockRejectedValue(new Error("Es läuft bereits eine Testrunde."));
    renderControls();

    await userEvent.click(screen.getByRole("button", { name: /Testrunde starten/ }));

    expect(await screen.findByText(/Es läuft bereits eine Testrunde/)).toBeInTheDocument();
  });
});

describe("a round in flight", () => {
  it("shows how far along it is rather than a spinner", async () => {
    renderControls(RUNNING);

    expect(screen.getByText(/45 von 180 Aufrufen/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  });

  it("calls out failed calls, which a percentage hides", async () => {
    renderControls({ ...RUNNING, failed: 3 });

    expect(screen.getByText(/3 fehlgeschlagen/)).toBeInTheDocument();
  });
});

describe("uploading a collection sheet", () => {
  it("reports the Test-IDs rather than a count", async () => {
    importSheet.mockResolvedValue({
      angelegt: ["TF-GO-001", "TF-GO-002"],
      aktualisiert: [],
      unveraendert: [],
      freigegeben: [],
    });
    const { onImported } = renderControls();

    await userEvent.upload(screen.getByLabelText(/Erfassungsvorlage hochladen/), sheet());

    expect(await screen.findByText(/TF-GO-001, TF-GO-002/)).toBeInTheDocument();
    expect(onImported).toHaveBeenCalled();
  });

  it("passes the reader's message through, row number and all", async () => {
    importSheet.mockRejectedValue(
      new Error("Die hochgeladene Datei, Zeile 4: Erwartete Antwort fehlt."),
    );
    renderControls();

    await userEvent.upload(screen.getByLabelText(/Erfassungsvorlage hochladen/), sheet());

    expect(await screen.findByText(/Zeile 4/)).toBeInTheDocument();
  });

  it("says so when the sheet held nothing", async () => {
    importSheet.mockResolvedValue({
      angelegt: [],
      aktualisiert: [],
      unveraendert: [],
      freigegeben: [],
    });
    renderControls();

    await userEvent.upload(screen.getByLabelText(/Erfassungsvorlage hochladen/), sheet());

    expect(await screen.findByText(/keine Testfälle/)).toBeInTheDocument();
  });

  it("states that nothing uploaded is approved", () => {
    renderControls();

    expect(screen.getByText(/immer Entwürfe/)).toBeInTheDocument();
  });
});
