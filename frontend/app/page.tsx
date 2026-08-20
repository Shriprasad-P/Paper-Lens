"use client";

import { useState } from "react";
import type { FormEvent } from "react";

type ParsedSection = { title: string; order: number; text: string };
type DocumentParagraph = {
  id: string;
  order: number;
  text: string;
  page: number | null;
  evidence_id: string | null;
};
type DocumentSection = {
  id: string;
  title: string;
  level: number;
  order: number;
  page_start: number | null;
  page_end: number | null;
  paragraphs: DocumentParagraph[];
};
type StructuredDocument = {
  id: string;
  paper_id: string;
  page_count: number | null;
  parser_name: string;
  parser_version: string | null;
  source_hash: string | null;
  document_hash: string | null;
  created_at: string;
  sections: DocumentSection[];
};
type Evidence = {
  id: string;
  paper_id: string;
  document_id: string;
  evidence_type: string;
  source_text: string;
  page: number | null;
  section_id: string | null;
  paragraph_id: string | null;
  source_region: { page: number; x0: number | null; y0: number | null; x1: number | null; y1: number | null } | null;
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
  const [document, setDocument] = useState<StructuredDocument | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);
    setPaper(null);
    setDocument(null);

    try {
      const ingested = await requestJson<IngestedPaper>("/api/papers/ingest", {
        method: "POST",
        body: JSON.stringify({ source: paperUrl.trim() }),
      });
      const normalized = await requestJson<StructuredDocument>(`/api/papers/${ingested.id}/document`);
      setPaper(ingested);
      setDocument(normalized);
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
            <div className="status-heading">Preparing source document</div>
            <p>Ingesting the arXiv paper, normalizing paragraphs, and registering evidence.</p>
          </div>
        ) : null}

        {error ? (
          <div className="status-card error-card" role="alert">
            <div className="status-heading">PaperLens could not prepare this paper</div>
            <p>{error}</p>
          </div>
        ) : null}
      </section>

      {paper && document ? <PaperView paper={paper} document={document} /> : null}

      <footer>
        <span>Evidence first.</span>
        <span>Unknown stays unknown.</span>
      </footer>
    </main>
  );
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const payload = (await response.json().catch(() => null)) as T | { detail?: string } | null;
  if (!response.ok) {
    throw new Error(payload && typeof payload === "object" && "detail" in payload && payload.detail ? payload.detail : "Request failed.");
  }
  return payload as T;
}

function PaperView({ paper, document }: { paper: IngestedPaper; document: StructuredDocument }) {
  const { metadata } = paper;
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);

  async function openEvidence(evidenceId: string) {
    setEvidenceError(null);
    try {
      setSelectedEvidence(await requestJson<Evidence>(`/api/papers/${paper.id}/evidence/${evidenceId}`));
    } catch (requestError) {
      setEvidenceError(requestError instanceof Error ? requestError.message : "Evidence could not be loaded.");
    }
  }

  return (
    <>
      <section className="paper-view" aria-labelledby="paper-title">
        <div className="paper-meta-row">
          <span className="eyebrow">STRUCTURED DOCUMENT / {metadata.arxiv_id}</span>
          <span className="paper-status">{paper.status}</span>
        </div>
        <h2 id="paper-title">{metadata.title}</h2>
        <p className="authors">{metadata.authors.join(" · ") || "Authors unavailable"}</p>
        <div className="metadata-links">
          <a href={metadata.source_url} target="_blank" rel="noreferrer">Open arXiv</a>
          <a href={metadata.pdf_url} target="_blank" rel="noreferrer">Open PDF</a>
          <span>{document.page_count ?? "Unknown"} pages · {document.sections.length} sections</span>
        </div>

        <div className="paper-grid">
          <article className="paper-card abstract-card">
            <div className="card-label">Abstract</div>
            <p>{metadata.abstract || "No abstract was provided by arXiv."}</p>
            <div className="document-note">Source parser: {document.parser_name}</div>
          </article>
          <article className="paper-card">
            <div className="card-label">Source paragraphs</div>
            <div className="section-list">
              {document.sections.map((section) => (
                <section key={section.id} className="document-section" aria-labelledby={section.id}>
                  <div className="section-heading-row">
                    <h3 id={section.id}>{section.title}</h3>
                    {section.page_start ? <span>p. {section.page_start}</span> : null}
                  </div>
                  {section.paragraphs.map((paragraph) => (
                    <div className="paragraph-row" key={paragraph.id}>
                      <p>{paragraph.text}</p>
                      <div className="paragraph-tools">
                        <span>{paragraph.page ? `p. ${paragraph.page}` : "Page unavailable"}</span>
                        {paragraph.evidence_id ? (
                          <button type="button" className="evidence-button" onClick={() => openEvidence(paragraph.evidence_id as string)}>
                            View Evidence
                          </button>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </section>
              ))}
            </div>
          </article>
        </div>
      </section>

      {evidenceError ? <div className="status-card error-card" role="alert"><p>{evidenceError}</p></div> : null}
      {selectedEvidence ? (
        <div className="drawer-backdrop" role="presentation" onClick={() => setSelectedEvidence(null)}>
          <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-title" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-header">
              <div>
                <div className="card-label">Evidence</div>
                <h3 id="evidence-title">{selectedEvidence.id}</h3>
              </div>
              <button type="button" className="close-button" onClick={() => setSelectedEvidence(null)} aria-label="Close evidence">×</button>
            </div>
            <dl className="evidence-details">
              <div><dt>Type</dt><dd>{selectedEvidence.evidence_type}</dd></div>
              <div><dt>Section</dt><dd>{selectedEvidence.section_id ?? "Unavailable"}</dd></div>
              <div><dt>Page</dt><dd>{selectedEvidence.page ?? "Unavailable"}</dd></div>
              <div><dt>Paragraph</dt><dd>{selectedEvidence.paragraph_id ?? "Unavailable"}</dd></div>
            </dl>
            <div className="source-quote"><div className="card-label">Original Source</div><p>{selectedEvidence.source_text}</p></div>
          </aside>
        </div>
      ) : null}
    </>
  );
}
