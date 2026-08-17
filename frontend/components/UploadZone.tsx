"use client";

import { useRef, useState } from "react";
import { FileUp, Loader2 } from "lucide-react";
import { uploadDocuments, ApiError } from "@/lib/api";
import type { DocumentSummary } from "@/lib/types";

const ACCEPT = ".pdf,.docx,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff";

export function UploadZone({
  onUploaded,
  onError,
}: {
  onUploaded: (docs: DocumentSummary[]) => void;
  onError: (message: string, needsConfig: boolean) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);

  async function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    setUploading(true);
    try {
      const docs = await uploadDocuments(Array.from(fileList));
      onUploaded(docs);
    } catch (err) {
      if (err instanceof ApiError) {
        onError(err.message, err.status === 400 && /configur/i.test(err.message));
      } else {
        onError("No se pudo conectar con el backend. ¿Está corriendo en el puerto 8000?", false);
      }
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <button
      type="button"
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        void handleFiles(e.dataTransfer.files);
      }}
      className={`group relative w-full cursor-pointer rounded-xl border-2 border-dashed p-10 text-center transition-all ${
        dragging
          ? "border-accent bg-[#f3e3d3]"
          : "border-line-strong bg-paper-raised hover:border-accent/60 hover:bg-[#faf5ea]"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => void handleFiles(e.target.files)}
      />
      <div className="flex flex-col items-center gap-3">
        {uploading ? (
          <Loader2 className="h-8 w-8 animate-spin text-accent" />
        ) : (
          <FileUp className="h-8 w-8 text-ink-faint transition-colors group-hover:text-accent" />
        )}
        <div>
          <p className="font-display text-lg font-medium text-ink">
            {uploading ? "Subiendo y encolando…" : "Arrastra tus papers aquí"}
          </p>
          <p className="mt-1 text-sm text-ink-soft">
            PDF, DOCX o imagen (escaneos con RapidOCR local) · también puedes hacer clic
          </p>
        </div>
      </div>
    </button>
  );
}
