import { useState } from "react";
import type { SourceResponse } from "@/types";
import { streamQuery, submitFeedback } from "@/lib/api";
import { SearchBar } from "@/components/SearchBar";
import { AnswerCard } from "@/components/AnswerCard";
import { SourceList } from "@/components/SourceList";

export function SearchView() {
  const [question, setQuestion] = useState("");
  const [fachbereich, setFachbereich] = useState<string | null>(null);
  const [documentType, setDocumentType] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [feedbackGiven, setFeedbackGiven] = useState<"positive" | "negative" | null>(null);

  const handleSearch = async () => {
    if (!question.trim() || isStreaming) return;

    setAnswer("");
    setSources([]);
    setError(null);
    setFeedbackGiven(null);
    setIsStreaming(true);

    try {
      await streamQuery(
        { question, fachbereich, document_type: documentType },
        {
          onToken: (token) => setAnswer((prev) => prev + token),
          onSources: (srcs) => setSources(srcs),
          onDone: () => setIsStreaming(false),
          onError: (err) => {
            setError(err);
            setIsStreaming(false);
          },
        }
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Suche fehlgeschlagen"
      );
      setIsStreaming(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-primary">
          Wissenschaftliche Dienste durchsuchen
        </h2>
        <p className="mt-1 text-muted-foreground">
          Stellen Sie eine Frage zu den Ausarbeitungen der Wissenschaftlichen
          Dienste des Deutschen Bundestages.
        </p>
      </div>

      <SearchBar
        question={question}
        onQuestionChange={setQuestion}
        fachbereich={fachbereich}
        onFachbereichChange={setFachbereich}
        documentType={documentType}
        onDocumentTypeChange={setDocumentType}
        onSearch={handleSearch}
        isLoading={isStreaming}
      />

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {(answer || isStreaming) && (
        <div className="space-y-6">
          <AnswerCard
            answer={answer}
            isStreaming={isStreaming}
            feedbackGiven={feedbackGiven}
            onFeedback={(rating) => {
              setFeedbackGiven(rating);
              submitFeedback({ question, answer, rating }).catch((err) =>
                console.error("Failed to submit feedback:", err)
              );
            }}
          />
          <SourceList sources={sources} />
        </div>
      )}
    </div>
  );
}
