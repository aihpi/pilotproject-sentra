import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Search,
  FolderSearch,
  MessageSquareText,
  FileStack,
  Globe,
  HelpCircle,
  BookOpenText,
  ArrowRight,
  Loader2,
  AlertCircle,
  SlidersHorizontal,
  X,
  Sparkles,
  RotateCcw,
} from "lucide-react";
import { DocumentList } from "./DocumentList";
import { GeneratedAnswer } from "./GeneratedAnswer";
import { SourceUrlList } from "./SourceUrlList";
import {
  searchDocumentsByTopic,
  findSimilarDocuments,
  findExternalSources,
  answerQuestion,
  generateOverview,
  fetchDocuments,
  fetchConfig,
} from "@/lib/api";
import type {
  AppConfig,
  ReferatOption,
  DocumentResult,
  GeneratedAnswerResult,
  ExternalSourceResult,
  DocumentInfo,
} from "@/types";

// --- Types ---

type Tab = "dokumente" | "fragen";
type DocSubMode = "thema" | "aehnliche" | "quellen";
type FragenSubMode = "fachfrage" | "ueberblick";
type SubMode = DocSubMode | FragenSubMode;

interface SubModeConfig {
  id: SubMode;
  label: string;
  icon: React.ReactNode;
  placeholder: string;
  description: string;
}

// --- Sub-mode definitions ---

const DOC_SUB_MODES: SubModeConfig[] = [
  {
    id: "thema",
    label: "Nach Thema",
    icon: <Search className="h-3.5 w-3.5" />,
    placeholder: "Thema eingeben, z.B. „CO₂-Bepreisung“",
    description: "Zeigt alle vorhandenen Dokumente zu einem Thema",
  },
  {
    id: "aehnliche",
    label: "Ähnliche Dokumente",
    icon: <FileStack className="h-3.5 w-3.5" />,
    placeholder: "Aktenzeichen oder Titel eingeben…",
    description: "Findet ähnliche Dokumente zu einem bestehenden Dokument",
  },
  {
    id: "quellen",
    label: "Externe Quellen",
    icon: <Globe className="h-3.5 w-3.5" />,
    placeholder: "Thema eingeben, z.B. „CO₂-Bepreisung“",
    description: "Zeigt externe Quellen und Datenportale aus unseren Dokumenten",
  },
];

const FRAGEN_SUB_MODES: SubModeConfig[] = [
  {
    id: "fachfrage",
    label: "Fachfrage",
    icon: <HelpCircle className="h-3.5 w-3.5" />,
    placeholder: "Frage eingeben, z.B. „Wann tritt ETS 2 in Kraft?“",
    description: "Beantwortet eine konkrete Frage mit Quellenbezug",
  },
  {
    id: "ueberblick",
    label: "Themenüberblick",
    icon: <BookOpenText className="h-3.5 w-3.5" />,
    placeholder: "Thema eingeben, z.B. „CO₂-Bepreisung“",
    description: "Erstellt eine strukturierte Übersicht zum aktuellen Wissensstand",
  },
];

// --- Autocomplete dropdown ---

