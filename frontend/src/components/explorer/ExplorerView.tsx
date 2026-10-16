import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { fetchConfig } from "@/lib/api";
import { atLeast } from "@/lib/session";
import type { AppConfig, Session } from "@/types";
import {
  ArrowRight,
  FolderSearch,
  Loader2,
  MessageSquareText,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-react";

import { DocumentAutocomplete } from "./DocumentAutocomplete";
import { FilterBar } from "./FilterBar";
import { PromptDialog } from "./PromptDialog";
import { ResultPanel } from "./ResultPanel";
import { DOC_SUB_MODES, FRAGEN_SUB_MODES } from "./subModes";
import type { DocSubMode, FragenSubMode, SubMode, Tab } from "./types";
import { useExplorerSearch } from "./useExplorerSearch";

/** The explorer screen: pick a mode, type something, look at what came back.
 *
 * What is left here is the control surface and the state it needs. The pieces
 * that can be described on their own moved out: the suggestion input, the
 * filter bar, the prompt editor, the result panel, and the decision about
 * which endpoint each sub-mode calls.
 *
 * It takes the session only to decide whether to offer the prompt editor. The
 * backend refuses the field either way — see `api/auth.py::PromptRights` — and
 * this spares a reader a button that would answer 403.
 */
export function ExplorerView({ session }: { session?: Session | null }) {
  const [activeTab, setActiveTab] = useState<Tab>("dokumente");
  const [docSubMode, setDocSubMode] = useState<DocSubMode>("thema");
  const [fragenSubMode, setFragenSubMode] =
    useState<FragenSubMode>("fachfrage");
  const [query, setQuery] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [fachbereich, setFachbereich] = useState<string | null>(null);
  const [documentType, setDocumentType] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  const { isLoading, result, error, search, clear, setError } =
    useExplorerSearch();

  // Replacing the prompt is an experiment rather than a question, so it is the
  // reviewer's to run. No session means no login is configured and everything
  // is on offer, which is what the backend does in that case too.
  const mayEditPrompt =
    session === undefined ||
    session === null ||
    atLeast(session.rolle, "pruefer");

  // Prompt customisation, only for the fragen modes. Null means "use the
  // server's default" rather than "empty prompt".
  const [customPrompts, setCustomPrompts] = useState<
    Record<string, string | null>
  >({
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
  }, [setError]);

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
    (dateFrom ? 1 : 0) +
    (dateTo ? 1 : 0) +
    (fachbereich ? 1 : 0) +
    (documentType ? 1 : 0);

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab);
    setQuery("");
    clear();
    setFachbereich(null);
    setDocumentType(null);
    setDateFrom("");
    setDateTo("");
  };

  const handleSubModeChange = (mode: SubMode) => {
    if (activeTab === "dokumente") setDocSubMode(mode as DocSubMode);
    else setFragenSubMode(mode as FragenSubMode);
    setQuery("");
    clear();
  };

  const handleSearch = () =>
    search({
      query,
      subMode: currentSubMode,
      dateRange,
      filters,
      customPrompt: customPrompts[currentSubMode],
    });

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
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
            <DocumentAutocomplete
              value={query}
              onChange={setQuery}
              onKeyDown={handleKeyDown}
            />
          ) : (
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={activeConfig.placeholder}
              className="h-11 flex-1 text-sm"
            />
          )}
          {activeTab === "fragen" && mayEditPrompt && (
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
      <div className="mt-6">
        <ResultPanel isLoading={isLoading} error={error} result={result} />
      </div>
      <PromptDialog
        open={promptDialogOpen}
        onOpenChange={setPromptDialogOpen}
        draft={draftPrompt}
        onDraftChange={setDraftPrompt}
        defaultPrompt={defaultPrompt}
        onApply={(prompt) =>
          setCustomPrompts((prev) => ({ ...prev, [currentSubMode]: prompt }))
        }
      />
    </div>
  );
}
