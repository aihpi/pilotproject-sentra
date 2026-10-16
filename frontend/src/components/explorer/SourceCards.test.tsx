import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { SourceRef } from "@/types";
import { SourceCards } from "@/components/explorer/SourceCards";

/** The numbered cards under an answer.
 *
 *  What is worth testing here is the citation, not the layout: a card says
 *  where in the paper the passage is and links there, and says nothing at all
 *  where nobody recorded a page — which is every document in the index until
 *  the corpus is re-ingested.
 */

const PLAIN: SourceRef = {
  aktenzeichen: "WD 3 - 3000 - 029/23",
  title: "Redezeit im Plenum",
  fachbereich: "Verfassung",
  completion_date: "2023-05-08",
  source_file: "WD 3-029-23.pdf",
};

const CITED: SourceRef = { ...PLAIN, page: 4, paragraph: 3 };

describe("where a source was cited from", () => {
  it("is shown on the card", () => {
    render(<SourceCards sources={[CITED]} />);

    expect(screen.getByText(/S\. 4, Abs\. 3/)).toBeInTheDocument();
  });

  it("and the link opens the document there", () => {
    render(<SourceCards sources={[CITED]} />);

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      expect.stringContaining("#page=4"),
    );
  });

  it("the page alone is enough, if that is all there is", () => {
    render(<SourceCards sources={[{ ...PLAIN, page: 7 }]} />);

    expect(screen.getByText(/S\. 7/)).toBeInTheDocument();
  });

  it("nothing is shown where nobody recorded a page", () => {
    /** Every document indexed before #134. "Seite 0" is not checkable, and the
     *  whole point of the citation is that it can be checked. */
    render(<SourceCards sources={[PLAIN]} />);

    expect(screen.queryByText(/S\. 0/)).not.toBeInTheDocument();
    expect(screen.getByRole("link").getAttribute("href")).not.toContain(
      "#page=",
    );
  });
});

describe("the numbering", () => {
  it("is the number the answer cites it by, not the position (#269)", () => {
    // [1] and [3] cited, source 2 not returned.
    const first: SourceRef = { ...PLAIN, nummer: 1 };
    const third: SourceRef = { ...PLAIN, aktenzeichen: "WD 1 - 3000 - 001/24", nummer: 3 };

    render(<SourceCards sources={[first, third]} />);

    const numbers = screen.getAllByText(/^[123]$/).map((el) => el.textContent);
    expect(numbers).toEqual(["1", "3"]);
  });

  it("shows nothing at all for an answer that cites nothing", () => {
    const { container } = render(<SourceCards sources={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("falls back to the position for a response stored before nummer existed", () => {
    const second: SourceRef = {
      ...PLAIN,
      aktenzeichen: "WD 1 - 3000 - 001/24",
    };

    render(<SourceCards sources={[PLAIN, second]} />);

    const numbers = screen.getAllByText(/^[12]$/).map((el) => el.textContent);
    expect(numbers).toEqual(["1", "2"]);
  });
});

describe("documents without an Aktenzeichen", () => {
  it("are told apart by file, so selecting one highlights only that one (#300)", () => {
    const first: SourceRef = { ...PLAIN, aktenzeichen: "", source_file: "AB 04-24.pdf", nummer: 1 };
    const second: SourceRef = { ...PLAIN, aktenzeichen: "", source_file: "AB 10-23.pdf", nummer: 2 };

    render(<SourceCards sources={[first, second]} onSelect={() => {}} selected="AB 10-23.pdf" />);

    const cards = screen.getAllByRole("button");
    expect(cards).toHaveLength(2);
    expect(cards[0].className).not.toContain("ring-1");
    expect(cards[1].className).toContain("ring-1");
  });
});
