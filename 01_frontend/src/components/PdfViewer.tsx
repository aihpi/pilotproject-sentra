import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

interface PdfViewerProps {
  filename: string | null;
  title: string;
  onClose: () => void;
}

export function PdfViewer({ filename, title, onClose }: PdfViewerProps) {
  if (!filename) return null;

  const pdfUrl = `${API_BASE}/documents/${encodeURIComponent(filename)}`;

  return (
    <Dialog open={!!filename} onOpenChange={(open: boolean) => !open && onClose()}>
      <DialogContent className="max-w-5xl h-[90vh] flex flex-col p-0">
        <DialogHeader className="px-6 pt-6 pb-2">
          <DialogTitle className="text-sm font-medium truncate">
            {title}
          </DialogTitle>
        </DialogHeader>
        <div className="flex-1 px-6 pb-6">
          <iframe
            src={pdfUrl}
            className="w-full h-full rounded border"
            title={`PDF: ${title}`}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
