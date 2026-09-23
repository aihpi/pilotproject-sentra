import type { QueueCall, SourceRef } from "@/types";
import { cn } from "@/lib/utils";
import { SourceCards } from "@/components/explorer/SourceCards";
import { labelFor } from "@/components/evaluation/callLabels";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface AnswerPaneProps {
  calls: QueueCall[];
  activeIndex: number;
  onSelectCall: (index: number) => void;
  onSelectSource?: (source: SourceRef) => void;
  selectedSource?: string;
}

/** One answer at a time, with tabs across the repeats.
 *
 *  The tabs switch which answer is being read; the assessment form below
 *  covers the whole case, because `Reproduzierbar?` asks whether a finding
 *  recurred across these and no single one can be asked that. The tab labels
 *  are what the form's Kernbefund boxes correspond to. */
export function AnswerPane({
  calls,
  activeIndex,
  onSelectCall,
  onSelectSource,
  selectedSource,
}: AnswerPaneProps) {
  const call = calls[activeIndex];
  if (!call) return null;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap gap-1" role="tablist" aria-label="Wiederholungen">
        {calls.map((c, i) => (
          <button
            key={c.id}
            type="button"
            role="tab"
            aria-selected={i === activeIndex}
            onClick={() => onSelectCall(i)}
            className={cn(
              "rounded-md border px-3 py-1 text-xs font-medium transition-colors",
              i === activeIndex
                ? "border-primary bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted",
            )}
          >
            {labelFor(c)}
          </button>
        ))}
      </div>

      <article className="rounded-lg border bg-card p-4">
        <div className="prose prose-sm max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{call.text}</ReactMarkdown>
        </div>
      </article>

      <SourceCards
        sources={call.sources}
        onSelect={onSelectSource}
        selected={selectedSource}
      />

      {call.dauer_ms !== null && (
        <p className="text-[11px] text-muted-foreground">
          {Math.round(call.dauer_ms / 100) / 10} s
        </p>
      )}
    </section>
  );
}
