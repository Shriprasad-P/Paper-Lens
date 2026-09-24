import type { ChatAnswerResponse, ChatSession, ChatSessionResponse, CitationGraph, Evidence, PaperComparisonIR, ReaderResponse, ResearchReport, ResearchRunResponse, Workspace, WorkspaceResponse } from "./reader-models";
import type { InteractivePaper } from "./interactive-models";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type ErrorPayload = {
  detail?: unknown;
  error?: { message?: unknown; request_id?: unknown } | unknown;
};

function runtimeValue(key: "apiBaseUrl" | "desktopToken"): string | null {
  if (typeof window === "undefined") return null;
  const storageKey = `paperlens.${key}`;
  const queryKey = key === "apiBaseUrl" ? "paperlens_api" : "desktop_token";
  const queryValue = new URLSearchParams(window.location.search).get(queryKey);
  if (queryValue) {
    window.sessionStorage.setItem(storageKey, queryValue);
    return queryValue;
  }
  return window.sessionStorage.getItem(storageKey);
}

function resolvedApiBaseUrl(): string {
  return runtimeValue("apiBaseUrl") || API_BASE_URL;
}

export function apiUrl(path: string): string {
  return `${resolvedApiBaseUrl()}${path}`;
}

export type CapabilityFlags = {
  ai_analysis_enabled: boolean;
  semantic_retrieval_enabled: boolean;
  research_agent_enabled: boolean;
  supported_sources: string[];
  beta: boolean;
  provider_configured: boolean;
  provider_types: string[];
};

export type ProviderConfig = {
  id: string;
  provider_type: "ollama" | "mlx" | "openai" | "anthropic" | "gemini" | "openai_compatible";
  display_name: string;
  base_url: string;
  generation_model: string;
  embedding_model: string | null;
  secret_configured: boolean;
  masked_secret: string | null;
  enabled: boolean;
  last_tested_at: string | null;
  last_test_status: string | null;
  created_at: string;
  updated_at: string;
};

export type AuthUser = {
  id: string;
  email: string;
  created_at: string;
};

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const desktopToken = runtimeValue("desktopToken");
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...init,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(desktopToken ? { "X-PaperLens-Desktop-Token": desktopToken } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch (requestError) {
    const reason = requestError instanceof Error && requestError.message ? ` (${requestError.message})` : "";
    throw new Error(`PaperLens could not reach its local API${reason}`);
  }

  const rawBody = await response.text();
  let payload: T | ErrorPayload | string | null = null;
  if (rawBody.trim()) {
    try {
      payload = JSON.parse(rawBody) as T | ErrorPayload;
    } catch {
      payload = rawBody.trim();
    }
  }
  if (!response.ok) {
    const errorPayload = payload && typeof payload === "object" && !Array.isArray(payload) ? payload as ErrorPayload : null;
    const nestedError = errorPayload?.error && typeof errorPayload.error === "object" ? errorPayload.error as { message?: unknown; request_id?: unknown } : null;
    const detail = typeof payload === "string" && payload ? payload.slice(0, 300)
      : errorPayload?.detail ? String(errorPayload.detail)
        : nestedError?.message ? String(nestedError.message)
          : `Request failed (HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}).`;
    const requestId = nestedError?.request_id ? String(nestedError.request_id) : null;
    const retryAfter = response.status === 429 ? response.headers.get("Retry-After") : null;
    const retryMessage = retryAfter ? ` Try again in ${retryAfter} seconds.` : "";
    throw new Error(`${detail}${retryMessage}${requestId && requestId !== "unknown" ? ` Request ID: ${requestId}` : ""}`);
  }
  if (payload === null) {
    throw new Error(`PaperLens returned an empty response (HTTP ${response.status}).`);
  }
  if (typeof payload === "string") {
    throw new Error(`PaperLens returned an invalid response (HTTP ${response.status}).`);
  }
  return payload as T;
}

