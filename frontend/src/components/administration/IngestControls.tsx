import { useCallback, useEffect, useRef, useState } from "react";
import type { IngestionStatus } from "@/types";
import { getIngestionStatus, startIngestion } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Loader2, CheckCircle2, AlertCircle } from "lucide-react";

const POLL_INTERVAL_MS = 3000;

/** Indexing what is on the volume.
 *
 *  Beside the upload rather than in the Dokumente tab: an uploaded file only
 *  reaches the list once this has run, so upload, einlesen and seeing the
 *  result belong on one screen. POST /ingest is admin only, like the upload. */
export function IngestControls({ onFinished }: { onFinished: () => void }) {
  const [status, setStatus] = useState<IngestionStatus | null>(null);
  const [toast, setToast] = useState<{
    type: "success" | "error";
    message: string;
    details?: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const fresh = await getIngestionStatus();
        setStatus(fresh);

        if (fresh.status === "completed") {
          stopPolling();
          setToast({
            type: "success",
            message: `${fresh.processed} Dokumente verarbeitet, ${fresh.chunks_created} Chunks erstellt.${
              fresh.skipped > 0 ? ` ${fresh.skipped} übersprungen.` : ""
            }`,
            details:
              [
                fresh.errors.length > 0
                  ? `${fresh.errors.length} Fehler: ${fresh.errors.slice(0, 3).join(", ")}`
                  : null,
                // Indexed but no longer on disk. The server has always
                // computed this and only logged it, so it was invisible here.
                fresh.stale_documents?.length
                  ? `${fresh.stale_documents.length} verwaiste Dokumente im Index: ${fresh.stale_documents
                      .slice(0, 3)
                      .join(", ")}`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ") || undefined,
          });
          onFinished();
        } else if (fresh.status === "failed") {
          stopPolling();
          setToast({
            type: "error",
            message: "Ingestion fehlgeschlagen",
            details: fresh.errors.slice(0, 3).join(", "),
          });
        }
      } catch {
        // Retried on the next interval.
      }
    }, POLL_INTERVAL_MS);
  }, [onFinished, stopPolling]);

  // A run started elsewhere, or before a reload, is still worth watching.
  useEffect(() => {
    getIngestionStatus()
      .then((current) => {
        if (current.status === "running") {
          setStatus(current);
          startPolling();
        }
      })
      .catch(() => {});
    return stopPolling;
  }, [startPolling, stopPolling]);

  async function ingest() {
    setToast(null);
    setError(null);
    try {
      await startIngestion();
      setStatus(await getIngestionStatus());
      startPolling();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const running = status?.status === "running";
  const progress =
    running && status.total_files > 0
      ? Math.round(((status.processed + status.skipped) / status.total_files) * 100)
      : 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Button type="button" onClick={() => void ingest()} disabled={running}>
          {running ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Verarbeite …
            </>
          ) : (
            "Dokumente einlesen"
          )}
        </Button>
        <p className="text-xs text-muted-foreground">
          Indiziert alle Dateien auf dem Volume, die noch nicht im Index sind.
        </p>
      </div>

      {running && status && (
        <div className="rounded-md border border-primary/20 bg-primary/5 p-4">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="font-medium text-primary">
              {status.current_file ? `Verarbeite: ${status.current_file}` : "Starte …"}
            </span>
            <span className="text-muted-foreground">
              {status.processed + status.skipped} / {status.total_files}
              {status.skipped > 0 && ` (${status.skipped} übersprungen)`}
            </span>
          </div>
          <div
            className="h-2 w-full rounded-full bg-primary/10"
            role="progressbar"
            aria-valuenow={progress}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Fortschritt der Ingestion"
          >
            <div
              className="h-2 rounded-full bg-primary transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          {status.chunks_created > 0 && (
            <p className="mt-1.5 text-xs text-muted-foreground">
              {status.chunks_created} Chunks erstellt
            </p>
          )}
        </div>
      )}

      {toast && (
        <div
          className={`flex items-start gap-3 rounded-md border p-4 text-sm ${
            toast.type === "success"
              ? "border-green-200 bg-green-50 text-green-800"
              : "border-destructive/50 bg-destructive/10 text-destructive"
          }`}
        >
          {toast.type === "success" ? (
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" />
          ) : (
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
          )}
          <div>
            <p>{toast.message}</p>
            {toast.details && <p className="mt-1 text-xs opacity-80">{toast.details}</p>}
          </div>
          <button
            type="button"
            onClick={() => setToast(null)}
            aria-label="Schließen"
            className="ml-auto shrink-0 text-xs opacity-60 hover:opacity-100"
          >
            &times;
          </button>
        </div>
      )}

      {error && (
        <p
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive"
        >
          {error}
        </p>
      )}
    </div>
  );
}
