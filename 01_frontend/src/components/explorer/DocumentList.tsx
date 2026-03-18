import { useState } from "react";
import type { DocumentResult } from "@/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { pdfUrl, formatDate } from "@/lib/api";
import {
  FileText,
  ArrowUpDown,
  Calendar,
  Building2,
  ExternalLink,
} from "lucide-react";

type SortMode = "relevance" | "date";

interface DocumentListProps {
  documents: DocumentResult[];
  referenceDoc?: string;
}

export function DocumentList({ documents, referenceDoc }: DocumentListProps) {
  const [sortMode, setSortMode] = useState<SortMode>("relevance");

  const sorted = [...documents].sort((a, b) => {
    if (sortMode === "relevance") return b.relevance_score - a.relevance_score;
    return (b.completion_date || "").localeCompare(a.completion_date || "");
  });

  const docTypeColor = (type: string) => {
    switch (type) {
      case "Ausarbeitung":
        return "bg-primary/10 text-primary border-primary/20";
      case "Sachstand":
        return "bg-blue-50 text-blue-700 border-blue-200";
      case "Dokumentation":
        return "bg-amber-50 text-amber-700 border-amber-200";
      case "Kurzinformation":
        return "bg-green-50 text-green-700 border-green-200";
      default:
        return "bg-muted text-muted-foreground border-border";
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {sorted.length} Dokument{sorted.length !== 1 && "e"} gefunden
          {referenceDoc && (
            <span>
              {" "}&mdash; ähnlich zu <span className="font-mono font-medium text-foreground">{referenceDoc}</span>
            </span>
          )}
        </p>
        <div className="flex items-center gap-1 rounded-lg border bg-card p-0.5">
          <button
            onClick={() => setSortMode("relevance")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              sortMode === "relevance"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <ArrowUpDown className="h-3 w-3" />
            Relevanz
          </button>
          <button
            onClick={() => setSortMode("date")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              sortMode === "date"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Calendar className="h-3 w-3" />
            Datum
          </button>
        </div>
      </div>

      <div className="space-y-2">
        {sorted.map((doc) => (
          <a
            key={doc.aktenzeichen}
            href={doc.source_file ? pdfUrl(doc.source_file) : undefined}
            target="_blank"
            rel="noopener noreferrer"
            className="group flex gap-4 rounded-lg border bg-card p-4 transition-all hover:shadow-md hover:border-primary/30 no-underline cursor-pointer"
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/5 text-primary">
              <FileText className="h-4.5 w-4.5" />
            </div>

            <div className="min-w-0 flex-1 space-y-1.5">
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-sm font-semibold leading-snug text-foreground group-hover:text-primary transition-colors">
                  {doc.title}
                </h3>
                <div className="shrink-0 flex items-center gap-2">
                  <ExternalLink className="h-3.5 w-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                  <div className="text-right">
                    <div className="text-xs tabular-nums font-medium text-muted-foreground">
                      {Math.round(doc.relevance_score * 100)}%
                    </div>
                    <div className="mt-0.5 h-1.5 w-12 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-primary/60 transition-all"
                        style={{ width: `${doc.relevance_score * 100}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  variant="outline"
                  className="font-mono text-[11px] px-1.5 py-0"
                >
                  {doc.aktenzeichen}
                </Badge>
                <Badge
                  variant="outline"
                  className={cn("text-[11px] px-1.5 py-0 border", docTypeColor(doc.document_type))}
                >
                  {doc.document_type}
                </Badge>
                <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                  <Calendar className="h-3 w-3" />
                  {formatDate(doc.completion_date)}
                </span>
                <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                  <Building2 className="h-3 w-3" />
                  {doc.fachbereich}
                </span>
              </div>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
