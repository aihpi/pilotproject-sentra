import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ReferatOption } from "@/types";

/** Date range, document type and Referat.
 *
 * The type and Referat options arrive from GET /api/config rather than
 * being listed here, so there is one definition of each.
 */
export function FilterBar({
  dateFrom,
  dateTo,
  onDateFromChange,
  onDateToChange,
  fachbereich,
  onFachbereichChange,
  documentType,
  onDocumentTypeChange,
  documentTypes,
  referate,
}: {
  dateFrom: string;
  dateTo: string;
  onDateFromChange: (v: string) => void;
  onDateToChange: (v: string) => void;
  fachbereich: string | null;
  onFachbereichChange: (v: string | null) => void;
  documentType: string | null;
  onDocumentTypeChange: (v: string | null) => void;
  /** Served by GET /api/config. Empty while that request is in flight. */
  documentTypes: string[];
  referate: ReferatOption[];
}) {
  const currentYear = new Date().getFullYear();
  const years = Array.from({ length: currentYear - 2014 }, (_, i) => 2015 + i);

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Zeitraum */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground whitespace-nowrap">Zeitraum:</span>
        <Select
          value={dateFrom || "__all__"}
          onValueChange={(v) => onDateFromChange(v === "__all__" ? "" : v)}
        >
          <SelectTrigger className="h-8 w-[80px] text-xs" aria-label="Zeitraum von">
            <SelectValue placeholder="Von" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Von</SelectItem>
            {years.map((y) => (
              <SelectItem key={y} value={String(y)}>
                {y}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">&ndash;</span>
        <Select
          value={dateTo || "__all__"}
          onValueChange={(v) => onDateToChange(v === "__all__" ? "" : v)}
        >
          <SelectTrigger className="h-8 w-[80px] text-xs" aria-label="Zeitraum bis">
            <SelectValue placeholder="Bis" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Bis</SelectItem>
            {years.map((y) => (
              <SelectItem key={y} value={String(y)}>
                {y}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Dokumenttyp */}
      <Select
        value={documentType || "__all__"}
        onValueChange={(v) => onDocumentTypeChange(v === "__all__" ? null : v)}
      >
        <SelectTrigger className="h-8 w-[150px] text-xs" aria-label="Dokumenttyp">
          <SelectValue placeholder="Dokumenttyp" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__all__">Alle Typen</SelectItem>
          {documentTypes.map((dt) => (
            <SelectItem key={dt} value={dt}>
              {dt}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Referat */}
      <Select
        value={fachbereich || "__all__"}
        onValueChange={(v) => onFachbereichChange(v === "__all__" ? null : v)}
      >
        <SelectTrigger className="h-8 w-[110px] text-xs" aria-label="Referat">
          <SelectValue placeholder="Referat" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__all__">Alle Referate</SelectItem>
          {referate.map((r) => (
            <SelectItem key={r.number} value={r.number} title={r.name}>
              {r.number}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
