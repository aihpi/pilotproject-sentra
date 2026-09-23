import { cn } from "@/lib/utils";
import type { ViewType } from "@/App";
import type { Session } from "@/types";

interface HeaderProps {
  activeView: ViewType;
  onViewChange: (view: ViewType) => void;
  /** The views this caller may use. Filtered by App, which owns the session —
   *  the header renders what it is given rather than deciding. */
  views: ViewType[];
  /** Null when nobody is signed in — either because this installation has no
   *  login, or because they have not used it. `loginPossible` is what tells
   *  the two apart, and offering to sign in where it is impossible would be a
   *  lie about what this installation is. */
  session: Session | null;
  loginPossible: boolean;
  onSignIn: () => void;
  onSignOut: () => void;
}

const NAV_ITEMS: { key: ViewType; label: string }[] = [
  { key: "explorer", label: "Suche" },
  { key: "documents", label: "Dokumente" },
  // The evaluation harness is a separate service behind /api/eval. This tab
  // shows an error rather than nothing when it is not running, which is its
  // normal state outside a test round.
  { key: "evaluation", label: "Auswertung" },
  // Changing the test set is a different job from judging against it, done by
  // different people at different times. Offered only to an admin, and since
  // #209 only to one who has actually signed in as one.
  { key: "administration", label: "Administration" },
];

export function Header({
  activeView,
  onViewChange,
  views,
  session,
  loginPossible,
  onSignIn,
  onSignOut,
}: HeaderProps) {
  const visible = NAV_ITEMS.filter((item) => views.includes(item.key));

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

        <nav className="ml-auto flex items-center gap-1">
          {visible.map((item) => (
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

          {!session && loginPossible && (
            <span className="ml-3 flex items-center border-l pl-3">
              <button
                type="button"
                onClick={onSignIn}
                className="rounded-md px-3 py-2 text-sm font-semibold text-muted-foreground hover:bg-secondary hover:text-secondary-foreground"
              >
                Anmelden
              </button>
            </span>
          )}

          {session && (
            <span className="ml-3 flex items-center gap-2 border-l pl-3 text-xs">
              <span className="text-muted-foreground">
                {session.benutzername}
                <span className="ml-1 rounded bg-secondary px-1.5 py-0.5">
                  {session.rolle}
                </span>
              </span>
              <button
                type="button"
                onClick={onSignOut}
                className="rounded-md px-2 py-1 text-muted-foreground hover:bg-secondary"
              >
                Abmelden
              </button>
            </span>
          )}
        </nav>
      </div>
    </header>
  );
}
