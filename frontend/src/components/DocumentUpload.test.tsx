import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UploadResponse } from "@/types";

/** Adding documents from the browser.
 *
 *  The property worth protecting here is that **a partial success is
 *  reported, not swallowed**. Dragging in a folder with one unreadable name
 *  is the ordinary case, and a component that showed only "upload failed"
 *  would send somebody hunting for a problem with the nine files that were
 *  fine.
 *
 *  What is rejected, and why, is the backend's decision — `services/uploads.py`
 *  and its tests. This only has to relay it. */

const uploadDocuments = vi.fn();

vi.mock("@/lib/api", () => ({
  uploadDocuments: (files: File[]) => uploadDocuments(files),
}));

const { DocumentUpload } = await import("@/components/DocumentUpload");

function pdf(name: string): File {
  return new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], name, {
    type: "application/pdf",
  });
}

function answer(over: Partial<UploadResponse> = {}): UploadResponse {
  return { accepted: 0, rejected: 0, files: [], ...over };
}

beforeEach(() => {
  uploadDocuments.mockReset();
});

describe("uploading", () => {
  it("sends the chosen files", async () => {
    uploadDocuments.mockResolvedValue(
      answer({ accepted: 1, files: [{ name: "a.pdf", accepted: true, size_bytes: 4, reason: null }] }),
    );
    render(<DocumentUpload onUploaded={vi.fn()} />);

    await userEvent.upload(
      screen.getByLabelText("Dateien auswählen"),
      pdf("a.pdf"),
    );

    expect(uploadDocuments).toHaveBeenCalledWith([expect.objectContaining({ name: "a.pdf" })]);
  });

  it("says the files are not searchable until ingestion runs", async () => {
    /** Uploading is not indexing, and the gap between the two is long enough
     *  that silence about it reads as a failed upload. */
    uploadDocuments.mockResolvedValue(
      answer({ accepted: 2, files: [] }),
    );
    render(<DocumentUpload onUploaded={vi.fn()} />);

    await userEvent.upload(
      screen.getByLabelText("Dateien auswählen"),
      [pdf("a.pdf"), pdf("b.pdf")],
    );

    expect(await screen.findByText(/2 Dateien hochgeladen/)).toBeInTheDocument();
    expect(screen.getByText(/Dokumente einlesen/)).toBeInTheDocument();
  });

  it("reports the rejected files individually, keeping the accepted ones", async () => {
    uploadDocuments.mockResolvedValue(
      answer({
        accepted: 1,
        rejected: 2,
        files: [
          { name: "good.pdf", accepted: true, size_bytes: 4, reason: null },
          {
            name: "../escape.pdf",
            accepted: false,
            size_bytes: 0,
            reason: "Der Dateiname darf keinen Pfad enthalten.",
          },
          {
            name: "notes.txt",
            accepted: false,
            size_bytes: 0,
            reason: "Nur .docx, .pdf werden angenommen.",
          },
        ],
      }),
    );
    render(<DocumentUpload onUploaded={vi.fn()} />);

    await userEvent.upload(screen.getByLabelText("Dateien auswählen"), pdf("good.pdf"));

    expect(await screen.findByText(/1 Datei hochgeladen/)).toBeInTheDocument();
    expect(screen.getByText(/keinen Pfad enthalten/)).toBeInTheDocument();
    expect(screen.getByText(/Nur .docx, .pdf/)).toBeInTheDocument();
  });

  it("refreshes the caller even when only some files were taken", async () => {
    const onUploaded = vi.fn();
    uploadDocuments.mockResolvedValue(
      answer({
        accepted: 1,
        rejected: 1,
        files: [
          { name: "good.pdf", accepted: true, size_bytes: 4, reason: null },
          { name: "bad.txt", accepted: false, size_bytes: 0, reason: "Nur .pdf" },
        ],
      }),
    );
    render(<DocumentUpload onUploaded={onUploaded} />);

    await userEvent.upload(screen.getByLabelText("Dateien auswählen"), pdf("good.pdf"));

    expect(onUploaded).toHaveBeenCalled();
  });

  it("shows the server's reason when the request itself fails", async () => {
    /** A 401 here means the session expired mid-session, which is actionable
     *  and worth saying plainly rather than as "upload failed". */
    uploadDocuments.mockRejectedValue(
      new Error("Zum Hochladen ist eine Anmeldung als Administrator nötig."),
    );
    render(<DocumentUpload onUploaded={vi.fn()} />);

    await userEvent.upload(screen.getByLabelText("Dateien auswählen"), pdf("a.pdf"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Anmeldung als Administrator/,
    );
  });

  it("does not call the API when nothing was chosen", async () => {
    render(<DocumentUpload onUploaded={vi.fn()} />);

    await userEvent.upload(screen.getByLabelText("Dateien auswählen"), []);

    expect(uploadDocuments).not.toHaveBeenCalled();
  });
});
