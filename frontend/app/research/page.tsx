"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import type { FormEvent } from "react";

import { createResearchRun } from "../reader-api";

export default function ResearchPage() {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [depth, setDepth] = useState<"QUICK" | "STANDARD" | "DEEP">("STANDARD");
  const [workspaceId, setWorkspaceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startResearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const response = await createResearchRun(question.trim(), depth, workspaceId.trim() || undefined);
      router.push(`/research/${response.run.id}`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to create the research run.");
      setBusy(false);
    }
  }

  return (
    <main className="page-shell research-shell">
      <section className="research-hero">
        <div className="eyebrow">PAPERLENS / RESEARCH AGENT</div>
        <h1>Ask across papers, keep every claim traceable.</h1>
        <p className="hero-copy">PaperLens discovers bounded arXiv candidates, ingests a small evidence set, and reports what the selected sources actually support.</p>
        <form className="research-form" onSubmit={startResearch}>
          <label htmlFor="research-question">Research question</label>
          <textarea id="research-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="How do retrieval-augmented language models reduce hallucinations?" rows={5} required />
          <div className="research-options">
            <label htmlFor="research-depth">Depth<select id="research-depth" value={depth} onChange={(event) => setDepth(event.target.value as typeof depth)}><option value="QUICK">Quick · 3 papers</option><option value="STANDARD">Standard · 5 papers</option><option value="DEEP">Deep · 8 papers</option></select></label>
            <label htmlFor="workspace-id">Workspace ID (optional)<input id="workspace-id" value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)} placeholder="workspace_…" /></label>
          </div>
          <button type="submit" disabled={busy}>{busy ? "Creating run…" : "Start evidence search"}</button>
        </form>
        {error ? <div className="status-card error-card" role="alert"><div className="status-heading">Research run could not start</div><p>{error}</p></div> : null}
      </section>
      <div className="landing-links"><Link href="/">Ingest one paper</Link><span>·</span><Link href="/workspaces">Open workspaces</Link></div>
    </main>
  );
}
