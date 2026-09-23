import { useEffect, useState, useRef, useCallback } from "react";
import type { DocumentInfo, IngestionStatus, VolumeFile } from "@/types";
import {
  fetchDocuments,
  fetchVolumeFiles,
  startIngestion,
  getIngestionStatus,
} from "@/lib/api";
import { DocumentUpload } from "@/components/DocumentUpload";
import { Button } from "@/components/ui/button";
import { DocumentsTable } from "@/components/DocumentsTable";
import { Loader2, CheckCircle2, AlertCircle } from "lucide-react";

const POLL_INTERVAL_MS = 3000;

export function DocumentsView({ canIngest }: { canIngest: boolean }) {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  // What is on the volume, which is not what is indexed. Only fetched where
  // the caller may read it — the endpoint is admin-only, and a 401 in the
  // console on every page load would be noise rather than information.
  const [volume, setVolume] = useState<VolumeFile[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Ingestion state
  const [ingestionStatus, setIngestionStatus] = useState<IngestionStatus | null>(null);
  const [toast, setToast] = useState<{
    type: "success" | "error";
    message: string;
    details?: string;
  } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadVolume = useCallback(async () => {
    if (!canIngest) return;
    try {
      setVolume(await fetchVolumeFiles());
    } catch {
      // Not worth surfacing. The document list is the primary content and it
      // has its own error path; this is a secondary count.
      setVolume(null);
    }
  }, [canIngest]);

  const loadDocuments = useCallback(async () => {
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
  }, []);

  useEffect(() => {
    loadDocuments();
    void loadVolume();
  }, [loadDocuments, loadVolume]);

  // Check if ingestion is already running on mount
  useEffect(() => {
    getIngestionStatus()
      .then((status) => {
        if (status.status === "running") {
          setIngestionStatus(status);
          startPolling();
        }
      })
      .catch(() => {});
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startPolling = () => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const status = await getIngestionStatus();
        setIngestionStatus(status);

        if (status.status === "completed") {
          stopPolling();
          setToast({
            type: "success",
            message: `${status.processed} Dokumente verarbeitet, ${status.chunks_created} Chunks erstellt.${
              status.skipped > 0 ? ` ${status.skipped} übersprungen.` : ""
            }`,
            details: [
              status.errors.length > 0
                ? `${status.errors.length} Fehler: ${status.errors.slice(0, 3).join(", ")}`
                : null,
              // Indexed but no longer on disk. The server has always computed
              // this and only logged it, so it was invisible here.
              status.stale_documents?.length
                ? `${status.stale_documents.length} verwaiste Dokumente im Index: ${status.stale_documents
                    .slice(0, 3)
                    .join(", ")}`
                : null,
            ]
              .filter(Boolean)
              .join(" · ") || undefined,
          });
          loadDocuments();
        } else if (status.status === "failed") {
          stopPolling();
          setToast({
            type: "error",
            message: "Ingestion fehlgeschlagen",
            details: status.errors.slice(0, 3).join(", "),
          });
        }
      } catch {
        // Ignore polling errors — will retry next interval
      }
    }, POLL_INTERVAL_MS);
  };

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const handleIngest = async () => {
    setToast(null);
    setError(null);

    try {
      await startIngestion();
      // Immediately fetch initial status
      const status = await getIngestionStatus();
      setIngestionStatus(status);
      startPolling();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Ingestion fehlgeschlagen"
      );
    }
  };

  const isRunning = ingestionStatus?.status === "running";

  // Only meaningful where the volume could be read at all; null means the
  // caller is not an admin, not that everything is indexed.
  const indexedNames = new Set(documents.map((d) => d.source_file));
  const notIndexed =
    volume === null
      ? 0
      : volume.filter((f) => f.indexable && !indexedNames.has(f.name)).length;
  const progress =
    isRunning && ingestionStatus.total_files > 0
      ? Math.round(
          ((ingestionStatus.processed + ingestionStatus.skipped) /
            ingestionStatus.total_files) *
            100,
        )
      : 0;

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-primary">
            Indizierte Dokumente
          </h2>
          <p className="text-muted-foreground">
            {documents.length} Dokumente in der Datenbank
            {notIndexed > 0 && (
              /* The comparison that needed a Job to make before #211. A file
                 on the volume and not in the index is one ingestion has not
                 reached, could not parse, or failed to register — and the
                 last of those is what 148 identical errors looked like. */
              <span className="ml-2 text-amber-700">
                · {notIndexed}{" "}
                {notIndexed === 1 ? "Datei" : "Dateien"} auf dem Volume noch
                nicht indiziert
              </span>
            )}
          </p>
        </div>
        {/* Re-indexing is `require_role(ADMIN)` on the backend, so offering
            the button to somebody it would refuse is offering a 403. App
            decides, mirroring that rule rather than the tab rule: the backend
            is open where no login is configured, and a compose installation
            keeps its button. Progress below stays visible either way — a run
            somebody else started is worth seeing. */}
        {canIngest && (
          <Button onClick={handleIngest} disabled={isRunning}>
            {isRunning ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Verarbeite...
              </>
            ) : (
              "Dokumente einlesen"
            )}
          </Button>
        )}
      </div>

      {canIngest && (
        <DocumentUpload
          onUploaded={() => {
            void loadVolume();
          }}
        />
      )}

      {/* Progress bar during ingestion */}
      {isRunning && ingestionStatus && (
        <div className="rounded-md border border-primary/20 bg-primary/5 p-4">
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-primary font-medium">
              {ingestionStatus.current_file
                ? `Verarbeite: ${ingestionStatus.current_file}`
                : "Starte..."}
            </span>
            <span className="text-muted-foreground">
              {ingestionStatus.processed + ingestionStatus.skipped} /{" "}
              {ingestionStatus.total_files}
              {ingestionStatus.skipped > 0 &&
                ` (${ingestionStatus.skipped} übersprungen)`}
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-primary/10">
            <div
              className="h-2 rounded-full bg-primary transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          {ingestionStatus.chunks_created > 0 && (
            <p className="mt-1.5 text-xs text-muted-foreground">
              {ingestionStatus.chunks_created} Chunks erstellt
            </p>
          )}
        </div>
      )}

      {/* Toast notification */}
      {toast && (
        <div
          className={`flex items-start gap-3 rounded-md border p-4 text-sm ${
            toast.type === "success"
              ? "border-green-200 bg-green-50 text-green-800"
              : "border-destructive/50 bg-destructive/10 text-destructive"
          }`}
        >
          {toast.type === "success" ? (
            <CheckCircle2 className="h-5 w-5 shrink-0 mt-0.5" />
          ) : (
            <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
          )}
          <div>
            <p>{toast.message}</p>
            {toast.details && (
              <p className="mt-1 text-xs opacity-80">{toast.details}</p>
            )}
          </div>
          <button
            onClick={() => setToast(null)}
            className="ml-auto shrink-0 text-xs opacity-60 hover:opacity-100"
          >
            &times;
          </button>
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
