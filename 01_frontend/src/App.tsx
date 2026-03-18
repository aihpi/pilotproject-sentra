import { useState } from "react";
import { Header } from "@/components/Header";
import { DocumentsView } from "@/components/DocumentsView";
import { ExplorerView } from "@/components/explorer/ExplorerView";

export type ViewType = "explorer" | "documents";

export default function App() {
  const [activeView, setActiveView] = useState<ViewType>("explorer");

  return (
    <div className="min-h-screen bg-background">
      <Header activeView={activeView} onViewChange={setActiveView} />
      <main>
        {activeView === "explorer" && <ExplorerView />}
        {activeView === "documents" && <DocumentsView />}
      </main>
    </div>
  );
}
