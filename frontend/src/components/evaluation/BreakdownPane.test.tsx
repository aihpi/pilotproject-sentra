import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BreakdownRow } from "@/types";

/** Results broken down by label (#289). */

const fetchBreakdown = vi.fn();

vi.mock("@/lib/evalApi", () => ({
  fetchBreakdown: (...a: unknown[]) => fetchBreakdown(...a),
}));

const { BreakdownPane } = await import("@/components/evaluation/BreakdownPane");

const ROWS: BreakdownRow[] = [
  {
    werte: { testart: "Präzision" },
    faelle: 4,
    auffaellig: 3,
    befunde: { quellenauswahl: 2, marker_ausrichtung: 1 },
    abweichung: { einig: 1, zu_streng: 1, zu_grosszuegig: 0, nicht_bewertet: 2, abweichungsquote: 0.5 },
  },
  {
    werte: { testart: "Regelfall" },
    faelle: 2,
    auffaellig: 0,
    befunde: {},
    abweichung: { einig: 0, zu_streng: 0, zu_grosszuegig: 0, nicht_bewertet: 2, abweichungsquote: null },
  },
];

beforeEach(() => {
  fetchBreakdown.mockReset().mockResolvedValue(ROWS);
});

describe("the breakdown", () => {
  it("starts with this round by Testart", async () => {
    render(<BreakdownPane runId="run-1" />);

    await screen.findByText("Präzision");
    expect(fetchBreakdown).toHaveBeenCalledWith(["testart"], "run-1");
  });

  it("shows cases, findings and the disagreement per value", async () => {
    render(<BreakdownPane runId="run-1" />);

    expect(await screen.findByText("3 (75 %)")).toBeInTheDocument();
    expect(screen.getByText("50 %")).toBeInTheDocument();
    expect(screen.getByText("quellenauswahl 2, marker_ausrichtung 1")).toBeInTheDocument();
  });

  it("says nicht bewertet rather than a flattering zero", async () => {
    render(<BreakdownPane runId="run-1" />);

    expect(await screen.findByText("nicht bewertet")).toBeInTheDocument();
  });

  it("combines a second label", async () => {
    render(<BreakdownPane runId="run-1" />);
    await screen.findByText("Präzision");

    await userEvent.selectOptions(screen.getByLabelText("Und nach"), "kategorie");

    await waitFor(() =>
      expect(fetchBreakdown).toHaveBeenLastCalledWith(["testart", "kategorie"], "run-1"),
    );
  });

  it("covers every round when asked", async () => {
    render(<BreakdownPane runId="run-1" />);
    await screen.findByText("Präzision");

    await userEvent.click(screen.getByRole("checkbox", { name: "alle Runden" }));

    await waitFor(() => expect(fetchBreakdown).toHaveBeenLastCalledWith(["testart"], undefined));
  });
});
