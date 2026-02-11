import type { SourceResponse } from "@/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface SourceCardProps {
  source: SourceResponse;
}

export function SourceCard({ source }: SourceCardProps) {
  const scorePercent = (source.score * 100).toFixed(0);

  return (
    <Card className="overflow-hidden transition-shadow hover:shadow-md">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <Badge variant="secondary" className="shrink-0 font-mono text-xs">
            {source.aktenzeichen}
          </Badge>
          <span className="shrink-0 text-xs text-muted-foreground">
            {scorePercent}%
          </span>
        </div>
        <CardTitle className="text-sm leading-tight mt-2">
          {source.title}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 space-y-1 text-xs text-muted-foreground">
        {source.section_title && (
          <p className="font-semibold text-foreground">
            Abschnitt: {source.section_title}
          </p>
        )}
        {source.text_preview && (
          <p className="line-clamp-2">{source.text_preview}</p>
        )}
      </CardContent>
    </Card>
  );
}
