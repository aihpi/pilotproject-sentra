import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PdfPane } from "@/components/evaluation/PdfPane";

/** The cited document, beside the claim.
 *
 *  4.3c is a person deciding whether a source supports an assertion, which
 *  means reading both at once. The tests worth having here are about the URL
 *  coming from one place and about the case where there is no file — an empty
 *  frame reads as a broken viewer, and a reviewer would go looking for the bug
 *  rather than recording that the check could not be made.
 */

const SOURCE = {
  aktenzeichen: "WD 3 - 3000 - 029/23",
  title: "Redezeit im Plenum",
  source_file: "WD 3-029-23.pdf",
};

describe("the PDF pane", () => {
  it("names the document it is showing", () => {
    render(<PdfPane source={SOURCE} onClose={() => {}} />);

    expect(screen.getByText("Redezeit im Plenum")).toBeInTheDocument();
    expect(screen.getByText("WD 3 - 3000 - 029/23")).toBeInTheDocument();
  });

  it("embeds the document rather than linking away from it", () => {
    render(<PdfPane source={SOURCE} onClose={() => {}} />);

    const frame = screen.getByTitle("PDF: Redezeit im Plenum");
    expect(frame.tagName).toBe("IFRAME");
  });

  it("builds the URL through the shared helper", () => {
    render(<PdfPane source={SOURCE} onClose={() => {}} />);

    expect(screen.getByTitle("PDF: Redezeit im Plenum")).toHaveAttribute(
      "src",
      "/api/documents/WD%203-029-23.pdf",
    );
  });

  it("closes", async () => {
    const onClose = vi.fn();
    render(<PdfPane source={SOURCE} onClose={onClose} />);

    await userEvent.click(screen.getByLabelText("Dokument schließen"));

    expect(onClose).toHaveBeenCalled();
  });

  it("says so when the source carries no file", () => {
    render(<PdfPane source={{ ...SOURCE, source_file: undefined }} onClose={() => {}} />);

    expect(screen.queryByTitle(/^PDF:/)).not.toBeInTheDocument();
    expect(screen.getByText(/keine Datei hinterlegt/)).toBeInTheDocument();
  });
});
