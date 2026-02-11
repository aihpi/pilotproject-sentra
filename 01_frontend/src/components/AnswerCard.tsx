import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface AnswerCardProps {
  answer: string;
  isStreaming: boolean;
}

export function AnswerCard({ answer, isStreaming }: AnswerCardProps) {
  return (
    <Card className="border-l-4 border-l-accent">
      <CardHeader>
        <CardTitle>Antwort</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="whitespace-pre-wrap leading-relaxed">
          {answer}
          {isStreaming && (
            <span className="ml-0.5 inline-block h-5 w-2 animate-pulse bg-primary" />
          )}
        </p>
      </CardContent>
    </Card>
  );
}
