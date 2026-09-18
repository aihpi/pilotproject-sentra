import { useState } from "react";
import { Header } from "@/components/Header";
import { DocumentsView } from "@/components/DocumentsView";
import { ExplorerView } from "@/components/explorer/ExplorerView";
import { AdministrationView } from "@/components/administration/AdministrationView";
import { EvaluationView } from "@/components/evaluation/EvaluationView";

export type ViewType =
  "explorer" | "documents" | "evaluation" | "administration";

export default function App() {
  const [activeView, setActiveView] = useState<ViewType>("explorer");

  return (
    <div className="min-h-screen bg-background">
      <Header activeView={activeView} onViewChange={setActiveView} />
      <main>
        {activeView === "explorer" && <ExplorerView />}
        {activeView === "documents" && <DocumentsView />}
        {activeView === "evaluation" && <EvaluationView />}
        {activeView === "administration" && <AdministrationView />}
      </main>
    </div>
  );
}
