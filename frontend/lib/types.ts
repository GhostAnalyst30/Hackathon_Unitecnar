export type DocumentStatus =
  | "queued"
  | "extracting"
  | "analyzing"
  | "awaiting_review"
  | "validated"
  | "discarded"
  | "error";

export type FindingKind =
  | "importante"
  | "alerta"
  | "contradiccion"
  | "inconsistencia"
  | "referencia";

export interface HighlightRect {
  page: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Finding {
  id: string;
  agent: "reader" | "contradictions" | "references";
  kind: FindingKind;
  severity: "baja" | "media" | "alta";
  quote: string;
  quote_secondary: string | null;
  explanation: string;
  anchored: boolean;
  start_offset: number | null;
  end_offset: number | null;
  rects?: HighlightRect[];
}

export interface AgentOutput {
  agent: string;
  output_json: string;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  suggestions_json: string;
  created_at: string;
}

export interface ProcessLog {
  id: string;
  agent: string;
  message: string;
  created_at: string;
}

export interface Suggestion {
  original: string;
  suggested: string;
  reason: string;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  file_format: "pdf" | "docx" | "image";
  status: DocumentStatus;
  score: number | null;
  classification: string | null;
  error: string | null;
  ocr_used: boolean;
  created_at: string;
  updated_at: string;
}

export interface DocumentDetail extends DocumentSummary {
  content_html: string;
  decision_comment: string | null;
  findings: Finding[];
  agent_outputs: AgentOutput[];
  chat_messages: ChatMessage[];
  process_logs: ProcessLog[];
}

export interface CrossrefVerification {
  verificada?: boolean | null;
  doi?: string | null;
  titulo_crossref?: string | null;
  anio?: number | null;
  revista?: string | null;
  coincidencia?: number;
}

export interface ReferenceEntry extends CrossrefVerification {
  referencia: string;
  relevancia: string;
  comentario: string;
}

export interface Settings {
  provider: "qianfan" | "openai" | "openrouter" | "gemini" | "custom";
  api_key: string;
  base_url: string;
  chat_model: string;
  chat_fallback_models: string;
  ocr_api_key: string;
  ocr_base_url: string;
  ocr_model: string;
  ocr_fallback_models: string;
  reader_instructions: string;
  contradictions_instructions: string;
  references_instructions: string;
  classifier_instructions: string;
  chat_instructions: string;
}

export interface DocumentEvent {
  type: "document";
  document_id: string;
  status: string;
  agent?: string;
  message?: string;
  log_id?: string;
  created_at?: string;
  score?: number;
  classification?: string;
  error?: string;
}
