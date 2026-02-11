import type { DocumentInfo } from "@/types";
import { Badge } from "@/components/ui/badge";

interface DocumentsTableProps {
  documents: DocumentInfo[];
  isLoading: boolean;
}

export function DocumentsTable({ documents, isLoading }: DocumentsTableProps) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="h-12 animate-pulse rounded-md bg-muted"
          />
        ))}
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-12 text-center">
        <p className="text-muted-foreground">
          Noch keine Dokumente indiziert. Klicken Sie auf &quot;Dokumente
          einlesen&quot;, um die Verarbeitung zu starten.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/50">
            <th className="px-4 py-3 text-left font-semibold">Aktenzeichen</th>
            <th className="px-4 py-3 text-left font-semibold">Titel</th>
            <th className="px-4 py-3 text-left font-semibold">Fachbereich</th>
            <th className="px-4 py-3 text-left font-semibold">Typ</th>
            <th className="px-4 py-3 text-left font-semibold">Datum</th>
            <th className="px-4 py-3 text-left font-semibold">Sprache</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => (
            <tr
              key={doc.aktenzeichen}
              className="border-b transition-colors hover:bg-muted/50"
            >
              <td className="px-4 py-3 font-mono text-xs">
                {doc.aktenzeichen}
              </td>
              <td className="max-w-xs truncate px-4 py-3" title={doc.title}>
                {doc.title}
              </td>
              <td className="px-4 py-3">
                <Badge variant="secondary">{doc.fachbereich_number}</Badge>
              </td>
              <td className="px-4 py-3">{doc.document_type}</td>
              <td className="px-4 py-3 text-muted-foreground">
                {doc.completion_date || "–"}
              </td>
              <td className="px-4 py-3 uppercase">{doc.language}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
