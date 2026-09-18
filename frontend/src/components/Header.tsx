import { cn } from "@/lib/utils";
import type { ViewType } from "@/App";

interface HeaderProps {
  activeView: ViewType;
  onViewChange: (view: ViewType) => void;
}

const NAV_ITEMS: { key: ViewType; label: string }[] = [
  { key: "explorer", label: "Suche" },
  { key: "documents", label: "Dokumente" },
  // The evaluation harness is a separate service behind /api/eval. This tab
  // shows an error rather than nothing when it is not running, which is its
  // normal state outside a test round.
  { key: "evaluation", label: "Auswertung" },
  // Changing the test set is a different job from judging against it, done by
  // different people at different times. A tab rather than a permission —
  // there is no authentication anywhere in SENTRA yet, so this separates the
  // two jobs without restricting who does them.
  { key: "administration", label: "Administration" },
];

export function Header({ activeView, onViewChange }: HeaderProps) {
  return (
    <header className="border-b bg-white">
      <div className="relative mx-auto flex h-16 max-w-7xl items-center px-6">
        <div className="flex items-center gap-3">
          <img
            src="/logo_aisc_bmftr.jpg"
            alt="KI Service Zentrum"
            className="h-10"
          />
        </div>

        <h1 className="absolute left-1/2 -translate-x-1/2 text-2xl font-bold text-primary">
          SENTRA
        </h1>

        <nav className="ml-auto flex gap-1">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              onClick={() => onViewChange(item.key)}
              className={cn(
                "rounded-md px-4 py-2 text-sm font-semibold transition-colors",
                activeView === item.key
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-secondary hover:text-secondary-foreground",
              )}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}
