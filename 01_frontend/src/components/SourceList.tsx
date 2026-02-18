import { useState } from "react";
import type { SourceResponse } from "@/types";
import { SourceCard } from "@/components/SourceCard";
import { PdfViewer } from "@/components/PdfViewer";

interface SourceListProps {
  sources: SourceResponse[];
}

export function SourceList({ sources }: SourceListProps) {
  const [selectedSource, setSelectedSource] = useState<SourceResponse | null>(null);

  if (sources.length === 0) return null;

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold">
        Quellen ({sources.length})
      </h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {sources.map((source, idx) => (
          <SourceCard
            key={`${source.aktenzeichen}-${idx}`}
            source={source}
            onClick={() => setSelectedSource(source)}
          />
        ))}
      </div>
      <PdfViewer
        filename={selectedSource?.source_file ?? null}
        title={selectedSource?.title ?? ""}
        onClose={() => setSelectedSource(null)}
      />
    </div>
  );
}
