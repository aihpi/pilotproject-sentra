import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { fetchDocuments } from "@/lib/api";
import type { DocumentInfo } from "@/types";

/** Input with suggestions from the indexed documents.
 *
 * Used by the "similar documents" mode, where the query has to name a
 * document that exists rather than describe a topic.
 */
export function DocumentAutocomplete({
  value,
  onChange,
  onKeyDown,
}: {
  value: string;
  onChange: (value: string) => void;
  onKeyDown?: (e: React.KeyboardEvent) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<DocumentInfo[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  // Load document list for autocomplete
  useEffect(() => {
    fetchDocuments()
      .then(setSuggestions)
      .catch(() => setSuggestions([]));
  }, []);

  const filtered =
    value.length > 0
      ? suggestions.filter(
          (d) =>
            d.aktenzeichen.toLowerCase().includes(value.toLowerCase()) ||
            d.title.toLowerCase().includes(value.toLowerCase()),
        )
      : suggestions;

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={ref} className="relative flex-1">
      <Input
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setIsOpen(true);
        }}
        onKeyDown={onKeyDown}
        onFocus={() => setIsOpen(true)}
        placeholder="Aktenzeichen oder Titel eingeben…"
        className="h-11 text-sm"
      />
      {isOpen && filtered.length > 0 && (
        <div className="absolute z-50 mt-1 w-full rounded-lg border bg-card shadow-lg">
          <div className="max-h-56 overflow-y-auto p-1">
            {filtered.map((doc) => (
              <button
                key={doc.aktenzeichen}
                className="flex w-full items-start gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-muted transition-colors"
                onClick={() => {
                  onChange(doc.aktenzeichen);
                  setIsOpen(false);
                }}
              >
                <span className="shrink-0 font-mono text-xs text-muted-foreground mt-0.5">
                  {doc.aktenzeichen}
                </span>
                <span className="text-xs text-foreground line-clamp-1">
                  {doc.title}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