export async function loadCurrentUser(): Promise<AuthUser> {
  const payload = await requestJson<{ user: AuthUser }>("/api/auth/me");
  return payload.user;
}

export async function registerUser(email: string, password: string): Promise<AuthUser> {
  const payload = await requestJson<{ user: AuthUser }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  return payload.user;
}

export async function loginUser(email: string, password: string): Promise<AuthUser> {
  const payload = await requestJson<{ user: AuthUser }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  return payload.user;
}

export async function logoutUser(): Promise<void> {
  await requestJson<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
}

export async function loadCapabilities(): Promise<CapabilityFlags> {
  return requestJson<CapabilityFlags>("/api/capabilities");
}

export async function listProviderConfigs(): Promise<ProviderConfig[]> {
  return requestJson<ProviderConfig[]>("/api/provider-configs");
}

export async function saveProviderConfig(payload: {
  provider_type: ProviderConfig["provider_type"];
  display_name: string;
  base_url: string;
  generation_model: string;
  embedding_model?: string | null;
  api_key?: string | null;
  enabled?: boolean;
}): Promise<ProviderConfig> {
  return requestJson<ProviderConfig>("/api/provider-configs", { method: "POST", body: JSON.stringify(payload) });
}

export async function testProviderConfig(id: string): Promise<{ provider_id: string; status: string; message: string; tested_at: string }> {
  return requestJson(`/api/provider-configs/${encodeURIComponent(id)}/test`, { method: "POST" });
}

export async function listPapers(): Promise<import("./reader-models").ReaderPaper[]> {
  return requestJson<import("./reader-models").ReaderPaper[]>("/api/papers");
}

export async function uploadPaper(file: File): Promise<{ id: string }> {
  const desktopToken = runtimeValue("desktopToken");
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(apiUrl("/api/papers/upload"), {
    method: "POST", credentials: "include", body: form,
    headers: desktopToken ? { "X-PaperLens-Desktop-Token": desktopToken } : undefined,
  });
  const raw = await response.text();
  let payload: unknown = null;
  try { payload = raw ? JSON.parse(raw) : null; } catch { payload = raw; }
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload ? String((payload as { detail: unknown }).detail) : "The PDF could not be uploaded.";
    throw new Error(detail);
  }
  return payload as { id: string };
}

export async function resolvePaper(source: string): Promise<import("./reader-models").ResolvedPaper> {
  return requestJson<import("./reader-models").ResolvedPaper>("/api/papers/resolve", { method: "POST", body: JSON.stringify({ source }) });
}

export async function loadArchifyHtml(paperId: string, blockId: string): Promise<string> {
  const desktopToken = runtimeValue("desktopToken");
  const response = await fetch(apiUrl(`/api/papers/${encodeURIComponent(paperId)}/interactive/${encodeURIComponent(blockId)}/archify`), {
    credentials: "include",
    headers: desktopToken ? { "X-PaperLens-Desktop-Token": desktopToken } : undefined,
  });
  if (!response.ok) throw new Error("The Archify visualization could not be rendered.");
  return response.text();
}

export async function loadSourcePdf(paperId: string, signal?: AbortSignal): Promise<Blob> {
  const desktopToken = runtimeValue("desktopToken");
  const response = await fetch(apiUrl(`/api/papers/${encodeURIComponent(paperId)}/source`), {
    credentials: "include",
    headers: desktopToken ? { "X-PaperLens-Desktop-Token": desktopToken } : undefined,
    signal,
  });
  if (!response.ok) throw new Error(`The original PDF could not be loaded (HTTP ${response.status}).`);
  const blob = await response.blob();
  if (!blob.size || !blob.type.toLowerCase().includes("pdf")) throw new Error("The source did not return a PDF.");
  return blob;
}

export function evidencePath(paperId: string, evidenceId: string): string {
  return `/api/papers/${paperId}/evidence/${encodeURIComponent(evidenceId)}`;
}

