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
  /** Whether anybody *could* sign in. Decides whether to offer the button, not
   *  whether to demand it. */
  const [loginPossible, setLoginPossible] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  // Nothing renders until the first fetch lands. Showing the signed-out header
  // and replacing it half a second later tells a signed-in person they are not.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let current = true;
    void (async () => {
      const [configured, found] = await Promise.all([
        loginConfigured(),
        fetchSession(),
      ]);
      if (!current) return;
      setSession(found);
      setLoginPossible(configured);
      setReady(true);
    })();
    return () => {
      current = false;
    };
  }, []);

  if (!ready) return null;

  /** **An anonymous visitor is a reader.**
   *
   *  This one line is the whole of #209. It used to say that no session meant
   *  everything was allowed, which matched the backend — `require_role` opens
   *  entirely while nothing is configured to check against — and which meant
   *  that on the deployed instance every visitor was offered Administration,
   *  including the screen that creates users.
   *
   *  That was defensible while there was nothing in front of SENTRA. There now
   *  is: the site sits behind a shared password, so "anybody who reaches this
   *  is trusted completely" describes a much larger group than it used to.
   *
   *  Signing in is how somebody becomes more than a reader, and the tabs that
   *  belong to a reviewer or an admin are not offered until they do. */
  const role = session?.rolle ?? "leser";
  const allowed = (view: ViewType) => atLeast(role, VIEW_ROLES[view]);

  if (signingIn) {
    return (
      <div className="min-h-screen bg-background">
        <LoginScreen
          onSignedIn={(found) => {
            setSession(found);
            setSigningIn(false);
            // Deliberately staying on the current tab. Signing in only ever
            // adds, so wherever they were is still somewhere they may be, and
            // moving them is the kind of surprise that reads as a bug.
          }}
          onCancel={() => setSigningIn(false)}
        />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <Header
        activeView={activeView}
        onViewChange={setActiveView}
        views={ALL_VIEWS.filter(allowed)}
        session={session}
        loginPossible={loginPossible}
        onSignIn={() => setSigningIn(true)}
        onSignOut={async () => {
          await logout();
          setSession(null);
          // Signing out can take the current tab away, unlike signing in.
          if (!atLeast("leser", VIEW_ROLES[activeView])) {
            setActiveView("explorer");
          }
        }}
      />
      <main>
        {allowed(activeView) ? (
          <>
            {activeView === "explorer" && <ExplorerView />}
            {activeView === "documents" && (
              /* Mirrors `require_role(ADMIN)` on POST /ingest rather than the
                 tab rule above: the backend is open while no login is
                 configured, so a compose installation keeps its button. */
              <DocumentsView
                canIngest={!loginPossible || atLeast(role, "admin")}
              />
            )}
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
