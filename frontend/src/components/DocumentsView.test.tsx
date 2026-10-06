import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

/** The Dokumente tab is the list anyone may read. Changing the corpus,
 *  including indexing it, lives in Administration. */

vi.mock("@/lib/api", () => ({
  fetchDocuments: () => Promise.resolve([]),
}));

const { DocumentsView } = await import("@/components/DocumentsView");

describe("the Dokumente tab", () => {
  it("lists without offering to change anything", async () => {
    render(<DocumentsView />);

    expect(await screen.findByText(/0 Dokumente in der Datenbank/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /einlesen/ })).not.toBeInTheDocument();
  });
});
