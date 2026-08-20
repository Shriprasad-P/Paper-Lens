"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import type { FormEvent } from "react";

import { requestJson } from "./reader-api";

type IngestedPaper = { id: string };

export default function HomePage() {
  const router = useRouter();
  const [paperUrl, setPaperUrl] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      const ingested = await requestJson<IngestedPaper>("/api/papers/ingest", {
        method: "POST",
        body: JSON.stringify({ source: paperUrl.trim() }),
      });
      router.push(`/papers/${ingested.id}`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to ingest this paper.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="page-shell landing-shell">
      <section className="hero" aria-labelledby="page-title">
        <div className="eyebrow">PAPERLENS / RESEARCH READER · PUBLIC BETA</div>
        <h1 id="page-title">Turn research papers into visual, verifiable explanations.</h1>
        <p className="hero-copy">Start with an arXiv paper. PaperLens preserves the path from the reader back to the source.</p>
        <p className="beta-notice">Public beta · arXiv is the supported source. PaperLens generates evidence-linked interpretations; verify important conclusions against the original source.</p>
        <form className="paper-form" onSubmit={handleSubmit}>
          <label htmlFor="paper-url">arXiv URL or identifier</label>
          <div className="input-row">
            <input id="paper-url" type="text" placeholder="https://arxiv.org/abs/1706.03762" value={paperUrl} onChange={(event) => setPaperUrl(event.target.value)} required />
            <button type="submit" disabled={isLoading}>{isLoading ? "Preparing…" : "Open visual reader"}</button>
          </div>
        </form>
        {isLoading ? <div className="status-card" aria-live="polite"><div className="status-heading">Preparing source document</div><p>Ingesting the arXiv paper and registering its source evidence.</p></div> : null}
        {error ? <div className="status-card error-card" role="alert"><div className="status-heading">PaperLens could not prepare this paper</div><p>{error}</p></div> : null}
      </section>
      <div className="landing-links"><Link href="/research">Ask across papers →</Link><span>·</span><Link href="/workspaces">Open research workspaces →</Link></div>
      <footer><span>Evidence first.</span><span>Unknown stays unknown.</span></footer>
    </main>
  );
}
