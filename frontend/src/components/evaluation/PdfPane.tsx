import type { SourceRef } from "@/types";
import { pdfUrl } from "@/lib/api";
import { X } from "lucide-react";

interface PdfPaneProps {
  source: SourceRef;
  onClose: () => void;
}

/** The cited document, in the same column as the answer.
 *
 *  4.3c — Kontextprüfung — is a person deciding whether the source actually
 *  supports the claim, which means reading the passage against the claim. A
 *  modal covers the answer, and a new tab puts them on separate screens; both
 *  turn one judgement into two acts of memory. So this sits under the answer,
 *  which stays visible above it.
 *
 *  There was a modal version, deleted as dead code during the restructure. It
 *  also carried its own copy of the API base path, which is why the URL here
 *  comes from the shared helper — the same reason #43 collapsed the fetch
 *  boilerplate. */
export function PdfPane({ source, onClose }: PdfPaneProps) {
  return (
    <section className="space-y-2 rounded-lg border bg-card p-3">
      <header className="flex items-center gap-2">
        <h4 className="min-w-0 flex-1 truncate text-xs font-semibold">
          {source.title}
          <span className="ml-2 font-mono font-normal text-muted-foreground">
            {source.aktenzeichen}
          </span>
          {/* Said in the header as well as jumped to. A viewer that lands on
              page 4 without saying so leaves the reviewer unsure whether it
              obeyed — and 4.3a is them checking a claim against a passage, so
              which passage was meant has to be on screen, not only implied by
              the scroll position. */}
          {!!source.page && (
            <span className="ml-2 font-normal text-muted-foreground">
              S. {source.page}
              {!!source.paragraph && `, Abs. ${source.paragraph}`}
            </span>
          )}
        </h4>
        <button
          type="button"
          onClick={onClose}
          aria-label="Dokument schließen"
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      {source.source_file ? (
        <iframe
          // Keyed on the page so that picking another source, or the same one
          // at a different passage, reloads the frame. A src change alone does
          // not move a PDF viewer that has already opened the file: the
          // fragment is resolved once, and the reviewer would be left on
          // whatever page they had scrolled to.
          key={`${source.source_file}#${source.page ?? 0}`}
          src={pdfUrl(source.source_file, source.page)}
          title={`PDF: ${source.title}`}
          className="h-[60vh] w-full rounded border"
        />
      ) : (
        // A real state rather than an error: the answer cited a document whose
        // filename the response did not carry. Saying so beats an empty frame
        // that looks like a broken viewer.
        <p className="rounded border border-dashed p-4 text-xs text-muted-foreground">
          Für diese Quelle ist keine Datei hinterlegt. Die Kontextprüfung (4.3c)
          muss hier anders belegt werden.
        </p>
      )}
    </section>
  );
}
