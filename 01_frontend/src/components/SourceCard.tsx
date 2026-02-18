import type { SourceResponse } from "@/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FileText } from "lucide-react";

interface SourceCardProps {
  source: SourceResponse;
  onClick?: () => void;
}

export function SourceCard({ source, onClick }: SourceCardProps) {
  const scorePercent = (source.score * 100).toFixed(0);

  return (
    <Card
      className="overflow-hidden transition-shadow hover:shadow-md cursor-pointer"
      onClick={onClick}
    >
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <Badge variant="secondary" className="shrink-0 font-mono text-xs">
            {source.aktenzeichen}
          </Badge>
          <div className="flex items-center gap-2 shrink-0">
            <FileText className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">
              {scorePercent}%
            </span>
          </div>
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
