import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DocumentInfo, VolumeFile } from "@/types";
import { VolumeComparison } from "@/components/administration/VolumeComparison";

/** Each group has its own cause and remedy, so the property worth holding is
 *  that a file lands in the right one. Above all, a withdrawn PDF must not be
 *  offered as waiting for ingestion: ingestion skips it, and suggesting
 *  otherwise invites somebody to try to bring it back that way. */

function file(name: string, over: Partial<VolumeFile> = {}): VolumeFile {
  return {
    name,
    size_bytes: 1,
    modified_at: "2026-10-01T00:00:00Z",
    indexable: name.endsWith(".pdf"),
    withdrawn: false,
    ...over,
  };
}

function doc(source_file: string): DocumentInfo {
  return {
    aktenzeichen: "WD 3 - 3000 - 029/23",
    title: source_file,
    fachbereich_number: "WD 3",
    fachbereich: "Verfassung",
    document_type: "Sachstand",
    completion_date: "2023-01-01",
    language: "de",
    source_file,
  };
}

async function group(title: string) {
  const summary = screen.getByText(title).closest("summary")!;
  await userEvent.click(summary);
  return summary.parentElement!;
}

describe("the volume comparison", () => {
  it("says so when volume and index agree", () => {
    render(<VolumeComparison files={[file("a.pdf")]} documents={[doc("a.pdf")]} />);

    expect(screen.getByText("Volume und Index stimmen überein.")).toBeInTheDocument();
  });

  it("sorts each discrepancy into its own group", async () => {
    render(
      <VolumeComparison
        files={[
          file("indexed.pdf"),
          file("new.pdf"),
          file("gone.pdf", { withdrawn: true }),
          file("abstract.docx"),
        ]}
        documents={[doc("indexed.pdf"), doc("orphan.pdf")]}
      />,
    );

    expect(await group("Bereit zum Einlesen")).toHaveTextContent("new.pdf");
    expect(await group("Zurückgezogen")).toHaveTextContent("gone.pdf");
    expect(await group("Werden nicht eingelesen")).toHaveTextContent("abstract.docx");
    expect(await group("Im Index ohne Datei")).toHaveTextContent("orphan.pdf");
  });

  it("does not offer a withdrawn PDF for ingestion", () => {
    render(
      <VolumeComparison files={[file("gone.pdf", { withdrawn: true })]} documents={[]} />,
    );

    expect(screen.queryByText("Bereit zum Einlesen")).not.toBeInTheDocument();
  });

  it("warns when the registry could not say what is withdrawn", () => {
    render(
      <VolumeComparison files={[file("a.pdf", { withdrawn: null })]} documents={[]} />,
    );

    expect(screen.getByText(/Registry ist nicht erreichbar/)).toBeInTheDocument();
  });
});
