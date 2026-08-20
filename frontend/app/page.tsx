"use client";

import { useState } from "react";
import type { FormEvent } from "react";

type ParsedSection = {
  title: string;
  order: number;
  text: string;
};

type IngestedPaper = {
  id: string;
  status: string;
  metadata: {
    arxiv_id: string;
    title: string;
    authors: string[];
    abstract: string | null;
    published_at: string | null;
    updated_at: string | null;
    categories: string[];
    source_url: string;
    pdf_url: string;
  };
  sections: ParsedSection[];
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HomePage() {
  const [paperUrl, setPaperUrl] = useState("");
  const [paper, setPaper] = useState<IngestedPaper | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);
    setPaper(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/papers/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: paperUrl.trim() }),
      });
      const payload = (await response.json().catch(() => null)) as IngestedPaper | { detail?: string } | null;
      if (!response.ok) {
        throw new Error(
          payload && "detail" in payload && payload.detail ? payload.detail : "Unable to ingest this paper.",
        );
      }
      setPaper(payload as IngestedPaper);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to ingest this paper.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="page-shell">
      <section className="hero" aria-labelledby="page-title">
        <div className="eyebrow">PAPERLENS / RESEARCH READER</div>
        <h1 id="page-title">Turn research papers into visual, verifiable explanations.</h1>
        <p className="hero-copy">
          Start with an arXiv paper. PaperLens preserves the path from the reader back to the source.
        </p>

        <form className="paper-form" onSubmit={handleSubmit}>
          <label htmlFor="paper-url">arXiv URL or identifier</label>
          <div className="input-row">
            <input
              id="paper-url"
              type="text"
              placeholder="https://arxiv.org/abs/1706.03762"
              value={paperUrl}
              onChange={(event) => setPaperUrl(event.target.value)}
              required
            />
            <button type="submit" disabled={isLoading}>
              {isLoading ? "Preparing…" : "Visualize Paper"}
            </button>
          </div>
        </form>

        {isLoading ? (
          <div className="status-card" aria-live="polite">
            <div className="status-heading">Preparing paper</div>
            <p>Validating the arXiv source, retrieving metadata and the PDF, then parsing sections.</p>
          </div>
        ) : null}

        {error ? (
          <div className="status-card error-card" role="alert">
            <div className="status-heading">PaperLens could not ingest this paper</div>
            <p>{error}</p>
          </div>
        ) : null}
      </section>

      {paper ? <PaperView paper={paper} /> : null}

      <footer>
        <span>Evidence first.</span>
        <span>Unknown stays unknown.</span>
      </footer>
    </main>
  );
}

function PaperView({ paper }: { paper: IngestedPaper }) {
  const { metadata } = paper;
  return (
    <section className="paper-view" aria-labelledby="paper-title">
      <div className="paper-meta-row">
        <span className="eyebrow">INGESTED PAPER / {metadata.arxiv_id}</span>
        <span className="paper-status">{paper.status}</span>
      </div>
      <h2 id="paper-title">{metadata.title}</h2>
      <p className="authors">{metadata.authors.join(" · ") || "Authors unavailable"}</p>
      <div className="metadata-links">
        <a href={metadata.source_url} target="_blank" rel="noreferrer">
          Open arXiv
        </a>
        <a href={metadata.pdf_url} target="_blank" rel="noreferrer">
          Open PDF
        </a>
        {metadata.categories.length ? <span>{metadata.categories.join(" · ")}</span> : null}
      </div>

      <div className="paper-grid">
        <article className="paper-card abstract-card">
          <div className="card-label">Abstract</div>
          <p>{metadata.abstract || "No abstract was provided by arXiv."}</p>
        </article>
        <article className="paper-card">
          <div className="card-label">Sections</div>
          {paper.sections.length ? (
            <ol className="section-list">
              {paper.sections.map((section) => (
                <li key={`${section.order}-${section.title}`}>
                  <h3>{section.title}</h3>
                  <p>{section.text}</p>
                </li>
              ))}
            </ol>
          ) : (
            <p>No sections could be extracted reliably.</p>
          )}
        </article>
      </div>
    </section>
  );
}
