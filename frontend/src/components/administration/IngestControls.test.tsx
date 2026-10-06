import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { IngestionStatus } from "@/types";

/** Running ingestion from Administration.
 *
 *  Worth holding: the pane's list is refreshed when a run finishes, since that
 *  is the moment an uploaded file first appears in it, and a run already going
 *  is picked up rather than offering a second one. */

const startIngestion = vi.fn();
const getIngestionStatus = vi.fn();

vi.mock("@/lib/api", () => ({
  startIngestion: () => startIngestion(),
  getIngestionStatus: () => getIngestionStatus(),
}));

const { IngestControls } = await import(
  "@/components/administration/IngestControls"
);

function status(overrides: Partial<IngestionStatus>): IngestionStatus {
  return {
    status: "idle",
    total_files: 0,
    processed: 0,
    skipped: 0,
    chunks_created: 0,
    errors: [],
    current_file: "",
    started_at: null,
    completed_at: null,
    stale_documents: [],
    ...overrides,
  };
}

beforeEach(() => {
  startIngestion.mockReset().mockResolvedValue({ status: "started" });
  getIngestionStatus.mockReset().mockResolvedValue(status({}));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ingestion", () => {
  it("refreshes the list once a run completes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onFinished = vi.fn();
    render(<IngestControls onFinished={onFinished} />);

    getIngestionStatus.mockResolvedValue(
      status({ status: "running", total_files: 2, current_file: "a.pdf" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Dokumente einlesen" }));
    expect(await screen.findByText("Verarbeite: a.pdf")).toBeInTheDocument();

    getIngestionStatus.mockResolvedValue(
      status({ status: "completed", total_files: 2, processed: 2, chunks_created: 40 }),
    );
    await act(() => vi.advanceTimersByTimeAsync(3000));

    expect(onFinished).toHaveBeenCalledOnce();
    expect(screen.getByText(/2 Dokumente verarbeitet, 40 Chunks erstellt/)).toBeInTheDocument();
  });

  it("picks up a run already in progress instead of offering another", async () => {
    getIngestionStatus.mockResolvedValue(
      status({ status: "running", total_files: 5, processed: 1 }),
    );
    render(<IngestControls onFinished={vi.fn()} />);

    expect(await screen.findByRole("button", { name: /Verarbeite/ })).toBeDisabled();
    expect(screen.getByRole("progressbar", { name: "Fortschritt der Ingestion" })).toBeInTheDocument();
  });

  it("shows the server's refusal", async () => {
    startIngestion.mockRejectedValue(new Error("Ingestion läuft bereits"));
    render(<IngestControls onFinished={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "Dokumente einlesen" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Ingestion läuft bereits");
  });
});
