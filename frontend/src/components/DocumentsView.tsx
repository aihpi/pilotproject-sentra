import { useEffect, useState } from "react";
import type { DocumentInfo } from "@/types";
import { fetchDocuments } from "@/lib/api";
import { DocumentsTable } from "@/components/DocumentsTable";

/** What is in the corpus, readable by anyone.
 *
 *  No controls. Adding, indexing and withdrawing change what WD staff are
 *  told, so they live in Administration → Dokumente. */
export function DocumentsView() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDocuments()
      .then(setDocuments)
      .catch((err: Error) => setError(err.message || "Dokumente konnten nicht geladen werden"))
      .finally(() => setIsLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <h2 className="text-2xl font-bold text-primary">Indizierte Dokumente</h2>
        <p className="text-muted-foreground">
          {documents.length} Dokumente in der Datenbank
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      <DocumentsTable documents={documents} isLoading={isLoading} />
    </div>
  );
}
