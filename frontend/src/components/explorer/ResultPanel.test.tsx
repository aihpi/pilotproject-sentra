import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ResultPanel } from "./ResultPanel";
import type { DocumentResult, ExternalSourceResult, GeneratedAnswerResult } from "@/types";

const doc: DocumentResult = {
  aktenzeichen: "WD 3 - 3000 - 029/23",
  title: "Zur Immunität von Abgeordneten",
  fachbereich: "Verfassung und Verwaltung",
  document_type: "Ausarbeitung",
  completion_date: "2023-05-01",
  relevance_score: 0.91,
  source_file: "WD 3-029-23.pdf",
};

const answer: GeneratedAnswerResult = {
  text: "Die Regelungen ergeben sich aus Artikel 46 GG **[1]**.",
  sources: [],
  system_prompt: "Du bist ein Assistent…",
};

const source: ExternalSourceResult = {
  url: "https://example.org/studie",
  label: "Beispielstudie",
  context: "…wie in der Beispielstudie gezeigt…",
  cited_in: [{ aktenzeichen: "WD 3 - 3000 - 029/23", title: "Zur Immunität von Abgeordneten" }],
};

describe("ResultPanel", () => {
  it("shows a spinner while the search runs", () => {
    render(<ResultPanel isLoading error={null} result={null} />);
    expect(screen.getByText("Suche läuft…")).toBeInTheDocument();
  });

  it("shows the error text when there is one", () => {
    render(
      <ResultPanel
        isLoading={false}
        error="Die Suchdatenbank ist nicht erreichbar."
        result={null}
      />,
    );
    expect(screen.getByText("Die Suchdatenbank ist nicht erreichbar.")).toBeInTheDocument();
  });

  it("renders nothing before the first search", () => {
    const { container } = render(<ResultPanel isLoading={false} error={null} result={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders documents", () => {
    render(
      <ResultPanel
        isLoading={false}
        error={null}
        result={{ type: "documents", documents: [doc] }}
      />,
    );
    expect(screen.getByText("Zur Immunität von Abgeordneten")).toBeInTheDocument();
  });

  it("renders a generated answer", () => {
    render(
      <ResultPanel
        isLoading={false}
        error={null}
        result={{ type: "answer", result: answer, query: "Frage?" }}
      />,
    );
    expect(screen.getByText(/Artikel 46 GG/)).toBeInTheDocument();
  });

  it("renders external sources", () => {
    render(
      <ResultPanel
        isLoading={false}
        error={null}
        result={{ type: "sources", sources: [source] }}
      />,
    );
    expect(screen.getByText("Beispielstudie")).toBeInTheDocument();
  });

  describe("precedence", () => {
    // The two that carry real weight. A result left on screen under a new
    // search would read as the answer to the new query.
    it("loading hides a previous result", () => {
      render(
        <ResultPanel
          isLoading
          error={null}
          result={{ type: "documents", documents: [doc] }}
        />,
      );
      expect(screen.getByText("Suche läuft…")).toBeInTheDocument();
      expect(screen.queryByText("Zur Immunität von Abgeordneten")).not.toBeInTheDocument();
    });

    it("an error hides a previous result", () => {
      render(
        <ResultPanel
          isLoading={false}
          error="Kaputt."
          result={{ type: "documents", documents: [doc] }}
        />,
      );
      expect(screen.getByText("Kaputt.")).toBeInTheDocument();
      expect(screen.queryByText("Zur Immunität von Abgeordneten")).not.toBeInTheDocument();
    });
  });
});