export async function loadEvidence(paperId: string, evidenceId: string): Promise<Evidence> {
  return requestJson<Evidence>(evidencePath(paperId, evidenceId));
}

export async function loadReader(paperId: string): Promise<ReaderResponse> {
  return requestJson<ReaderResponse>(`/api/papers/${paperId}/reader`);
}

export async function generateInteractivePaper(paperId: string): Promise<InteractivePaper> {
  return requestJson<InteractivePaper>(`/api/papers/${paperId}/interactive`, { method: "POST" });
}

export async function createChatSession(paperId: string): Promise<ChatSession> {
  const payload = await requestJson<{
    session_id: string;
    paper_id: string;
    document_id: string;
    document_hash: string | null;
    created_at: string;
    updated_at: string;
  }>(`/api/papers/${paperId}/chat/sessions`, { method: "POST" });
  return { id: payload.session_id, paper_id: payload.paper_id, document_id: payload.document_id, document_hash: payload.document_hash, created_at: payload.created_at, updated_at: payload.updated_at };
}

export async function loadChatSession(paperId: string, sessionId: string): Promise<ChatSessionResponse> {
  return requestJson<ChatSessionResponse>(`/api/papers/${paperId}/chat/sessions/${encodeURIComponent(sessionId)}`);
}

export async function sendChatMessage(paperId: string, sessionId: string, question: string): Promise<ChatAnswerResponse> {
  return requestJson<ChatAnswerResponse>(`/api/papers/${paperId}/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export async function listWorkspaces(): Promise<Workspace[]> {
  return requestJson<Workspace[]>("/api/workspaces");
}

export async function createWorkspace(name: string): Promise<Workspace> {
  return requestJson<Workspace>("/api/workspaces", { method: "POST", body: JSON.stringify({ name }) });
}

export async function loadWorkspace(workspaceId: string): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
}

export async function addPaperToWorkspace(workspaceId: string, paperId: string): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`/api/workspaces/${encodeURIComponent(workspaceId)}/papers/${encodeURIComponent(paperId)}`, { method: "POST" });
}

export async function removePaperFromWorkspace(workspaceId: string, paperId: string): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`/api/workspaces/${encodeURIComponent(workspaceId)}/papers/${encodeURIComponent(paperId)}`, { method: "DELETE" });
}

export async function compareWorkspace(workspaceId: string, paperIds: string[]): Promise<PaperComparisonIR> {
  return requestJson<PaperComparisonIR>(`/api/workspaces/${encodeURIComponent(workspaceId)}/compare`, { method: "POST", body: JSON.stringify({ paper_ids: paperIds }) });
}

export async function loadCitationGraph(paperId: string): Promise<CitationGraph> {
  return requestJson<CitationGraph>(`/api/papers/${encodeURIComponent(paperId)}/citation-graph`);
}

export async function createResearchRun(question: string, depth: "QUICK" | "STANDARD" | "DEEP", workspaceId?: string): Promise<ResearchRunResponse> {
  return requestJson<ResearchRunResponse>("/api/research/runs", { method: "POST", body: JSON.stringify({ question, depth, workspace_id: workspaceId || null }) });
}

export async function loadResearchRun(runId: string): Promise<ResearchRunResponse> {
  return requestJson<ResearchRunResponse>(`/api/research/runs/${encodeURIComponent(runId)}`);
}

export async function executeResearchRun(runId: string): Promise<ResearchRunResponse> {
  return requestJson<ResearchRunResponse>(`/api/research/runs/${encodeURIComponent(runId)}/execute`, { method: "POST" });
}

export async function cancelResearchRun(runId: string): Promise<ResearchRunResponse> {
  return requestJson<ResearchRunResponse>(`/api/research/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
}

export async function loadResearchReport(runId: string): Promise<ResearchReport> {
  return requestJson<ResearchReport>(`/api/research/runs/${encodeURIComponent(runId)}/report`);
}
