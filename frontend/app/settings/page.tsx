"use client";

import { useEffect, useState } from "react";
import {
  Eye,
  EyeOff,
  Loader2,
  PlugZap,
  Save,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { getSettings, testConnection, updateSettings } from "@/lib/api";
import type { Settings } from "@/lib/types";

const PROVIDERS = [
  {
    value: "openrouter",
    label: "OpenRouter (barato · Gemini Flash / GPT-4o mini)",
    hint: "https://openrouter.ai/api/v1 · key sk-or-… · modelos de pago baratos (hace falta un poco de crédito)",
  },
  {
    value: "gemini",
    label: "Google Gemini (API gratis · Google AI Studio)",
    hint: "https://aistudio.google.com/apikey · key AIza… · Gemini Flash con cupo gratis (visión incluida)",
  },
  {
    value: "qianfan",
    label: "Baidu Qianfan (ERNIE, DeepSeek…)",
    hint: "https://qianfan.baidubce.com/v2 · API key formato bce-v3/…",
  },
  {
    value: "openai",
    label: "OpenAI",
    hint: "https://api.openai.com/v1 · API key formato sk-…",
  },
  {
    value: "custom",
    label: "Endpoint OpenAI-compatible (custom)",
    hint: "Cualquier servicio compatible con la API de OpenAI",
  },
] as const;

const GEMINI_BASE_URL =
  "https://generativelanguage.googleapis.com/v1beta/openai/";

const CHAT_PRESETS: Record<string, { id: string; label: string; model: string }[]> = {
  openrouter: [
    {
      id: "gemini-25-flash-lite",
      label: "Barato · Gemini 2.5 Flash-Lite (visión, recomendado)",
      model: "google/gemini-2.5-flash-lite",
    },
    {
      id: "gemini-25-flash",
      label: "Barato · Gemini 2.5 Flash (visión)",
      model: "google/gemini-2.5-flash",
    },
    {
      id: "gpt-4o-mini",
      label: "Barato · GPT-4o mini (visión)",
      model: "openai/gpt-4o-mini",
    },
    {
      id: "gemini-35-flash",
      label: "Barato · Gemini 3.5 Flash (visión)",
      model: "google/gemini-3.5-flash",
    },
    {
      id: "gemma-26b-free",
      label: "Gratis · Gemma 4 26B MoE (visión, tope 50/día)",
      model: "google/gemma-4-26b-a4b-it:free",
    },
    {
      id: "gemma-31b-free",
      label: "Gratis · Gemma 4 31B (visión, tope 50/día)",
      model: "google/gemma-4-31b-it:free",
    },
    {
      id: "or-free-auto",
      label: "Gratis · Auto (OpenRouter elige un :free, tope 50/día)",
      model: "openrouter/free",
    },
  ],
  qianfan: [
    { id: "ernie", label: "ERNIE 4.5 Turbo 128k", model: "ernie-4.5-turbo-128k" },
  ],
  openai: [
    { id: "gpt-4o-mini", label: "GPT-4o mini", model: "gpt-4o-mini" },
  ],
  gemini: [
    {
      id: "gemini-25-flash",
      label: "Gratis · Gemini 2.5 Flash (visión, recomendado)",
      model: "gemini-2.5-flash",
    },
    {
      id: "gemini-25-flash-lite",
      label: "Gratis · Gemini 2.5 Flash-Lite (más rápido)",
      model: "gemini-2.5-flash-lite",
    },
    {
      id: "gemini-flash-latest",
      label: "Gratis · Gemini Flash latest",
      model: "gemini-flash-latest",
    },
    {
      id: "gemini-20-flash",
      label: "Gratis · Gemini 2.0 Flash",
      model: "gemini-2.0-flash",
    },
  ],
  custom: [],
};

const OCR_PRESETS = [
  {
    id: "or-gemini-lite",
    label: "Barato · OpenRouter · Gemini 2.5 Flash-Lite (visión)",
    base_url: "https://openrouter.ai/api/v1",
    model: "google/gemini-2.5-flash-lite",
  },
  {
    id: "or-gemini-25",
    label: "Barato · OpenRouter · Gemini 2.5 Flash (visión)",
    base_url: "https://openrouter.ai/api/v1",
    model: "google/gemini-2.5-flash",
  },
  {
    id: "or-gpt-4o-mini",
    label: "Barato · OpenRouter · GPT-4o mini (visión)",
    base_url: "https://openrouter.ai/api/v1",
    model: "openai/gpt-4o-mini",
  },
  {
    id: "or-gemini-35",
    label: "Barato · OpenRouter · Gemini 3.5 Flash (visión)",
    base_url: "https://openrouter.ai/api/v1",
    model: "google/gemini-3.5-flash",
  },
  {
    id: "gemini-flash-ocr",
    label: "Gratis · Gemini API · 2.5 Flash (visión)",
    base_url: GEMINI_BASE_URL,
    model: "gemini-2.5-flash",
  },
  {
    id: "gemini-flash-lite-ocr",
    label: "Gratis · Gemini API · 2.5 Flash-Lite",
    base_url: GEMINI_BASE_URL,
    model: "gemini-2.5-flash-lite",
  },
  {
    id: "or-gemma-26b-free",
    label: "Gratis · OpenRouter · Gemma 4 26B MoE (visión, tope 50/día)",
    base_url: "https://openrouter.ai/api/v1",
    model: "google/gemma-4-26b-a4b-it:free",
  },
  {
    id: "or-gemma-31b-free",
    label: "Gratis · OpenRouter · Gemma 4 31B (visión, tope 50/día)",
    base_url: "https://openrouter.ai/api/v1",
    model: "google/gemma-4-31b-it:free",
  },
  {
    id: "or-free-auto",
    label: "Gratis · OpenRouter · Auto (:free, tope 50/día)",
    base_url: "https://openrouter.ai/api/v1",
    model: "openrouter/free",
  },
  {
    id: "qianfan-ocr",
    label: "De pago · Qianfan-OCR (Baidu, especializado en documentos)",
    base_url: "https://qianfan.baidubce.com/v2",
    model: "qianfan-ocr",
  },
  {
    id: "or-qwen-vl",
    label: "Caro · OpenRouter · Qwen3-VL 235B",
    base_url: "https://openrouter.ai/api/v1",
    model: "qwen/qwen3-vl-235b-a22b-instruct",
  },
] as const;

const AGENT_INSTRUCTIONS: {
  field: keyof Settings;
  label: string;
  placeholder: string;
}[] = [
  {
    field: "reader_instructions",
    label: "Agente lector",
    placeholder: "Ej.: prioriza la metodología y los resultados numéricos…",
  },
  {
    field: "contradictions_instructions",
    label: "Agente de contradicciones",
    placeholder: "Ej.: sé estricto con inconsistencias estadísticas…",
  },
  {
    field: "references_instructions",
    label: "Agente de referencias",
    placeholder: "Ej.: penaliza referencias de más de 10 años…",
  },
  {
    field: "classifier_instructions",
    label: "Agente clasificador",
    placeholder: "Ej.: exige puntaje mayor a 85 para clasificar como aprobable…",
  },
  {
    field: "chat_instructions",
    label: "Asistente de chat",
    placeholder: "Ej.: responde de forma breve y en tono académico…",
  },
];

type TestResult = { ok: boolean; detail: string } | null;

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [showOcrKey, setShowOcrKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState<"chat" | "ocr" | null>(null);
  const [testResult, setTestResult] = useState<Record<string, TestResult>>({});
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    getSettings()
      .then(setSettings)
      .catch(() => setLoadError(true));
  }, []);

  function set<K extends keyof Settings>(field: K, value: Settings[K]) {
    setSettings((prev) => (prev ? { ...prev, [field]: value } : prev));
    setSaved(false);
  }

  async function handleSave() {
    if (!settings) return;
    setSaving(true);
    try {
      const updated = await updateSettings(settings);
      setSettings(updated);
      setSaved(true);
    } catch (err) {
      alert(err instanceof Error ? err.message : "No se pudo guardar");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest(target: "chat" | "ocr") {
    if (!settings) return;
    setTesting(target);
    setTestResult((prev) => ({ ...prev, [target]: null }));
    try {
      // Guarda primero para probar exactamente lo configurado
      await updateSettings(settings);
      setSaved(true);
      const result = await testConnection(target);
      setTestResult((prev) => ({ ...prev, [target]: result }));
    } catch (err) {
      setTestResult((prev) => ({
        ...prev,
        [target]: {
          ok: false,
          detail: err instanceof Error ? err.message : "Error inesperado",
        },
      }));
    } finally {
      setTesting(null);
    }
  }

  if (loadError) {
    return (
      <div className="mx-auto max-w-lg px-5 py-20 text-center text-danger">
        No se pudo conectar con el backend (puerto 8000).
      </div>
    );
  }
  if (!settings) {
    return (
      <div className="flex flex-1 items-center justify-center py-20 text-ink-faint">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Cargando configuración…
      </div>
    );
  }

  const provider = PROVIDERS.find((p) => p.value === settings.provider);

  return (
    <div className="mx-auto w-full max-w-3xl flex-1 px-5 py-8">
      <div className="rise-in mb-8">
        <h1 className="font-display text-4xl font-semibold tracking-tight text-ink">
          Configuración
        </h1>
        <p className="mt-2 text-sm text-ink-soft">
          Modelos, API keys e instrucciones personalizadas. Puedes usar{" "}
          <strong>Google Gemini</strong> con una key gratis de{" "}
          <a
            href="https://aistudio.google.com/apikey"
            target="_blank"
            rel="noreferrer"
            className="font-medium text-accent underline"
          >
            Google AI Studio
          </a>{" "}
          (Flash, cupo gratis de Google) u OpenRouter con modelos{" "}
          <strong>baratos de pago</strong> (Gemini Flash-Lite, GPT-4o mini) desde{" "}
          <a
            href="https://openrouter.ai/keys"
            target="_blank"
            rel="noreferrer"
            className="font-medium text-accent underline"
          >
            openrouter.ai/keys
          </a>
          . En OpenRouter hace falta un poco de crédito; los `:free` se acaban a
          las 50 peticiones/día. Todo se guarda en tu base local.
        </p>
      </div>

      <div className="space-y-6">
        {/* Proveedor LLM */}
        <section className="rise-in rounded-xl border border-line bg-paper-raised p-5" style={{ animationDelay: "40ms" }}>
          <h2 className="font-display text-lg font-semibold text-ink">
            Modelo de los agentes
          </h2>
          <p className="mb-4 mt-1 text-xs text-ink-faint">{provider?.hint}</p>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-soft">
                Proveedor
              </span>
              <select
                value={settings.provider}
                onChange={(e) => {
                  const next = e.target.value as Settings["provider"];
                  set("provider", next);
                  const first = CHAT_PRESETS[next]?.[0];
                  if (first) set("chat_model", first.model);
                  if (next === "gemini") {
                    set("chat_fallback_models", "gemini-2.5-flash-lite\ngemini-flash-latest");
                    set("ocr_base_url", GEMINI_BASE_URL);
                    set("ocr_model", "gemini-2.5-flash");
                    set(
                      "ocr_fallback_models",
                      "gemini-2.5-flash-lite\ngemini-flash-latest",
                    );
                  }
                  if (next === "openrouter") {
                    set("ocr_base_url", "https://openrouter.ai/api/v1");
                    set("ocr_model", "google/gemini-2.5-flash-lite");
                    set(
                      "chat_fallback_models",
                      "google/gemini-2.5-flash\nopenai/gpt-4o-mini",
                    );
                    set(
                      "ocr_fallback_models",
                      "google/gemini-2.5-flash\nopenai/gpt-4o-mini",
                    );
                  }
                }}
                className="w-full rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none focus:border-accent"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-soft">
                Modelo
              </span>
              {(CHAT_PRESETS[settings.provider] ?? []).length > 0 && (
                <select
                  value={
                    CHAT_PRESETS[settings.provider]?.find(
                      (p) => p.model === settings.chat_model,
                    )?.id ?? ""
                  }
                  onChange={(e) => {
                    const preset = CHAT_PRESETS[settings.provider]?.find(
                      (p) => p.id === e.target.value,
                    );
                    if (preset) set("chat_model", preset.model);
                  }}
                  className="mb-2 w-full rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none focus:border-accent"
                >
                  <option value="">— Escribir slug a mano —</option>
                  {CHAT_PRESETS[settings.provider].map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              )}
              <input
                value={settings.chat_model}
                onChange={(e) => set("chat_model", e.target.value)}
                placeholder={
                  settings.provider === "gemini"
                    ? "gemini-2.5-flash"
                    : "google/gemini-2.5-flash-lite"
                }
                className="w-full rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none placeholder:text-ink-faint focus:border-accent"
              />
            </label>
          </div>

          <label className="mt-4 block">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-soft">
              Modelos de respaldo
            </span>
            <p className="mb-1.5 text-xs text-ink-faint">
              Si el modelo principal no responde, cada agente reintenta varias veces
              y recorre esta lista en orden (uno por línea) antes de mostrar error.
            </p>
            <textarea
              value={settings.chat_fallback_models ?? ""}
              onChange={(e) => set("chat_fallback_models", e.target.value)}
              rows={3}
              placeholder={
                settings.provider === "gemini"
                  ? "gemini-2.5-flash-lite\ngemini-flash-latest"
                  : "google/gemini-2.5-flash\nopenai/gpt-4o-mini"
              }
              className="w-full resize-y rounded-md border border-line bg-paper px-3 py-2 font-mono text-xs outline-none placeholder:text-ink-faint focus:border-accent"
            />
            {(CHAT_PRESETS[settings.provider] ?? []).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {CHAT_PRESETS[settings.provider]
                  .filter((p) => p.model !== settings.chat_model)
                  .map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => {
                        const parts = (settings.chat_fallback_models ?? "")
                          .split(/[\s,;]+/)
                          .filter(Boolean);
                        if (parts.includes(p.model)) return;
                        set("chat_fallback_models", [...parts, p.model].join("\n"));
                      }}
                      className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-soft hover:border-accent hover:text-accent"
                    >
                      + {p.label.replace(/^(Gratis|Barato|Caro|De pago) · (rápido · )?/i, "")}
                    </button>
                  ))}
              </div>
            )}
          </label>

          {settings.provider === "custom" && (
            <label className="mt-4 block">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-soft">
                Base URL
              </span>
              <input
                value={settings.base_url}
                onChange={(e) => set("base_url", e.target.value)}
                placeholder="https://mi-endpoint.com/v1"
                className="w-full rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none placeholder:text-ink-faint focus:border-accent"
              />
            </label>
          )}

          <label className="mt-4 block">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-soft">
              API key
            </span>
            <div className="flex gap-2">
              <input
                type={showKey ? "text" : "password"}
                value={settings.api_key}
                onChange={(e) => set("api_key", e.target.value)}
                placeholder={
                  settings.provider === "gemini"
                    ? "AIza… (gratis en aistudio.google.com/apikey)"
                    : settings.provider === "openrouter"
                      ? "sk-or-… (openrouter.ai/keys · con un poco de crédito)"
                      : "sk-or-… · AIza… · bce-v3/… · sk-…"
                }
                className="w-full flex-1 rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none placeholder:text-ink-faint focus:border-accent"
              />
              <button
                onClick={() => setShowKey((v) => !v)}
                className="rounded-md border border-line px-3 text-ink-faint hover:text-ink"
                title={showKey ? "Ocultar" : "Mostrar"}
              >
                {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </label>

          <TestRow
            label="Probar conexión del modelo"
            testing={testing === "chat"}
            result={testResult.chat ?? null}
            onTest={() => void handleTest("chat")}
          />
        </section>

        {/* OCR */}
        <section className="rise-in rounded-xl border border-line bg-paper-raised p-5" style={{ animationDelay: "80ms" }}>
          <h2 className="font-display text-lg font-semibold text-ink">
            OCR — documentos escaneados e imágenes
          </h2>
          <p className="mb-4 mt-1 text-xs text-ink-faint">
            Por defecto un modelo de visión <strong>barato</strong>. Con OpenRouter:
            Gemini 2.5 Flash-Lite. Con Gemini API: Flash nativo. Si la API key
            queda vacía se reutiliza la de los agentes.
          </p>

          <label className="mb-4 block">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-soft">
              Preset rápido
            </span>
            <select
              value={
                OCR_PRESETS.find(
                  (p) =>
                    p.base_url === settings.ocr_base_url &&
                    p.model === settings.ocr_model,
                )?.id ?? ""
              }
              onChange={(e) => {
                const preset = OCR_PRESETS.find((p) => p.id === e.target.value);
                if (preset) {
                  set("ocr_base_url", preset.base_url);
                  set("ocr_model", preset.model);
                }
              }}
              className="w-full rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none focus:border-accent"
            >
              <option value="">— Configuración manual —</option>
              {OCR_PRESETS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-soft">
                Base URL
              </span>
              <input
                value={settings.ocr_base_url}
                onChange={(e) => set("ocr_base_url", e.target.value)}
                className="w-full rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none focus:border-accent"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-soft">
                Modelo OCR
              </span>
              <input
                value={settings.ocr_model}
                onChange={(e) => set("ocr_model", e.target.value)}
                className="w-full rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none focus:border-accent"
              />
            </label>
          </div>

          <label className="mt-4 block">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-soft">
              Modelos OCR de respaldo
            </span>
            <p className="mb-1.5 text-xs text-ink-faint">
              Si el OCR principal falla, se reintenta y se recorre esta lista
              completa antes de marcar error.
            </p>
            <textarea
              value={settings.ocr_fallback_models ?? ""}
              onChange={(e) => set("ocr_fallback_models", e.target.value)}
              rows={3}
              placeholder={
                settings.ocr_base_url.includes("generativelanguage.googleapis.com")
                  ? "gemini-2.5-flash-lite\ngemini-flash-latest"
                  : "google/gemini-2.5-flash\nopenai/gpt-4o-mini"
              }
              className="w-full resize-y rounded-md border border-line bg-paper px-3 py-2 font-mono text-xs outline-none placeholder:text-ink-faint focus:border-accent"
            />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {OCR_PRESETS.filter((p) => p.model !== settings.ocr_model).map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    const parts = (settings.ocr_fallback_models ?? "")
                      .split(/[\s,;]+/)
                      .filter(Boolean);
                    if (parts.includes(p.model)) return;
                    set("ocr_fallback_models", [...parts, p.model].join("\n"));
                  }}
                  className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-soft hover:border-accent hover:text-accent"
                >
                  + {p.label.replace(/^(Gratis|Barato|Caro|De pago) · (rápido · )?(OpenRouter · |Gemini API · )?/i, "").replace(/^OpenRouter · /, "")}
                </button>
              ))}
            </div>
          </label>

          <label className="mt-4 block">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-soft">
              API key del OCR (opcional)
            </span>
            <div className="flex gap-2">
              <input
                type={showOcrKey ? "text" : "password"}
                value={settings.ocr_api_key}
                onChange={(e) => set("ocr_api_key", e.target.value)}
                placeholder="Vacío = usar la API key de arriba"
                className="w-full flex-1 rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none placeholder:text-ink-faint focus:border-accent"
              />
              <button
                onClick={() => setShowOcrKey((v) => !v)}
                className="rounded-md border border-line px-3 text-ink-faint hover:text-ink"
              >
                {showOcrKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </label>

          <TestRow
            label="Probar conexión OCR"
            testing={testing === "ocr"}
            result={testResult.ocr ?? null}
            onTest={() => void handleTest("ocr")}
          />
        </section>

        {/* Instrucciones por agente */}
        <section className="rise-in rounded-xl border border-line bg-paper-raised p-5" style={{ animationDelay: "120ms" }}>
          <h2 className="font-display text-lg font-semibold text-ink">
            Personalizar respuestas por agente
          </h2>
          <p className="mb-4 mt-1 text-xs text-ink-faint">
            Instrucciones adicionales que cada agente respetará siempre. Déjalas
            vacías para usar el comportamiento por defecto.
          </p>
          <div className="space-y-3">
            {AGENT_INSTRUCTIONS.map(({ field, label, placeholder }) => (
              <label key={field} className="block">
                <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-soft">
                  {label}
                </span>
                <textarea
                  value={settings[field] as string}
                  onChange={(e) => set(field, e.target.value)}
                  placeholder={placeholder}
                  rows={2}
                  className="w-full resize-y rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none placeholder:text-ink-faint focus:border-accent"
                />
              </label>
            ))}
          </div>
        </section>

        <div className="rise-in flex items-center gap-3 pb-10" style={{ animationDelay: "160ms" }}>
          <button
            onClick={() => void handleSave()}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-strong disabled:opacity-50"
          >
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Guardar configuración
          </button>
          {saved && (
            <span className="inline-flex items-center gap-1 text-sm font-medium text-ok">
              <CheckCircle2 className="h-4 w-4" /> Guardado
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function TestRow({
  label,
  testing,
  result,
  onTest,
}: {
  label: string;
  testing: boolean;
  result: TestResult;
  onTest: () => void;
}) {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <button
        onClick={onTest}
        disabled={testing}
        className="inline-flex items-center gap-1.5 rounded-md border border-line-strong px-3 py-1.5 text-xs font-semibold text-ink-soft transition-colors hover:border-accent hover:text-accent disabled:opacity-50"
      >
        {testing ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <PlugZap className="h-3.5 w-3.5" />
        )}
        {label}
      </button>
      {result && (
        <span
          className={`inline-flex items-center gap-1 text-xs font-medium ${
            result.ok ? "text-ok" : "text-danger"
          }`}
        >
          {result.ok ? (
            <CheckCircle2 className="h-3.5 w-3.5" />
          ) : (
            <XCircle className="h-3.5 w-3.5" />
          )}
          {result.detail}
        </span>
      )}
    </div>
  );
}
