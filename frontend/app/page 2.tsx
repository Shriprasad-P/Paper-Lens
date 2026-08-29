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
type ExtractionState = { status: string; error: string | null };
type ResearchClaim = { id: string; statement: string; evidence_ids: string[]; origin: string; confidence: number | null };
type Analysis = {
  problem: { id: string; statement: string; context: string | null; evidence_ids: string[]; origin: string; confidence: number | null } | null;
  motivation: ResearchClaim | null;
  research_gap: ResearchClaim[];
  contributions: ResearchClaim[];
  method: { summary: string; evidence_ids: string[]; origin: string; steps: { id: string; label: string; description: string; evidence_ids: string[]; origin: string }[] } | null;
  equations: { id: string; expression: string; explanation: string | null; interpretation: string | null; evidence_ids: string[]; origin: string }[];
  experiments: { id: string; name: string | null; datasets: string[]; models: string[]; baselines: string[]; metrics: string[]; setup: string | null; evidence_ids: string[]; origin: string }[];
  results: { id: string; statement: string; metric: string | null; value: number | string | null; evidence_ids: string[]; origin: string }[];
  limitations: ResearchClaim[];
  future_work: ResearchClaim[];
  extraction: Record<string, ExtractionState>;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HomePage() {
  const [paperUrl, setPaperUrl] = useState("");
  const [paper, setPaper] = useState<IngestedPaper | null>(null);
  const [document, setDocument] = useState<StructuredDocument | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);
    setPaper(null);
    setDocument(null);
    setAnalysis(null);

    try {
      const ingested = await requestJson<IngestedPaper>("/api/papers/ingest", {
        method: "POST",
        body: JSON.stringify({ source: paperUrl.trim() }),
      });
      const normalized = await requestJson<StructuredDocument>(`/api/papers/${ingested.id}/document`);
      const extracted = await requestJson<Analysis>(`/api/papers/${ingested.id}/extract`, { method: "POST" });
      setPaper(ingested);
      setDocument(normalized);
      setAnalysis(extracted);
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

      {paper && document && analysis ? <PaperView paper={paper} document={document} analysis={analysis} /> : null}

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

function PaperView({ paper, document, analysis }: { paper: IngestedPaper; document: StructuredDocument; analysis: Analysis }) {
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
        <AnalysisView analysis={analysis} onEvidence={openEvidence} />
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

function AnalysisView({ analysis, onEvidence }: { analysis: Analysis; onEvidence: (evidenceId: string) => void }) {
  const completed = Object.values(analysis.extraction).filter((state) => state.status === "COMPLETED").length;
  return (
    <section className="analysis-view" aria-labelledby="analysis-title">
      <div className="analysis-header">
        <div>
          <div className="eyebrow">PAPERLENS INTERPRETATION</div>
          <h3 id="analysis-title">Research extraction</h3>
        </div>
        <span className="paper-status">{completed} / {Object.keys(analysis.extraction).length} stages</span>
      </div>
      <p className="analysis-note">Semantic statements are labeled by origin and remain linked to paper evidence.</p>

      <ClaimCard title="Research Problem" claim={analysis.problem} onEvidence={onEvidence} missing="Not explicitly identified in the paper." />
      <ClaimCard title="Motivation" claim={analysis.motivation} onEvidence={onEvidence} missing="Not explicitly identified in the paper." />
      <ClaimList title="Research Gap" claims={analysis.research_gap} onEvidence={onEvidence} />
      <ClaimList title="Contributions" claims={analysis.contributions} onEvidence={onEvidence} />

      {analysis.method ? (
        <article className="analysis-card">
          <div className="card-label">Method</div>
          <p>{analysis.method.summary}</p>
          <OriginBadge origin={analysis.method.origin} />
          <div className="method-steps">
            {analysis.method.steps.map((step) => (
              <div key={step.id} className="method-step">
                <strong>{step.label}</strong>
                <span>{step.description}</span>
                <EvidenceButton evidenceIds={step.evidence_ids} onEvidence={onEvidence} />
              </div>
            ))}
          </div>
          <EvidenceButton evidenceIds={analysis.method.evidence_ids} onEvidence={onEvidence} />
        </article>
      ) : <ExtractionStatusCard title="Method" state={analysis.extraction.method} />}

      <article className="analysis-card compact-analysis">
        <div className="card-label">Equations</div>
        {analysis.equations.length ? analysis.equations.map((equation) => (
          <div key={equation.id} className="equation-row">
            <code>{equation.expression}</code>
            {(equation.explanation ?? equation.interpretation) ? <span>{equation.explanation ?? equation.interpretation}</span> : null}
            <OriginBadge origin={equation.origin} />
            <EvidenceButton evidenceIds={equation.evidence_ids} onEvidence={onEvidence} />
          </div>
        )) : <ExtractionStatusCard title="Equations" state={analysis.extraction.equations} nested />}
      </article>

      <ClaimList title="Limitations" claims={analysis.limitations} onEvidence={onEvidence} state={analysis.extraction.limitations} />
      <ClaimList title="Future Work" claims={analysis.future_work} onEvidence={onEvidence} state={analysis.extraction.future_work} />

      <article className="analysis-card compact-analysis">
        <div className="card-label">Experiments & Results</div>
        {analysis.experiments.length ? analysis.experiments.map((experiment) => (
          <div key={experiment.id} className="experiment-row">
            <strong>{experiment.name || "Experiment"}</strong>
            <span>{experiment.datasets.join(" · ") || "Dataset not explicitly identified"}</span>
            <EvidenceButton evidenceIds={experiment.evidence_ids} onEvidence={onEvidence} />
          </div>
        )) : <ExtractionStatusCard title="Experiments" state={analysis.extraction.experiments} nested />}
        {analysis.results.length ? analysis.results.map((result) => (
          <div key={result.id} className="experiment-row">
            <strong>{result.metric || "Result"}</strong>
            <span>{result.statement}{result.value !== null ? ` (${result.value})` : ""}</span>
            <EvidenceButton evidenceIds={result.evidence_ids} onEvidence={onEvidence} />
          </div>
        )) : <ExtractionStatusCard title="Results" state={analysis.extraction.results} nested />}
      </article>

      <ExtractionSummary analysis={analysis} />
    </section>
  );
}

function ClaimCard({ title, claim, onEvidence, missing }: { title: string; claim: ResearchClaim | Analysis["problem"]; onEvidence: (evidenceId: string) => void; missing: string }) {
  return claim ? (
    <article className="analysis-card">
      <div className="card-label">{title}</div>
      <p>{claim.statement}</p>
      <OriginBadge origin={claim.origin} />
      {"context" in claim && claim.context ? <p className="claim-context">{claim.context}</p> : null}
      <EvidenceButton evidenceIds={claim.evidence_ids} onEvidence={onEvidence} />
    </article>
  ) : <ExtractionStatusCard title={title} state={undefined} missing={missing} />;
}

function ClaimList({ title, claims, onEvidence, state }: { title: string; claims: ResearchClaim[]; onEvidence: (evidenceId: string) => void; state?: ExtractionState }) {
  return (
    <article className="analysis-card">
      <div className="card-label">{title}</div>
      {claims.length ? claims.map((claim) => (
        <div key={claim.id} className="claim-row">
          <p>{claim.statement}</p>
          <OriginBadge origin={claim.origin} />
          <EvidenceButton evidenceIds={claim.evidence_ids} onEvidence={onEvidence} />
        </div>
      )) : <ExtractionStatusCard title={title} state={state} nested />}
    </article>
  );
}

function ExtractionStatusCard({ title, state, missing, nested = false }: { title: string; state?: ExtractionState; missing?: string; nested?: boolean }) {
  const message = state?.status === "FAILED" ? "Extraction failed for this component." : state?.status === "NO_EVIDENCE" ? "Not explicitly identified in the paper." : missing ?? "Not extracted.";
  return <div className={nested ? "extraction-status nested-status" : "analysis-card"}><div className="card-label">{title}</div><p>{message}</p></div>;
}

function EvidenceButton({ evidenceIds, onEvidence }: { evidenceIds: string[]; onEvidence: (evidenceId: string) => void }) {
  const first = evidenceIds[0];
  return first ? <button type="button" className="evidence-button" onClick={() => onEvidence(first)}>View Evidence{evidenceIds.length > 1 ? ` (${evidenceIds.length})` : ""}</button> : null;
}

function OriginBadge({ origin }: { origin: string }) {
  return <span className="origin-badge">{origin === "AUTHOR_EXPLICIT" ? "Explicit in paper" : "PaperLens interpretation"}</span>;
}

function ExtractionSummary({ analysis }: { analysis: Analysis }) {
  return <div className="extraction-summary">{Object.entries(analysis.extraction).map(([name, state]) => <span key={name} data-status={state.status}>{name}: {state.status}</span>)}</div>;
}
