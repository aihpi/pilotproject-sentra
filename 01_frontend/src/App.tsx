import { useState } from "react";
import { Header } from "@/components/Header";
import { SearchView } from "@/components/SearchView";
import { DocumentsView } from "@/components/DocumentsView";

export default function App() {
  const [activeView, setActiveView] = useState<"search" | "documents">(
    "search"
  );

  return (
    <div className="min-h-screen bg-background">
      <Header activeView={activeView} onViewChange={setActiveView} />
      <main>
        {activeView === "search" ? <SearchView /> : <DocumentsView />}
      </main>
    </div>
  );
}
