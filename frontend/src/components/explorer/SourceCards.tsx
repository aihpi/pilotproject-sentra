import type { SourceRef } from "@/types";
import { pdfUrl, formatDate } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { BookOpen, Calendar, ExternalLink } from "lucide-react";

interface SourceCardsProps {
  sources: SourceRef[];
  /** Called instead of opening a new tab. The review screen shows the PDF in
   *  its own pane, because 4.3c means reading the cited passage against the
   *  claim and a new tab puts them on separate screens. */
  onSelect?: (source: SourceRef) => void;
  /** Highlighted card, when one is open in a viewer. */
  selected?: string;
}

/** The numbered source cards under a generated answer.
 *
 *  Extracted from GeneratedAnswer so the review screen can show the same cards
 *  without the feedback controls, which belong to someone searching rather
 *  than someone assessing. The numbering is what a [n] marker in the answer
 *  refers to, so it has to match the order the API returned. */
export function SourceCards({ sources, onSelect, selected }: SourceCardsProps) {
  return (
    <div className="space-y-2">
      <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        <BookOpen className="h-3.5 w-3.5" />
        Quellen ({sources.length})
      </h4>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {sources.map((source, i) => {
          const inner = (
            <>
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-primary/10 text-[11px] font-bold text-primary">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex items-start justify-between gap-1">
                  <p className="text-xs font-medium leading-snug text-foreground line-clamp-2 group-hover:text-primary transition-colors">
                    {source.title}
                  </p>
                  {!onSelect && (
                    <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity mt-0.5" />
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline" className="font-mono text-[10px] px-1 py-0">
                    {source.aktenzeichen}
                  </Badge>
                  {source.completion_date && (
                    <span className="flex items-center gap-0.5 text-[10px] text-muted-foreground">
                      <Calendar className="h-2.5 w-2.5" />
                      {formatDate(source.completion_date)}
                    </span>
                  )}
                </div>
              </div>
            </>
          );

          const className = [
            "flex items-start gap-3 rounded-lg border bg-card p-3 text-left transition-colors",
            "hover:border-primary/30 hover:shadow-sm no-underline cursor-pointer group",
            selected === source.aktenzeichen ? "border-primary ring-1 ring-primary/30" : "",
          ].join(" ");

          return onSelect ? (
            <button
              key={source.aktenzeichen}
              type="button"
              onClick={() => onSelect(source)}
              className={className}
            >
              {inner}
            </button>
          ) : (
            <a
              key={source.aktenzeichen}
              href={source.source_file ? pdfUrl(source.source_file) : undefined}
              target="_blank"
              rel="noopener noreferrer"
              className={className}
            >
              {inner}
            </a>
          );
        })}
      </div>
    </div>
  );
}
