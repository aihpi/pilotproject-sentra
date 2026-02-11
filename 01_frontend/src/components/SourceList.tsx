import type { SourceResponse } from "@/types";
import { SourceCard } from "@/components/SourceCard";

interface SourceListProps {
  sources: SourceResponse[];
}

export function SourceList({ sources }: SourceListProps) {
  if (sources.length === 0) return null;

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold">
        Quellen ({sources.length})
      </h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {sources.map((source, idx) => (
          <SourceCard key={`${source.aktenzeichen}-${idx}`} source={source} />
        ))}
      </div>
    </div>
  );
}