function DocumentAutocomplete({
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

// --- Filter bar ---

function FilterBar({
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
          <SelectTrigger className="h-8 w-[80px] text-xs">
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
          <SelectTrigger className="h-8 w-[80px] text-xs">
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
        <SelectTrigger className="h-8 w-[150px] text-xs">
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
        <SelectTrigger className="h-8 w-[110px] text-xs">
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

// --- Result state ---

type ResultData =
  | { type: "documents"; documents: DocumentResult[]; referenceDoc?: string }
  | { type: "answer"; result: GeneratedAnswerResult; query: string }
  | { type: "sources"; sources: ExternalSourceResult[] };

// --- Main ExplorerView ---

export function ExplorerView() {
  const [activeTab, setActiveTab] = useState<Tab>("dokumente");
  const [docSubMode, setDocSubMode] = useState<DocSubMode>("thema");
  const [fragenSubMode, setFragenSubMode] = useState<FragenSubMode>("fachfrage");
  const [query, setQuery] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [fachbereich, setFachbereich] = useState<string | null>(null);
  const [documentType, setDocumentType] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [resultData, setResultData] = useState<ResultData | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Prompt customisation (only for fragen modes)
  const [customPrompts, setCustomPrompts] = useState<Record<string, string | null>>({
    fachfrage: null,
    ueberblick: null,
  });
  const [promptDialogOpen, setPromptDialogOpen] = useState(false);
  const [draftPrompt, setDraftPrompt] = useState("");

  // Prompts and filter options come from the API so there is one definition of
  // each. Null until the request lands: the filters render empty and the
  // prompt button stays disabled rather than offering a prompt we cannot
  // vouch for. No hardcoded fallback, which is the point of the endpoint.
  const [appConfig, setAppConfig] = useState<AppConfig | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchConfig()
      .then((cfg) => {
        if (!cancelled) setAppConfig(cfg);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Konfiguration konnte nicht geladen werden.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const currentSubMode = activeTab === "dokumente" ? docSubMode : fragenSubMode;
  const subModes = activeTab === "dokumente" ? DOC_SUB_MODES : FRAGEN_SUB_MODES;
  const activeConfig = subModes.find((m) => m.id === currentSubMode)!;

  // "" while the config request is in flight; the button that opens the
  // prompt dialog is disabled until then.
  const defaultPrompt = appConfig?.prompts[currentSubMode] ?? "";

  const dateRange =
    dateFrom || dateTo
      ? { date_from: dateFrom || null, date_to: dateTo || null }
      : undefined;

  const filters =
    fachbereich || documentType
      ? { fachbereich, document_type: documentType }
      : undefined;

  const activeFilterCount =
    (dateFrom ? 1 : 0) + (dateTo ? 1 : 0) + (fachbereich ? 1 : 0) + (documentType ? 1 : 0);

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab);
    setQuery("");
    setResultData(null);
    setError(null);
    setFachbereich(null);
    setDocumentType(null);
    setDateFrom("");
    setDateTo("");
  };

  const handleSubModeChange = (mode: SubMode) => {
    if (activeTab === "dokumente") setDocSubMode(mode as DocSubMode);
    else setFragenSubMode(mode as FragenSubMode);
    setQuery("");
    setResultData(null);
    setError(null);
  };

  const handleSearch = async () => {
    if (!query.trim()) return;
    setIsLoading(true);
    setResultData(null);
    setError(null);

    try {
      switch (currentSubMode) {
        case "thema": {
          const docs = await searchDocumentsByTopic(query, dateRange, 20, filters);
          setResultData({ type: "documents", documents: docs });
          break;
        }
        case "aehnliche": {
          const docs = await findSimilarDocuments(query);
          setResultData({ type: "documents", documents: docs, referenceDoc: query });
          break;
        }
        case "quellen": {
          const sources = await findExternalSources(query, dateRange, filters);
          setResultData({ type: "sources", sources });
          break;
        }
        case "fachfrage": {
          const result = await answerQuestion(query, dateRange, 10, filters, customPrompts.fachfrage);
          setResultData({ type: "answer", result, query });
          break;
        }
        case "ueberblick": {
          const result = await generateOverview(query, dateRange, 10, filters, customPrompts.ueberblick);
          setResultData({ type: "answer", result, query });
          break;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ein Fehler ist aufgetreten.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
  };

  // --- Render results based on current mode ---
  const renderResults = () => {
    if (isLoading) {
      return (
        <div className="flex items-center justify-center py-16">
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">Suche läuft…</p>
          </div>
        </div>
      );
    }

    if (error) {
      return (
        <div className="flex items-center justify-center py-16">
          <div className="flex flex-col items-center gap-3 text-center">
            <AlertCircle className="h-6 w-6 text-destructive" />
            <p className="text-sm text-destructive">{error}</p>
          </div>
        </div>
      );
    }

    if (!resultData) return null;

    switch (resultData.type) {
      case "documents":
        return (
          <DocumentList
            documents={resultData.documents}
            referenceDoc={resultData.referenceDoc}
          />
        );
      case "answer":
        return (
          <GeneratedAnswer result={resultData.result} query={resultData.query} />
        );
      case "sources":
        return <SourceUrlList sources={resultData.sources} />;
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      {/* Title */}
      <div className="mb-8 text-center">
        <h2 className="text-2xl font-bold text-foreground">
          Wissenschaftliche Dienste durchsuchen
        </h2>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Dokumente finden, Fragen beantworten und externe Quellen recherchieren
        </p>
      </div>

      {/* Tabs */}
      <div className="mb-6 flex justify-center">
        <div className="inline-flex rounded-xl border bg-card p-1 shadow-sm">
          <button
            onClick={() => handleTabChange("dokumente")}
            className={cn(
              "flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-all",
              activeTab === "dokumente"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
            )}
          >
            <FolderSearch className="h-4 w-4" />
            Dokumente finden
          </button>
          <button
            onClick={() => handleTabChange("fragen")}
            className={cn(
              "flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-all",
              activeTab === "fragen"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
            )}
          >
            <MessageSquareText className="h-4 w-4" />
            Fragen beantworten
          </button>
        </div>
      </div>

      {/* Sub-mode pills */}
      <div className="mb-4 flex flex-wrap justify-center gap-2">
        {subModes.map((mode) => (
          <button
            key={mode.id}
            onClick={() => handleSubModeChange(mode.id)}
            className={cn(
              "flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-all",
              currentSubMode === mode.id
                ? "border-primary/30 bg-primary/5 text-primary shadow-sm"
                : "border-transparent bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {mode.icon}
            {mode.label}
          </button>
        ))}
      </div>

      {/* Mode description */}
      <p className="mb-4 text-center text-xs text-muted-foreground">
        {activeConfig.description}
      </p>

      {/* Search input area */}
      <div className="mb-3 rounded-xl border bg-card p-4 shadow-sm">
        <div className="flex gap-2">
          {currentSubMode === "aehnliche" ? (
            <DocumentAutocomplete value={query} onChange={setQuery} onKeyDown={handleKeyDown} />
          ) : (
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={activeConfig.placeholder}
              className="h-11 flex-1 text-sm"
            />
          )}
          {activeTab === "fragen" && (
            <Button
              variant="outline"
              size="icon"
              // The dialog shows and resets the default prompt, which arrives
              // with the config. Opening it before then would show an empty
              // box and let a blank prompt be saved as a custom one.
              disabled={!appConfig}
              title={
                appConfig
                  ? "KI-Anweisungen anpassen"
                  : "KI-Anweisungen werden geladen"
              }
              className={cn(
                "h-11 w-11 shrink-0",
                customPrompts[currentSubMode]
                  ? "border-primary/50 bg-primary/5"
                  : "",
              )}
              onClick={() => {
                setDraftPrompt(customPrompts[currentSubMode] || defaultPrompt);
                setPromptDialogOpen(true);
              }}
            >
              <Sparkles
                className={cn(
                  "h-4 w-4",
                  customPrompts[currentSubMode]
                    ? "text-primary"
                    : "text-muted-foreground",
                )}
              />
            </Button>
          )}
          <Button
            onClick={handleSearch}
            disabled={!query.trim() || isLoading}
            className="h-11 px-5 gap-2"
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowRight className="h-4 w-4" />
            )}
            Suchen
          </Button>
        </div>

        {/* Collapsible filter section — hidden for "aehnliche" mode */}
        {currentSubMode !== "aehnliche" && (
          <div className="mt-3">
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setShowFilters(!showFilters)}
                className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
              >
                <SlidersHorizontal className="h-3.5 w-3.5" />
                Filter
              </button>
              {activeFilterCount > 0 && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setDateFrom("");
                    setDateTo("");
                    setFachbereich(null);
                    setDocumentType(null);
                  }}
                  className="group inline-flex items-center gap-1 rounded-full bg-primary/10 py-0.5 pl-2 pr-1 text-[11px] font-medium text-primary transition-colors hover:bg-destructive/10 hover:text-destructive"
                >
                  {activeFilterCount} aktiv
                  <span className="flex h-4 w-4 items-center justify-center rounded-full transition-colors group-hover:bg-destructive/15">
                    <X className="h-3 w-3" />
                  </span>
                </button>
              )}
            </div>
            <div
              className={cn(
                "overflow-hidden transition-all duration-200 ease-in-out",
                showFilters ? "mt-3 max-h-24 opacity-100" : "max-h-0 opacity-0",
              )}
            >
              <FilterBar
                dateFrom={dateFrom}
                dateTo={dateTo}
                onDateFromChange={setDateFrom}
                onDateToChange={setDateTo}
                fachbereich={fachbereich}
                onFachbereichChange={setFachbereich}
                documentType={documentType}
                onDocumentTypeChange={setDocumentType}
                documentTypes={appConfig?.document_types ?? []}
                referate={appConfig?.referate ?? []}
              />
            </div>
          </div>
        )}
      </div>

      {/* Results */}
      <div className="mt-6">{renderResults()}</div>

      {/* Prompt editor dialog */}
      <Dialog open={promptDialogOpen} onOpenChange={setPromptDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              KI-Anweisungen
            </DialogTitle>
            <DialogDescription>
              Passen Sie die Anweisungen an, die die KI bei der Beantwortung
              verwendet. Änderungen wirken sich auf alle zukünftigen Antworten
              in diesem Modus aus.
            </DialogDescription>
          </DialogHeader>

          <div className="py-2">
            <textarea
              value={draftPrompt}
              onChange={(e) => setDraftPrompt(e.target.value)}
              className="min-h-[220px] w-full rounded-lg border bg-muted/30 p-3 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary/20 resize-y font-mono"
              placeholder="Anweisungen eingeben…"
            />
          </div>

          <DialogFooter className="flex items-center justify-between gap-2 sm:justify-between">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setDraftPrompt(defaultPrompt);
              }}
              className="gap-1.5 text-muted-foreground"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Standard wiederherstellen
            </Button>
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => setPromptDialogOpen(false)}
              >
                Abbrechen
              </Button>
              <Button
                onClick={() => {
                  const isCustom =
                    draftPrompt.trim() !== defaultPrompt.trim();
                  setCustomPrompts((prev) => ({
                    ...prev,
                    [currentSubMode]: isCustom ? draftPrompt : null,
                  }));
                  setPromptDialogOpen(false);
                }}
              >
                Übernehmen
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
