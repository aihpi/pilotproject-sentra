import { Search, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const FACHBEREICHE = [
  { value: "WD 1", label: "WD 1: Geschichte, Zeitgeschichte und Politik" },
  { value: "WD 2", label: "WD 2: Auswärtiges, Völkerrecht, wirtschaftliche Zusammenarbeit und Entwicklung" },
  { value: "WD 3", label: "WD 3: Verfassung und Verwaltung" },
  { value: "WD 4", label: "WD 4: Haushalt und Finanzen" },
  { value: "WD 5", label: "WD 5: Wirtschaft und Verkehr, Ernährung, Landwirtschaft und Verbraucherschutz" },
  { value: "WD 6", label: "WD 6: Arbeit und Soziales" },
  { value: "WD 7", label: "WD 7: Zivil-, Straf- und Verfahrensrecht, Umweltschutzrecht, Bau und Stadtentwicklung" },
  { value: "WD 8", label: "WD 8: Umwelt, Naturschutz, Reaktorsicherheit, Bildung und Forschung" },
  { value: "WD 9", label: "WD 9: Gesundheit, Familie, Senioren, Frauen und Jugend" },
  { value: "WD 10", label: "WD 10: Kultur, Medien und Sport" },
  { value: "EU 6", label: "EU 6: Europa" },
];

const DOCUMENT_TYPES = [
  "Ausarbeitung",
  "Sachstand",
  "Kurzinformation",
  "Dokumentation",
  "Sonstiges",
];

interface SearchBarProps {
  question: string;
  onQuestionChange: (q: string) => void;
  fachbereich: string | null;
  onFachbereichChange: (fb: string | null) => void;
  documentType: string | null;
  onDocumentTypeChange: (dt: string | null) => void;
  onSearch: () => void;
  isLoading: boolean;
}

export function SearchBar({
  question,
  onQuestionChange,
  fachbereich,
  onFachbereichChange,
  documentType,
  onDocumentTypeChange,
  onSearch,
  isLoading,
}: SearchBarProps) {
  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <Input
          value={question}
          onChange={(e) => onQuestionChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !isLoading) onSearch();
          }}
          placeholder="Frage eingeben..."
          className="h-12 text-base"
          disabled={isLoading}
        />
        <Button
          onClick={onSearch}
          disabled={isLoading || !question.trim()}
          size="lg"
          className="h-12 px-6"
        >
          {isLoading ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Search className="h-5 w-5" />
          )}
        </Button>
      </div>

      <div className="flex flex-wrap gap-3">
        <Select
          value={fachbereich ?? "__all__"}
          onValueChange={(v) => onFachbereichChange(v === "__all__" ? null : v)}
        >
          <SelectTrigger className="w-[280px]">
            <SelectValue placeholder="Fachbereich" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Alle Fachbereiche</SelectItem>
            {FACHBEREICHE.map((fb) => (
              <SelectItem key={fb.value} value={fb.value}>
                {fb.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={documentType ?? "__all__"}
          onValueChange={(v) => onDocumentTypeChange(v === "__all__" ? null : v)}
        >
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="Dokumenttyp" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Alle Typen</SelectItem>
            {DOCUMENT_TYPES.map((dt) => (
              <SelectItem key={dt} value={dt}>
                {dt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
