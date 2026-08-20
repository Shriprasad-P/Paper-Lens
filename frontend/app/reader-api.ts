import type { ChatAnswerResponse, ChatSession, ChatSessionResponse, CitationGraph, Evidence, PaperComparisonIR, ReaderResponse, ResearchReport, ResearchRunResponse, Workspace, WorkspaceResponse } from "./reader-models";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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

export type CapabilityFlags = {
  ai_analysis_enabled: boolean;
  semantic_retrieval_enabled: boolean;
  research_agent_enabled: boolean;
  supported_sources: string[];
  beta: boolean;
};

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const desktopToken = runtimeValue("desktopToken");
  const response = await fetch(`${resolvedApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(desktopToken ? { "X-PaperLens-Desktop-Token": desktopToken } : {}),
      ...(init?.headers ?? {}),
    },
  });
  const payload = (await response.json().catch(() => null)) as T | { detail?: string } | null;
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload && payload.detail ? String(payload.detail) : "Request failed.";
    const requestId = payload && typeof payload === "object" && "error" in payload && payload.error && typeof payload.error === "object" && "request_id" in payload.error
      ? String(payload.error.request_id)
      : null;
    throw new Error(requestId && requestId !== "unknown" ? `${detail} Request ID: ${requestId}` : detail);
  }
  return payload as T;
}

export async function loadCapabilities(): Promise<CapabilityFlags> {
  return requestJson<CapabilityFlags>("/api/capabilities");
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
