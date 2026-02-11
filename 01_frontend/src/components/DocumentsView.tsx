import { useEffect, useState } from "react";
import type { DocumentInfo, IngestResponse } from "@/types";
import { fetchDocuments, ingestDocuments } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { DocumentsTable } from "@/components/DocumentsTable";
import { Loader2 } from "lucide-react";

export function DocumentsView() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isIngesting, setIsIngesting] = useState(false);
  const [ingestResult, setIngestResult] = useState<IngestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadDocuments = async () => {
    setIsLoading(true);
    try {
      const docs = await fetchDocuments();
      setDocuments(docs);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Dokumente konnten nicht geladen werden"
      );
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadDocuments();
  }, []);

  const handleIngest = async () => {
    setIsIngesting(true);
    setIngestResult(null);
    setError(null);

    try {
      const result = await ingestDocuments();
      setIngestResult(result);
      await loadDocuments();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Ingestion fehlgeschlagen"
      );
    } finally {
      setIsIngesting(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-primary">
            Indizierte Dokumente
          </h2>
          <p className="text-muted-foreground">
            {documents.length} Dokumente in der Datenbank
          </p>
        </div>
        <Button onClick={handleIngest} disabled={isIngesting}>
          {isIngesting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Verarbeite...
            </>
          ) : (
            "Dokumente einlesen"
          )}
        </Button>
      </div>

      {ingestResult && (
        <div className="rounded-md border border-green-200 bg-green-50 p-4 text-sm text-green-800">
          {ingestResult.documents_processed} Dokumente verarbeitet,{" "}
          {ingestResult.chunks_created} Chunks erstellt.
          {ingestResult.errors.length > 0 && (
            <p className="mt-1 text-destructive">
              {ingestResult.errors.length} Fehler: {ingestResult.errors.join(", ")}
            </p>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      <DocumentsTable documents={documents} isLoading={isLoading} />
    </div>
  );
}
