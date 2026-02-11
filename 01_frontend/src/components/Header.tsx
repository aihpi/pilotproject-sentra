import { cn } from "@/lib/utils";

interface HeaderProps {
  activeView: "search" | "documents";
  onViewChange: (view: "search" | "documents") => void;
}

export function Header({ activeView, onViewChange }: HeaderProps) {
  return (
    <header className="border-b bg-white">
      <div className="relative mx-auto flex h-16 max-w-7xl items-center px-6">
        <div className="flex items-center gap-3">
          <img
            src="/logo_aisc_150dpi.png"
            alt="KI Service Zentrum"
            className="h-10"
          />
        </div>

        <h1 className="absolute left-1/2 -translate-x-1/2 text-2xl font-bold text-primary">
          SENTRA
        </h1>

        <nav className="ml-auto flex gap-1">
          <button
            onClick={() => onViewChange("search")}
            className={cn(
              "rounded-md px-4 py-2 text-sm font-semibold transition-colors",
              activeView === "search"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-secondary hover:text-secondary-foreground"
            )}
          >
            Suche
          </button>
          <button
            onClick={() => onViewChange("documents")}
            className={cn(
              "rounded-md px-4 py-2 text-sm font-semibold transition-colors",
              activeView === "documents"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-secondary hover:text-secondary-foreground"
            )}
          >
            Dokumente
          </button>
        </nav>
      </div>
    </header>
  );
}
