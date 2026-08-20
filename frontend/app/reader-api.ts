import type { ReaderResponse, Evidence } from "./reader-models";

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
