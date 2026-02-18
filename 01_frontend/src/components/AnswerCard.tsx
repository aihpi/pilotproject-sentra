import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Copy, Check, ThumbsUp, ThumbsDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface AnswerCardProps {
  answer: string;
  isStreaming: boolean;
  feedbackGiven: "positive" | "negative" | null;
  onFeedback: (rating: "positive" | "negative") => void;
}

export function AnswerCard({
  answer,
  isStreaming,
  feedbackGiven,
  onFeedback,
}: AnswerCardProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Card className="border-l-4 border-l-accent">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Antwort</CardTitle>
          {!isStreaming && answer && (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={handleCopy}
              title="Antwort kopieren"
            >
              {copied ? (
                <Check className="h-4 w-4 text-green-600" />
              ) : (
                <Copy className="h-4 w-4" />
              )}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div>
          <div className="prose prose-slate dark:prose-invert max-w-none prose-headings:text-base prose-headings:font-semibold prose-p:leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {answer}
            </ReactMarkdown>
          </div>
          {isStreaming && (
            <span className="mt-1 inline-block h-5 w-2 animate-pulse bg-primary" />
          )}
        </div>
      </CardContent>
      {!isStreaming && answer && (
        <div className="flex items-center gap-2 px-6 pb-4">
          <span className="text-xs text-muted-foreground mr-1">
            War diese Antwort hilfreich?
          </span>
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              "h-8 w-8",
              feedbackGiven === "positive" && "text-green-600 bg-green-50"
            )}
            onClick={() => onFeedback("positive")}
            disabled={feedbackGiven !== null}
          >
            <ThumbsUp className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              "h-8 w-8",
              feedbackGiven === "negative" && "text-red-600 bg-red-50"
            )}
            onClick={() => onFeedback("negative")}
            disabled={feedbackGiven !== null}
          >
            <ThumbsDown className="h-4 w-4" />
          </Button>
        </div>
      )}
    </Card>
  );
}
