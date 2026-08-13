import type {
  ChatMessage,
  DocumentDetail,
  DocumentSummary,
  Finding,
  Settings,
  Suggestion,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* respuesta sin JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export function listDocuments() {
  return request<DocumentSummary[]>("/api/documents");
}

export function getDocument(id: string) {
  return request<DocumentDetail>(`/api/documents/${id}`);
}

export function uploadDocuments(files: File[]) {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  return request<DocumentSummary[]>("/api/documents", {
    method: "POST",
    body: form,
  });
}

export function deleteDocument(id: string) {
  return request<{ ok: boolean }>(`/api/documents/${id}`, { method: "DELETE" });
}

export function updateContent(id: string, contentHtml: string) {
  return request<Finding[]>(`/api/documents/${id}/content`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content_html: contentHtml }),
  });
}

export function reanalyzeDocument(id: string) {
  return request<DocumentSummary>(`/api/documents/${id}/reanalyze`, {
    method: "POST",
  });
}

export function decideDocument(
  id: string,
  decision: "validated" | "discarded",
  comment?: string,
) {
  return request<DocumentSummary>(`/api/documents/${id}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, comment: comment ?? null }),
  });
}

export function sendChat(id: string, message: string) {
  return request<{ reply: string; suggestions: Suggestion[]; message_id: string }>(
    `/api/documents/${id}/chat`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    },
  );
}

export function exportUrl(id: string, format: "md" | "html" | "docx") {
  return `${API_BASE}/api/documents/${id}/export?format=${format}`;
}

export function getSettings() {
  return request<Settings>("/api/settings");
}

export function updateSettings(payload: Partial<Settings>) {
  return request<Settings>("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function testConnection(target: "chat" | "ocr") {
  return request<{ ok: boolean; detail: string }>("/api/settings/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target }),
  });
}

export function parseSuggestions(msg: ChatMessage): Suggestion[] {
  try {
    return JSON.parse(msg.suggestions_json) as Suggestion[];
  } catch {
    return [];
  }
}
