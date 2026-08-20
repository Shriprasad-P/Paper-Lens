import type { ChatAnswerResponse, ChatSession, ChatSessionResponse, Evidence, ReaderResponse } from "./reader-models";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const payload = (await response.json().catch(() => null)) as T | { detail?: string } | null;
  if (!response.ok) {
    throw new Error(
      payload && typeof payload === "object" && "detail" in payload && payload.detail
        ? payload.detail
        : "Request failed.",
    );
  }
  return payload as T;
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
