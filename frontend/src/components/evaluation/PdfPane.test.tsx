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
    render(
      <PdfPane
        source={{ ...SOURCE, source_file: undefined }}
        onClose={() => {}}
      />,
    );

    expect(screen.queryByTitle(/^PDF:/)).not.toBeInTheDocument();
    expect(screen.getByText(/keine Datei hinterlegt/)).toBeInTheDocument();
  });
});

describe("opening at the cited passage", () => {
  /** The point of #134. A section can run for four pages, and a reviewer told
   *  "look in section 2.1" cannot do 4.3a by hand; told "page 4, paragraph 3"
   *  they can. */

  const CITED = { ...SOURCE, page: 4, paragraph: 3 };

  it("jumps to the page", () => {
    render(<PdfPane source={CITED} onClose={() => {}} />);

    expect(screen.getByTitle(/^PDF:/)).toHaveAttribute(
      "src",
      expect.stringContaining("#page=4"),
    );
  });

  it("and says so, rather than only scrolling there", () => {
    /** A viewer that lands on page 4 silently leaves the reviewer unsure
     *  whether it obeyed, and which passage was meant is the thing being
     *  checked. */
    render(<PdfPane source={CITED} onClose={() => {}} />);

    expect(screen.getByText(/S\. 4, Abs\. 3/)).toBeInTheDocument();
  });

  it("says nothing where no page was recorded", () => {
    /** Every document indexed before #134 is in this state, which is all of
     *  them until the corpus is re-ingested. "Seite 0" is not checkable, and
     *  a viewer told to open at page 0 lands wherever it likes. */
    render(<PdfPane source={SOURCE} onClose={() => {}} />);

    expect(screen.queryByText(/S\. 0/)).not.toBeInTheDocument();
    expect(screen.getByTitle(/^PDF:/).getAttribute("src")).not.toContain(
      "#page=",
    );
  });

  it("reloads when the passage changes", () => {
    /** A src change alone does not move a viewer that has already opened the
     *  file — the fragment is resolved once — so the reviewer would be left on
     *  whatever page they had scrolled to. The frame is keyed on the passage
     *  so React replaces it. */
    const { rerender, container } = render(
      <PdfPane source={CITED} onClose={() => {}} />,
    );
    const first = container.querySelector("iframe");

    rerender(<PdfPane source={{ ...CITED, page: 9 }} onClose={() => {}} />);

    expect(container.querySelector("iframe")).not.toBe(first);
  });
});
