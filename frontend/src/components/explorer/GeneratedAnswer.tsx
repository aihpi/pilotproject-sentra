import { useState } from "react";
import type { GeneratedAnswerResult } from "@/types";
import { cn } from "@/lib/utils";
import { submitFeedback } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { SourceCards } from "@/components/explorer/SourceCards";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronDown, ChevronRight, Code2, ThumbsDown, ThumbsUp } from "lucide-react";

interface GeneratedAnswerProps {
  result: GeneratedAnswerResult;
  /** The question that produced this answer. Recorded with any feedback. */
  query: string;
}

export function GeneratedAnswer({ result, query }: GeneratedAnswerProps) {
  const [showPrompt, setShowPrompt] = useState(false);
  const [rating, setRating] = useState<"positive" | "negative" | null>(null);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);
  const [failed, setFailed] = useState(false);

  async function send(value: "positive" | "negative", withComment: string) {
    setRating(value);
    setFailed(false);
    try {
      await submitFeedback({
        question: query,
        answer: result.text,
        rating: value,
        comment: withComment.trim() || null,
      });
      setSent(true);
    } catch {
      // The answer is still on screen and still useful; a failed rating should
      // not read like the answer failed.
      setFailed(true);
    }
  }

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

      {/* Was this answer any good? Recorded to /api/feedback, which is the
          best available source of real test cases for evaluation rounds. */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {sent ? (
          <span className="text-muted-foreground">Danke für die Rückmeldung.</span>
        ) : (
          <>
            <span className="text-muted-foreground">War diese Antwort hilfreich?</span>
            <button
              onClick={() => send("positive", comment)}
              aria-label="Antwort war hilfreich"
              className={cn(
                "flex items-center gap-1 rounded-md border px-2 py-1 transition-colors hover:bg-muted",
                rating === "positive" && "border-primary text-primary",
              )}
            >
              <ThumbsUp className="h-3 w-3" />
              Ja
            </button>
            <button
              onClick={() => setRating("negative")}
              aria-label="Antwort war nicht hilfreich"
              className={cn(
                "flex items-center gap-1 rounded-md border px-2 py-1 transition-colors hover:bg-muted",
                rating === "negative" && "border-destructive text-destructive",
              )}
            >
              <ThumbsDown className="h-3 w-3" />
              Nein
            </button>
          </>
        )}
        {failed && (
          <span className="text-destructive">
            Rückmeldung konnte nicht gespeichert werden.
          </span>
        )}
      </div>

      {/* A negative rating is the one worth asking about, so it gets a comment
          field before it is sent. */}
      {rating === "negative" && !sent && (
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Was war falsch oder hat gefehlt? (optional)"
            className="flex-1 rounded-md border bg-card px-3 py-2 text-xs"
          />
          <button
            onClick={() => send("negative", comment)}
            className="rounded-md border px-3 py-2 text-xs font-medium transition-colors hover:bg-muted"
          >
            Senden
          </button>
        </div>
      )}

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

      <SourceCards sources={result.sources} />
    </div>
  );
}
