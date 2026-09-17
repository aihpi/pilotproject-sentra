import type { QueueEntry } from "@/types";
import { cn } from "@/lib/utils";
import { Check } from "lucide-react";

interface QueueListProps {
  entries: QueueEntry[];
  selected: string | null;
  onSelect: (caseVersionId: string) => void;
}

/** The round's queue.
 *
 *  A list rather than one case at a time, because Hotline and WD may work the
 *  same round concurrently and need to see what is already done. It also lets
 *  somebody come back to a case they were unsure about, which a wizard would
 *  make them walk through everything to reach. */
export function QueueList({ entries, selected, onSelect }: QueueListProps) {
  const done = entries.filter((e) => e.assessed).length;

  return (
    <nav className="flex flex-col rounded-lg border bg-card">
      <div className="border-b px-3 py-2 text-xs font-semibold text-muted-foreground">
        Warteschlange — {done}/{entries.length} bearbeitet
      </div>
      <ul className="max-h-[60vh] overflow-y-auto">
        {entries.map((entry) => (
          <li key={entry.case_version_id}>
            <button
              type="button"
              onClick={() => onSelect(entry.case_version_id)}
              aria-current={selected === entry.case_version_id ? "true" : undefined}
              className={cn(
                "flex w-full items-center gap-2 border-b px-3 py-2 text-left text-xs transition-colors",
                "hover:bg-muted/60",
                selected === entry.case_version_id && "bg-primary/10 font-semibold",
              )}
            >
              <span className="w-4 shrink-0">
                {entry.assessed && <Check className="h-3.5 w-3.5 text-primary" />}
              </span>
              <span className="font-mono">{entry.test_id}</span>
              {entry.grenzfall && (
                <span
                  className="ml-auto text-[10px] uppercase text-destructive"
                  title="Grenzfall — wird nie vorgefiltert (4.4)"
                >
                  Grenzfall
                </span>
              )}
            </button>
          </li>
        ))}
        {entries.length === 0 && (
          <li className="px-3 py-6 text-center text-xs text-muted-foreground">
            Nichts zu bewerten.
          </li>
        )}
      </ul>
    </nav>
  );
}
