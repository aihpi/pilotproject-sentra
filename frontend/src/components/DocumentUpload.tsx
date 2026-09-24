import { useRef, useState } from "react";
import type { UploadedFile } from "@/types";
import { uploadDocuments } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Loader2, Upload } from "lucide-react";

/** Adding documents to the corpus.
 *
 *  Self-contained on purpose. It lives in Dokumente today, beside the ingest
 *  button, so that upload → einlesen → see it listed is one screen. It is
 *  expected to move to Administration once that tab owns changing the corpus
 *  and Dokumente is left as the list anyone may read (#211), so it takes one
 *  callback and reaches into nothing.
 *
 *  Uploading is not indexing. A file appears on the volume immediately and in
 *  the document list only after ingestion, which is a much more expensive act
 *  somebody starts deliberately — so this says so rather than letting the
 *  absence look like a failure. */
export function DocumentUpload({ onUploaded }: { onUploaded: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [result, setResult] = useState<{
    accepted: number;
    rejected: UploadedFile[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function send(files: File[]) {
    if (files.length === 0) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await uploadDocuments(files);
      setResult({
        accepted: response.accepted,
        rejected: response.files.filter((f) => !f.accepted),
      });
      // Even a partial success changes the volume, so the listing is stale
      // either way.
      onUploaded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void send(Array.from(e.dataTransfer.files));
        }}
        className={[
          "rounded-lg border-2 border-dashed p-6 text-center transition-colors",
          dragging ? "border-primary bg-primary/5" : "border-muted",
        ].join(" ")}
      >
        <Upload className="mx-auto h-6 w-6 text-muted-foreground" />
        <p className="mt-2 text-sm text-muted-foreground">
          PDF- oder DOCX-Dateien hierher ziehen
        </p>
        <input
          ref={input}
          type="file"
          multiple
          accept=".pdf,.docx"
          aria-label="Dateien auswählen"
          className="hidden"
          onChange={(e) => void send(Array.from(e.target.files ?? []))}
        />
        <Button
          type="button"
          variant="outline"
          className="mt-3"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          {busy ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Wird hochgeladen …
            </>
          ) : (
            "Dateien auswählen"
          )}
        </Button>
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive"
        >
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-2 text-xs">
          {result.accepted > 0 && (
            <p className="text-muted-foreground">
              {result.accepted}{" "}
              {result.accepted === 1 ? "Datei" : "Dateien"} hochgeladen. Sie
              erscheinen in der Liste, sobald „Dokumente einlesen“ gelaufen ist.
            </p>
          )}
          {result.rejected.length > 0 && (
            <ul className="space-y-1 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-destructive">
              {result.rejected.map((file) => (
                <li key={file.name}>
                  <span className="font-medium">{file.name}</span>: {file.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
