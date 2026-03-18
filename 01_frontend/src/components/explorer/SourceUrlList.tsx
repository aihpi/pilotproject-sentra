import type { ExternalSourceResult } from "@/types";
import { Badge } from "@/components/ui/badge";
import { ExternalLink, FileText } from "lucide-react";

interface SourceUrlListProps {
  sources: ExternalSourceResult[];
}

export function SourceUrlList({ sources }: SourceUrlListProps) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {sources.length} externe Quelle{sources.length !== 1 && "n"} in den Dokumenten referenziert
      </p>

      <div className="space-y-3">
        {sources.map((source) => (
          <div
            key={source.url}
            className="group rounded-lg border bg-card p-4 transition-all hover:shadow-md hover:border-primary/30"
          >
            <div className="space-y-2.5">
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
                  <ExternalLink className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors">
                    {source.label}
                  </h3>
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-0.5 block truncate text-xs text-primary/70 hover:text-primary hover:underline"
                  >
                    {source.url}
                  </a>
                </div>
              </div>

              <p className="text-xs leading-relaxed text-muted-foreground pl-11">
                {source.context}
              </p>

              <div className="flex flex-wrap items-center gap-1.5 pl-11">
                <span className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  <FileText className="h-3 w-3" />
                  Zitiert in:
                </span>
                {source.cited_in.map((doc) => (
                  <Badge
                    key={doc.aktenzeichen}
                    variant="outline"
                    className="font-mono text-[10px] px-1.5 py-0"
                    title={doc.title}
                  >
                    {doc.aktenzeichen}
                  </Badge>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
