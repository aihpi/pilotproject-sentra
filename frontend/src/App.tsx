import { useEffect, useState } from "react";
import type { Session } from "@/types";
import { atLeast, fetchSession, loginConfigured, logout } from "@/lib/session";
import { ALL_VIEWS, VIEW_ROLES } from "@/lib/views";
import { Header } from "@/components/Header";
import { LoginScreen } from "@/components/LoginScreen";
import { DocumentsView } from "@/components/DocumentsView";
import { ExplorerView } from "@/components/explorer/ExplorerView";
import { AdministrationView } from "@/components/administration/AdministrationView";
import { EvaluationView } from "@/components/evaluation/EvaluationView";

export type ViewType =
  "explorer" | "documents" | "evaluation" | "administration";

export default function App() {
  const [activeView, setActiveView] = useState<ViewType>("explorer");
  const [session, setSession] = useState<Session | null>(null);
  // Three states, not two: unknown while the first fetch is in flight, because
  // rendering the login screen and then replacing it half a second later is
  // how a signed-in person is told they are not.
  const [needsLogin, setNeedsLogin] = useState<boolean | null>(null);

  useEffect(() => {
    let current = true;
    void (async () => {
      const [configured, found] = await Promise.all([
        loginConfigured(),
        fetchSession(),
      ]);
      if (!current) return;
      setSession(found);
      // A deployment that cannot authenticate anybody is open by design and
      // should look exactly as it did before any of this existed.
      setNeedsLogin(configured && found === null);
    })();
    return () => {
      current = false;
    };
  }, []);

  if (needsLogin === null) return null;

  if (needsLogin) {
    return (
      <div className="min-h-screen bg-background">
        <LoginScreen
          onSignedIn={(found) => {
            setSession(found);
            setNeedsLogin(false);
            setActiveView(firstViewFor(found));
          }}
        />
      </div>
    );
  }

  // No session means no login is configured, and then everything is on offer —
  // which matches what the backend does in that case.
  const allowed = (view: ViewType) =>
    session === null || atLeast(session.rolle, VIEW_ROLES[view]);

  return (
    <div className="min-h-screen bg-background">
      <Header
        activeView={activeView}
        onViewChange={setActiveView}
        views={ALL_VIEWS.filter(allowed)}
        session={session}
        onSignOut={async () => {
          await logout();
          setSession(null);
          setNeedsLogin(true);
        }}
      />
      <main>
        {allowed(activeView) ? (
          <>
            {activeView === "explorer" && <ExplorerView session={session} />}
            {activeView === "documents" && <DocumentsView />}
            {activeView === "evaluation" && (
              <EvaluationView session={session} />
            )}
            {activeView === "administration" && (
              <AdministrationView session={session} />
            )}
          </>
        ) : (
          <p className="mx-auto max-w-2xl p-6 text-sm text-muted-foreground">
            Für diesen Bereich fehlt die nötige Rolle.
          </p>
        )}
      </main>
    </div>
  );
}

/** Where somebody lands after signing in: the first view their role allows.
 *
 *  A reviewer who only has Auswertung should not arrive on a tab they cannot
 *  use — and the default cannot simply be "explorer", because a role that
 *  cannot search would then start on an empty screen. */
function firstViewFor(session: Session): ViewType {
  const views = Object.keys(VIEW_ROLES) as ViewType[];
  return (
    views.find((view) => atLeast(session.rolle, VIEW_ROLES[view])) ?? "explorer"
  );
}
