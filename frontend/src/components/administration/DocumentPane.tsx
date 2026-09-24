import { useCallback, useEffect, useState } from "react";
import type { DocumentInfo } from "@/types";
import { fetchDocuments, withdrawDocument } from "@/lib/api";
import { DocumentUpload } from "@/components/DocumentUpload";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";

/** Changing what the corpus contains.
 *
 *  Separate from the Dokumente tab, which lists what is in the corpus and is
 *  readable by anyone. Checking is not a privileged act and changing is, so
 *  adding and withdrawing live here.
 *
 *  Withdrawal rather than deletion. The points go, so the document stops being
 *  searchable and citable; the registry row and the PDF stay, so the decision
 *  can be undone and the system can still answer whether a document was in the
 *  corpus when a past answer was generated. That distinction is stated on the
 *  screen, because "delete" means different things to a developer and to an
 *  archivist and the button should not be ambiguous about which it is. */
export function DocumentPane() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDocuments(await fetchDocuments());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function withdraw(name: string) {
    setBusy(name);
    setError(null);
    try {
      await withdrawDocument(name);
      setConfirming(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Dokumente hinzufügen</h3>
        <DocumentUpload onUploaded={load} />
      </section>

      <section className="space-y-2">
        <div className="flex items-baseline gap-3">
          <h3 className="text-sm font-semibold">Dokumente im Index</h3>
          <span className="text-xs text-muted-foreground">
            {documents.length} Dokumente
          </span>
        </div>

        <p className="text-xs text-muted-foreground">
          Zurückgezogene Dokumente sind nicht mehr durchsuchbar und werden nicht
          mehr zitiert. Die Datei und der Registrierungseintrag bleiben
          erhalten, damit nachvollziehbar bleibt, was zum Zeitpunkt einer
          früheren Antwort im Bestand war.
        </p>

        {error && (
          <p
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive"
          >
            {error}
          </p>
        )}

        {loading ? (
          <p className="text-xs text-muted-foreground">Wird geladen …</p>
        ) : documents.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Keine Dokumente im Index.
          </p>
        ) : (
          <ul className="divide-y rounded-md border">
            {documents.map((doc) => (
              <li
                key={doc.source_file}
                className="flex items-center gap-3 px-3 py-2 text-xs"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {doc.title}
                  </span>
                  <span className="block truncate text-muted-foreground">
                    {doc.aktenzeichen} · {doc.source_file}
                  </span>
                </span>

                {confirming === doc.source_file ? (
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="text-muted-foreground">
                      Wirklich zurückziehen?
                    </span>
                    <Button
                      type="button"
                      variant="destructive"
                      size="sm"
                      disabled={busy === doc.source_file}
                      onClick={() => void withdraw(doc.source_file)}
                    >
                      {busy === doc.source_file ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        "Ja, zurückziehen"
                      )}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirming(null)}
                    >
                      Abbrechen
                    </Button>
                  </span>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="shrink-0"
                    onClick={() => setConfirming(doc.source_file)}
                  >
                    Zurückziehen
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
