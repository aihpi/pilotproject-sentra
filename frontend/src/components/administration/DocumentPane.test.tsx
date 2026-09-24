import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DocumentInfo } from "@/types";

/** Changing what the corpus contains.
 *
 *  The property worth protecting is that **withdrawing asks first**. It is
 *  reversible, but it takes a document out of every answer until somebody
 *  restores it, and the row sits next to a list where the neighbouring
 *  document is one click away.
 */

const fetchDocuments = vi.fn();
const withdrawDocument = vi.fn();

vi.mock("@/lib/api", () => ({
  fetchDocuments: () => fetchDocuments(),
  withdrawDocument: (name: string) => withdrawDocument(name),
  uploadDocuments: vi.fn(),
}));

vi.mock("@/components/DocumentUpload", () => ({
  DocumentUpload: () => <div>Upload-Bereich</div>,
}));

const { DocumentPane } = await import(
  "@/components/administration/DocumentPane"
);

function doc(name: string, title = "Ein Titel"): DocumentInfo {
  return {
    aktenzeichen: "WD 3 - 3000 - 029/23",
    title,
    fachbereich_number: "WD 3",
    fachbereich: "Verfassung",
    document_type: "Sachstand",
    completion_date: "2023-01-01",
    language: "de",
    source_file: name,
  };
}

beforeEach(() => {
  fetchDocuments.mockReset();
  withdrawDocument.mockReset();
  fetchDocuments.mockResolvedValue([doc("a.pdf", "Erstes"), doc("b.pdf", "Zweites")]);
  withdrawDocument.mockResolvedValue({ name: "a.pdf", registered: true });
});

describe("the document pane", () => {
  it("offers the upload alongside the list", async () => {
    render(<DocumentPane />);

    expect(await screen.findByText("Upload-Bereich")).toBeInTheDocument();
    expect(screen.getByText("Erstes")).toBeInTheDocument();
  });

  it("says what withdrawing does, because delete is ambiguous", async () => {
    render(<DocumentPane />);

    expect(
      await screen.findByText(/nicht mehr durchsuchbar/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Datei und der Registrierungseintrag bleiben/)).toBeInTheDocument();
  });

  it("asks before withdrawing", async () => {
    render(<DocumentPane />);
    await screen.findByText("Erstes");

    await userEvent.click(screen.getAllByRole("button", { name: "Zurückziehen" })[0]);

    expect(screen.getByText("Wirklich zurückziehen?")).toBeInTheDocument();
    expect(withdrawDocument).not.toHaveBeenCalled();
  });

  it("withdraws the document it was asked about, and reloads", async () => {
    render(<DocumentPane />);
    await screen.findByText("Zweites");

    await userEvent.click(screen.getAllByRole("button", { name: "Zurückziehen" })[1]);
    await userEvent.click(screen.getByRole("button", { name: "Ja, zurückziehen" }));

    expect(withdrawDocument).toHaveBeenCalledWith("b.pdf");
    await waitFor(() => expect(fetchDocuments).toHaveBeenCalledTimes(2));
  });

  it("can be cancelled", async () => {
    render(<DocumentPane />);
    await screen.findByText("Erstes");

    await userEvent.click(screen.getAllByRole("button", { name: "Zurückziehen" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Abbrechen" }));

    expect(screen.queryByText("Wirklich zurückziehen?")).not.toBeInTheDocument();
    expect(withdrawDocument).not.toHaveBeenCalled();
  });

  it("shows the server's reason when withdrawing fails", async () => {
    withdrawDocument.mockRejectedValue(
      new Error("Zum Zurückziehen wird die Rolle „admin“ benötigt."),
    );
    render(<DocumentPane />);
    await screen.findByText("Erstes");

    await userEvent.click(screen.getAllByRole("button", { name: "Zurückziehen" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Ja, zurückziehen" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Rolle/);
  });
});
