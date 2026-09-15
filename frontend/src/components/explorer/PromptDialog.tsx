import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { RotateCcw, Sparkles } from "lucide-react";

interface PromptDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The text being edited, held by the caller so it survives closing. */
  draft: string;
  onDraftChange: (draft: string) => void;
  /** The default for the current sub-mode, from GET /api/config. Both the
   *  reset button and the decision below need it. */
  defaultPrompt: string;
  /** Called with the edited text, or null when it matches the default. */
  onApply: (prompt: string | null) => void;
}

/** Editor for the instructions the model is given.
 *
 * Applying text equal to the default reports null rather than the text. That
 * keeps "unchanged" distinct from "customised to the same thing": a null means
 * no system_prompt is sent and the server uses its own default, so a later
 * change to that default reaches this user instead of being overridden by a
 * stale copy of it.
 */
export function PromptDialog({
  open,
  onOpenChange,
  draft,
  onDraftChange,
  defaultPrompt,
  onApply,
}: PromptDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
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
            value={draft}
            onChange={(e) => onDraftChange(e.target.value)}
            className="min-h-[220px] w-full rounded-lg border bg-muted/30 p-3 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary/20 resize-y font-mono"
            placeholder="Anweisungen eingeben…"
          />
        </div>

        <DialogFooter className="flex items-center justify-between gap-2 sm:justify-between">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onDraftChange(defaultPrompt)}
            className="gap-1.5 text-muted-foreground"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Standard wiederherstellen
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Abbrechen
            </Button>
            <Button
              onClick={() => {
                const isCustom = draft.trim() !== defaultPrompt.trim();
                onApply(isCustom ? draft : null);
                onOpenChange(false);
              }}
            >
              Übernehmen
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
