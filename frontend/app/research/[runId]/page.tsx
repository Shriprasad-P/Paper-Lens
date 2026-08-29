"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { cancelResearchRun, executeResearchRun, loadEvidence, loadResearchRun } from "../../reader-api";
import type { Evidence, ResearchEvidenceRef, ResearchReportClaim, ResearchRunResponse } from "../../reader-models";

const ACTIVE = new Set(["CREATED", "PLANNING", "DISCOVERING", "SELECTING", "INGESTING", "ANALYZING", "SYNTHESIZING", "VERIFYING"]);

export default function ResearchRunPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const [payload, setPayload] = useState<ResearchRunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedRef, setSelectedRef] = useState<ResearchEvidenceRef | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await loadResearchRun(runId);
      setPayload(next);
      if (next.run.status === "CREATED") {
        await executeResearchRun(runId);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load this research run.");
    }
  }, [runId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function openCitation(ref: ResearchEvidenceRef) {
    setSelectedRef(ref);
    try {
      setEvidence(await loadEvidence(ref.paper_id, ref.evidence_id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Evidence could not be loaded.");
    }
  }

  async function stopRun() {
    try { setPayload(await cancelResearchRun(runId)); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Unable to cancel the run."); }
  }

  const report = payload?.report;
  if (!payload) return <main className="page-shell"><p>{error ?? "Loading research run…"}</p></main>;

  return (
    <main className="page-shell research-run-shell">
      <header className="research-run-header"><div><Link className="back-link" href="/research">← New research question</Link><div className="eyebrow">RESEARCH RUN / {payload.run.id}</div><h1>{payload.run.research_question}</h1></div><div className="run-status" data-status={payload.run.status}>{payload.run.status} · {payload.run.execution_state}</div></header>
      {error ? <div className="status-card error-card" role="alert"><p>{error}</p></div> : null}
      <section className="run-progress"><div className="run-progress-heading"><div><div className="card-label">Observable progress</div><p>{payload.events.at(-1)?.message ?? "Preparing…"}</p></div>{ACTIVE.has(payload.run.status) ? <button className="secondary-button" onClick={stopRun}>Cancel run</button> : null}</div><ol className="event-timeline">{payload.events.slice(-18).map((event) => <li key={event.id}><span>{event.event_type}</span><p>{event.message}</p><time>{new Date(event.created_at).toLocaleTimeString()}</time></li>)}</ol></section>
      <section className="run-stats"><div><strong>{payload.candidates.length}</strong><span>candidates</span></div><div><strong>{payload.candidates.filter((candidate) => candidate.selected).length}</strong><span>selected</span></div><div><strong>{payload.report?.papers.length ?? 0}</strong><span>analyzed</span></div><div><strong>{payload.coverage?.evidence_count ?? 0}</strong><span>evidence records</span></div></section>
      {report ? <ReportView report={report} onCitation={openCitation} /> : <section className="research-empty"><h2>Report will appear here</h2><p>Discovery, ingestion, analysis, and synthesis are persisted as the run advances. Claims stay unverified until their evidence tuple resolves.</p></section>}
      {selectedRef ? <div className="drawer-backdrop" role="presentation" onClick={() => setSelectedRef(null)}><aside className="evidence-drawer" role="dialog" aria-label="Research evidence" onClick={(event) => event.stopPropagation()}><div className="drawer-header"><div><div className="card-label">Evidence registry</div><h3>{selectedRef.evidence_id}</h3></div><button className="close-button" onClick={() => setSelectedRef(null)} aria-label="Close evidence">×</button></div>{evidence ? <><dl className="evidence-details"><div><dt>Paper</dt><dd>{selectedRef.paper_id}</dd></div><div><dt>Document</dt><dd>{selectedRef.document_id}</dd></div><div><dt>Page</dt><dd>{evidence.page ?? "—"}</dd></div></dl><div className="source-quote"><div className="card-label">Source text</div><p>{evidence.source_text}</p></div><Link className="back-link" href={`/papers/${selectedRef.paper_id}`}>Open paper reader →</Link></> : <p>Loading source evidence…</p>}</aside></div> : null}
    </main>
  );
}

function ReportView({ report, onCitation }: { report: NonNullable<ResearchRunResponse["report"]>; onCitation: (ref: ResearchEvidenceRef) => void }) {
  return <section className="research-report"><div className="report-heading"><div><div className="card-label">Evidence-grounded report</div><h2>What the selected literature supports</h2></div><span className="verification-badge">Claims: unverified by default</span></div><div className="report-grid"><ReportClaims title="Executive summary" claims={report.executive_summary} onCitation={onCitation} /><ReportClaims title="Agreements" claims={report.agreements} onCitation={onCitation} /><div className="report-card"><div className="card-label">Methods</div>{report.methods.length ? report.methods.map((method) => <div className="report-item" key={method.paper_id}><strong>{method.paper_id}</strong><p>{method.method}</p><CitationButtons refs={method.evidence_refs} onCitation={onCitation} /></div>) : <p>No persisted method extraction was available.</p>}</div><ReportClaims title="Limitations" claims={report.limitations} onCitation={onCitation} /><div className="report-card"><div className="card-label">Contradictions</div>{report.contradictions.length ? report.contradictions.map((item) => <div className="report-item" key={item.id}><strong>{item.topic} · {item.contradiction_type}</strong><p>{item.explanation}</p><p>{item.claim_a}</p><p>{item.claim_b}</p><CitationButtons refs={[...item.evidence_a, ...item.evidence_b]} onCitation={onCitation} /></div>) : <p>No safe comparable contradiction detected.</p>}</div><div className="report-card"><div className="card-label">Research gaps</div>{report.research_gaps.length ? report.research_gaps.map((gap) => <div className="report-item" key={gap.id}><p>{gap.statement}</p><CitationButtons refs={gap.evidence_refs} onCitation={onCitation} /></div>) : <p>Selected-paper limitations did not support a calibrated gap statement.</p>}</div></div><div className="report-card report-papers"><div className="card-label">Selected papers</div>{report.papers.map((paper) => <div className="report-item" key={paper.paper_id}><Link href={`/papers/${paper.paper_id}`}><strong>{paper.title}</strong></Link><p>{paper.why_selected} · {paper.analysis_status}</p></div>)}</div><details className="report-card"><summary>Search plan and coverage</summary><p>{report.coverage.summary}</p><p>{report.discovery_queries.join(" · ")}</p></details></section>;
}

function ReportClaims({ title, claims, onCitation }: { title: string; claims: ResearchReportClaim[]; onCitation: (ref: ResearchEvidenceRef) => void }) {
  return <div className="report-card"><div className="card-label">{title}</div>{claims.length ? claims.map((claim) => <div className="report-item" key={claim.claim_id}><span className="verification-badge">{claim.origin} · {claim.verification_status}</span><p>{claim.statement}</p><CitationButtons refs={claim.evidence_refs} onCitation={onCitation} /></div>) : <p>No grounded statements were available.</p>}</div>;
}

function CitationButtons({ refs, onCitation }: { refs: ResearchEvidenceRef[]; onCitation: (ref: ResearchEvidenceRef) => void }) {
  return refs.length ? <div className="citation-buttons">{refs.map((ref) => <button className="evidence-button" key={`${ref.paper_id}:${ref.evidence_id}`} onClick={() => onCitation(ref)}>{ref.paper_id} · {ref.evidence_id}</button>)}</div> : <small>No linked evidence</small>;
}
