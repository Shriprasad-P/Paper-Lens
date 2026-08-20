"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { loadReader, requestJson } from "../../reader-api";
import { PaperReader } from "../../components/paper-reader";
import type { ReaderResponse } from "../../reader-models";

export default function ReaderPageClient({ paperId }: { paperId: string }) {
  const [reader, setReader] = useState<ReaderResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [verificationError, setVerificationError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setReader(await loadReader(paperId));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "The reader could not be loaded.");
    } finally {
      setIsLoading(false);
    }
  }, [paperId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const analyze = useCallback(async () => {
    setAnalysisError(null);
    try {
      await requestJson(`/api/papers/${paperId}/extract`, { method: "POST" });
      await refresh();
    } catch (requestError) {
      setAnalysisError(requestError instanceof Error ? requestError.message : "Analysis could not be completed.");
    }
  }, [paperId, refresh]);

  const verify = useCallback(async () => {
    setVerificationError(null);
    try {
      await requestJson(`/api/papers/${paperId}/verify`, { method: "POST" });
      await refresh();
    } catch (requestError) {
      setVerificationError(requestError instanceof Error ? requestError.message : "Verification could not be completed.");
    }
  }, [paperId, refresh]);

  if (isLoading) return <main className="reader-loading"><div className="eyebrow">PAPERLENS / VISUAL READER</div><h1>Loading the research story…</h1><p>Fetching persisted analysis and source metadata.</p></main>;
  if (error || !reader) return <main className="reader-loading"><div className="eyebrow">PAPERLENS / VISUAL READER</div><h1>Reader unavailable</h1><p>{error || "The reader response was empty."}</p><Link className="back-link" href="/">← Return home</Link></main>;
  const aiEnabled = reader.capabilities?.ai_analysis_enabled ?? true;
  return <PaperReader reader={reader} onAnalyze={reader.analysis || !aiEnabled ? undefined : analyze} analysisError={analysisError} onVerify={reader.analysis && aiEnabled ? verify : undefined} verificationError={verificationError} />;
}
