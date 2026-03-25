import { useState } from "react";
import type { GeneratedAnswerResult } from "@/types";
import { cn } from "@/lib/utils";
import { pdfUrl, formatDate } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BookOpen, Calendar, ChevronDown, ChevronRight, Code2, ExternalLink } from "lucide-react";

interface GeneratedAnswerProps {
  result: GeneratedAnswerResult;
}

export function GeneratedAnswer({ result }: GeneratedAnswerProps) {
  const [showPrompt, setShowPrompt] = useState(false);

  return (
    <div className="space-y-4">
      <Card className="overflow-hidden border-l-4 border-l-accent">
        <CardContent className="pt-6">
          <div className="prose prose-slate max-w-none overflow-hidden prose-headings:text-base prose-headings:font-semibold prose-headings:mt-4 prose-headings:mb-2 prose-p:leading-relaxed prose-p:text-sm prose-li:text-sm prose-strong:text-foreground">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {result.text}
            </ReactMarkdown>
          </div>
        </CardContent>
      </Card>

      {/* Prompt transparency toggle */}
      {result.system_prompt && (
        <div>
          <button
            onClick={() => setShowPrompt(!showPrompt)}
            className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            {showPrompt ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            <Code2 className="h-3 w-3" />
            {showPrompt ? "Systemanweisung ausblenden" : "Systemanweisung anzeigen"}
          </button>
          <div
            className={cn(
              "overflow-hidden transition-all duration-200 ease-in-out",
              showPrompt ? "mt-2 max-h-[500px] opacity-100" : "max-h-0 opacity-0",
            )}
          >
            <pre className="rounded-lg border bg-muted p-4 text-xs leading-relaxed text-muted-foreground whitespace-pre-wrap font-mono">
              {result.system_prompt}
            </pre>
          </div>
        </div>
      )}

      <div className="space-y-2">
        <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <BookOpen className="h-3.5 w-3.5" />
          Quellen ({result.sources.length})
        </h4>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {result.sources.map((source, i) => (
            <a
              key={source.aktenzeichen}
              href={source.source_file ? pdfUrl(source.source_file) : undefined}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-3 rounded-lg border bg-card p-3 transition-colors hover:border-primary/30 hover:shadow-sm no-underline cursor-pointer group"
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-primary/10 text-[11px] font-bold text-primary">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex items-start justify-between gap-1">
                  <p className="text-xs font-medium leading-snug text-foreground line-clamp-2 group-hover:text-primary transition-colors">
                    {source.title}
                  </p>
                  <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity mt-0.5" />
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge
                    variant="outline"
                    className="font-mono text-[10px] px-1 py-0"
                  >
                    {source.aktenzeichen}
                  </Badge>
                  <span className="flex items-center gap-0.5 text-[10px] text-muted-foreground">
                    <Calendar className="h-2.5 w-2.5" />
                    {formatDate(source.completion_date)}
                  </span>
                </div>
              </div>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
