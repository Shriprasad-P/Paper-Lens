"use client";

import {
  Background,
  Controls,
  ReactFlow,
  type NodeMouseHandler,
} from "@xyflow/react";
import Link from "next/link";
import katex from "katex";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_BASE_URL, loadEvidence } from "../reader-api";
import {
  type Analysis,
  type Evidence,
  type ExtractionState,
  type ExperimentIR,
  type MethodFlowNode,
  type MethodIR,
  methodToFlow,
  type ProblemClaim,
  type ReaderResponse,
  type ResearchClaim,
  type ResultIR,
  type StatementOrigin,
} from "../reader-models";

type ReaderSectionId =
  | "overview"
  | "problem"
  | "gap"
  | "contributions"
  | "method"
  | "equations"
  | "experiments"
  | "results"
  | "limitations"
  | "future-work"
  | "references";

type EvidenceDrawer = {
  title: string;
  requestedIds: string[];
  records: Evidence[];
  loading: boolean;
  error: string | null;
};

type PaperReaderProps = {
  reader: ReaderResponse;
  onAnalyze?: () => Promise<void>;
  analysisError?: string | null;
};

const sectionLabels: Record<ReaderSectionId, string> = {
  overview: "Overview",
  problem: "Problem",
  gap: "Research Gap",
  contributions: "Contributions",
  method: "Method",
  equations: "Equations",
  experiments: "Experiments",
  results: "Results",
  limitations: "Limitations",
  "future-work": "Future Work",
  references: "References",
};

export function PaperReader({ reader, onAnalyze, analysisError }: PaperReaderProps) {
  const [activeSection, setActiveSection] = useState<ReaderSectionId>("overview");
  const [pdfOpen, setPdfOpen] = useState(reader.source.available);
  const [pdfPage, setPdfPage] = useState<number | null>(null);
  const [pdfLoading, setPdfLoading] = useState(reader.source.available);
  const [drawer, setDrawer] = useState<EvidenceDrawer | null>(null);
  const [selectedMethodNode, setSelectedMethodNode] = useState<MethodFlowNode | null>(null);
  const evidenceCache = useRef(new Map<string, Evidence>());

  const analysis = reader.analysis;
  const navigation = useMemo(() => buildNavigation(reader), [reader]);
  const sourceUrl = reader.source.endpoint ? `${API_BASE_URL}${reader.source.endpoint}` : null;

  useEffect(() => {
    const hash = window.location.hash.replace("#", "") as ReaderSectionId;
    if (navigation.some((item) => item.id === hash)) setActiveSection(hash);
  }, [navigation]);

  useEffect(() => {
    if (pdfOpen && sourceUrl) setPdfLoading(true);
  }, [pdfOpen, pdfPage, sourceUrl]);

  const goToSection = useCallback((section: ReaderSectionId) => {
    setActiveSection(section);
    window.history.replaceState(null, "", `#${section}`);
    document.getElementById(section)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const openEvidence = useCallback(
    async (evidenceIds: string[], title: string) => {
      const requestedIds = evidenceIds.filter((id, index, all) => id && all.indexOf(id) === index);
      if (!requestedIds.length) return;
      const cached = requestedIds.flatMap((id) => {
        const record = evidenceCache.current.get(id);
        return record ? [record] : [];
      });
      const missingIds = requestedIds.filter((id) => !evidenceCache.current.has(id));
      setDrawer({ title, requestedIds, records: cached, loading: missingIds.length > 0, error: null });
      const loaded = await Promise.allSettled(missingIds.map((id) => loadEvidence(reader.paper.id, id)));
      const failed = loaded.filter((result) => result.status === "rejected").length;
      loaded.forEach((result) => {
        if (result.status === "fulfilled") evidenceCache.current.set(result.value.id, result.value);
      });
      const records = requestedIds.flatMap((id) => {
        const record = evidenceCache.current.get(id);
        return record ? [record] : [];
      });
      setDrawer({
        title,
        requestedIds,
        records,
        loading: false,
        error: failed ? `${failed} evidence record${failed === 1 ? "" : "s"} could not be loaded.` : null,
      });
      const firstPage = records.find((record) => record.page !== null)?.page;
      if (firstPage !== undefined && firstPage !== null) {
        setPdfPage(firstPage);
        if (reader.source.available) setPdfOpen(true);
      }
    },
    [reader.paper.id, reader.source.available],
  );

  const openPage = useCallback(
    (page: number | null) => {
      if (page === null) return;
      setPdfPage(page);
      if (reader.source.available) setPdfOpen(true);
    },
    [reader.source.available],
  );

  const handleMethodNodeClick: NodeMouseHandler<MethodFlowNode> = useCallback(
    (_event, node) => {
      setSelectedMethodNode(node);
      void openEvidence(node.data.evidenceIds, `Method · ${node.data.label}`);
    },
    [openEvidence],
  );

  return (
    <main className="reader-shell">
      <header className="reader-header">
        <div className="reader-header-copy">
          <Link className="back-link" href="/">← New paper</Link>
          <div className="eyebrow">PAPERLENS / VISUAL READER</div>
          <h1>{reader.paper.metadata.title}</h1>
          <p className="reader-authors">{reader.paper.metadata.authors.join(" · ") || "Authors unavailable"}</p>
          <div className="reader-meta">
            <span>{reader.paper.metadata.arxiv_id}</span>
            <span>{reader.document.page_count ?? "Unknown"} pages</span>
            <span>{reader.document.section_count} sections</span>
            <a href={reader.paper.metadata.source_url} target="_blank" rel="noreferrer">Open arXiv</a>
          </div>
        </div>
        <div className="reader-header-actions">
          <span className="paper-status">{reader.paper.status}</span>
          {sourceUrl ? (
            <button type="button" className="secondary-button" onClick={() => setPdfOpen((open) => !open)}>
              {pdfOpen ? "Hide original" : "Show original"}
            </button>
          ) : null}
        </div>
      </header>

      <div className={`reader-layout${pdfOpen && sourceUrl ? " reader-with-source" : ""}`}>
        <aside className="reader-sidebar" aria-label="Reader sections">
          <div className="sidebar-label">Research story</div>
          <nav>
            {navigation.map((item) => (
              <button
                type="button"
                key={item.id}
                className={`reader-nav-item${activeSection === item.id ? " active" : ""}`}
                aria-current={activeSection === item.id ? "page" : undefined}
                onClick={() => goToSection(item.id)}
              >
                <span>{item.index}</span>
                {item.label}
              </button>
            ))}
          </nav>
          <div className="sidebar-note">
            <strong>Evidence first.</strong>
            <span>Interpretations stay linked to source passages.</span>
          </div>
        </aside>

        <article className="reader-story">
          <ReaderSection id="overview" title="Overview" eyebrow="01 / ORIENTATION">
            <OverviewSection reader={reader} analysis={analysis} onEvidence={openEvidence} onNavigate={goToSection} />
          </ReaderSection>

          {hasSection(navigation, "problem") ? (
            <ReaderSection id="problem" title="Problem" eyebrow="02 / QUESTION">
              <ProblemSection analysis={analysis} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(navigation, "gap") ? (
            <ReaderSection id="gap" title="Research Gap" eyebrow="03 / GAP">
              <ClaimList claims={analysis?.research_gap ?? []} emptyState={analysis?.extraction.research_gap} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(navigation, "contributions") ? (
            <ReaderSection id="contributions" title="Contributions" eyebrow="04 / WHAT THIS PAPER ADDS">
              <ClaimList claims={analysis?.contributions ?? []} emptyState={analysis?.extraction.contributions} onEvidence={openEvidence} numbered />
            </ReaderSection>
          ) : null}
          {hasSection(navigation, "method") ? (
            <ReaderSection id="method" title="Method" eyebrow="05 / HOW IT WORKS">
              <MethodSection method={analysis?.method ?? null} state={analysis?.extraction.method} selectedNodeId={selectedMethodNode?.id ?? null} onEvidence={openEvidence} onNodeClick={handleMethodNodeClick} />
            </ReaderSection>
          ) : null}
          {hasSection(navigation, "equations") ? (
            <ReaderSection id="equations" title="Equations" eyebrow="06 / MATHEMATICAL OBJECTS">
              <EquationSection equations={analysis?.equations ?? []} state={analysis?.extraction.equations} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(navigation, "experiments") ? (
            <ReaderSection id="experiments" title="Experiments" eyebrow="07 / EVALUATION SETUP">
              <ExperimentSection experiments={analysis?.experiments ?? []} state={analysis?.extraction.experiments} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(navigation, "results") ? (
            <ReaderSection id="results" title="Results" eyebrow="08 / FINDINGS">
              <ResultsSection analysis={analysis} specs={reader.visualizations} state={analysis?.extraction.results} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(navigation, "limitations") ? (
            <ReaderSection id="limitations" title="Limitations" eyebrow="09 / BOUNDARIES">
              <ClaimList claims={analysis?.limitations ?? []} emptyState={analysis?.extraction.limitations} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(navigation, "future-work") ? (
            <ReaderSection id="future-work" title="Future Work" eyebrow="10 / WHAT COMES NEXT">
              <ClaimList claims={analysis?.future_work ?? []} emptyState={analysis?.extraction.future_work} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(navigation, "references") ? (
            <ReaderSection id="references" title="References" eyebrow="11 / SOURCES">
              <ReferencesSection references={reader.document.references} />
            </ReaderSection>
          ) : null}

          {analysis ? <ExtractionSummary analysis={analysis} /> : <EmptyAnalysis onAnalyze={onAnalyze} error={analysisError} />}
        </article>

        {pdfOpen && sourceUrl ? (
          <aside className="source-panel" aria-label="Original paper">
            <div className="source-panel-header">
              <div>
                <div className="card-label">Original paper</div>
                <strong>Source PDF</strong>
              </div>
              <button type="button" className="close-source" onClick={() => setPdfOpen(false)} aria-label="Hide original paper">×</button>
            </div>
            <div className="source-page-control">
              <label htmlFor="source-page">Page</label>
              <input
                id="source-page"
                type="number"
                min={1}
                max={reader.source.page_count ?? undefined}
                value={pdfPage ?? ""}
                placeholder="—"
                onChange={(event) => setPdfPage(event.target.value ? Number(event.target.value) : null)}
              />
              <span>of {reader.source.page_count ?? "?"}</span>
            </div>
            {pdfLoading ? <div className="source-loading" aria-live="polite">Loading original paper…</div> : null}
            <iframe
              key={`${sourceUrl}-${pdfPage ?? "document"}`}
              className="source-frame"
              title="Original paper PDF"
              src={`${sourceUrl}${pdfPage ? `#page=${pdfPage}` : ""}`}
              onLoad={() => setPdfLoading(false)}
            />
            <p className="source-panel-note">Page navigation is deterministic. Region highlighting is not enabled until coordinate mapping is reliable.</p>
          </aside>
        ) : null}
      </div>

      {drawer ? (
        <EvidenceDrawerView drawer={drawer} onClose={() => setDrawer(null)} onPage={openPage} />
      ) : null}
    </main>
  );
}

function ReaderSection({ id, title, eyebrow, children }: { id: ReaderSectionId; title: string; eyebrow: string; children: React.ReactNode }) {
  return (
    <section id={id} className="reader-section" aria-labelledby={`${id}-title`}>
      <div className="section-eyebrow">{eyebrow}</div>
      <h2 id={`${id}-title`}>{title}</h2>
      {children}
    </section>
  );
}

function OverviewSection({ reader, analysis, onEvidence, onNavigate }: { reader: ReaderResponse; analysis: Analysis | null; onEvidence: (ids: string[], title: string) => void; onNavigate: (section: ReaderSectionId) => void }) {
  if (!analysis) {
    return (
      <div className="overview-intro">
        <p className="lead-copy">{reader.paper.metadata.abstract || "The source document is ready to inspect."}</p>
        <div className="reader-meta-line"><span>{reader.document.paragraph_count} source paragraphs</span><span>{reader.document.parser_name}</span></div>
        <div className="reader-empty"><span className="status-dot" data-status="UNKNOWN" /><p>This paper has been ingested but has not been analyzed yet.</p></div>
      </div>
    );
  }
  const overviewItems = [
    analysis.problem ? { label: "Research problem", statement: analysis.problem.statement, origin: analysis.problem.origin, evidenceIds: analysis.problem.evidence_ids, section: "problem" as ReaderSectionId } : null,
    analysis.research_gap[0] ? { label: "Research gap", statement: analysis.research_gap[0].statement, origin: analysis.research_gap[0].origin, evidenceIds: analysis.research_gap[0].evidence_ids, section: "gap" as ReaderSectionId } : null,
    analysis.contributions[0] ? { label: "Main contribution", statement: analysis.contributions[0].statement, origin: analysis.contributions[0].origin, evidenceIds: analysis.contributions[0].evidence_ids, section: "contributions" as ReaderSectionId } : null,
    analysis.method ? { label: "Method summary", statement: analysis.method.summary, origin: analysis.method.origin, evidenceIds: analysis.method.evidence_ids, section: "method" as ReaderSectionId } : null,
    analysis.results[0] ? { label: "Main result", statement: analysis.results[0].statement, origin: analysis.results[0].origin, evidenceIds: analysis.results[0].evidence_ids, section: "results" as ReaderSectionId } : null,
  ].filter((item): item is { label: string; statement: string; origin: StatementOrigin; evidenceIds: string[]; section: ReaderSectionId } => item !== null);
  return (
    <div className="overview-grid">
      <div className="overview-intro">
        <p className="lead-copy">{reader.paper.metadata.abstract || "The paper has been ingested and its source provenance is ready to inspect."}</p>
        <div className="reader-meta-line"><span>{reader.document.paragraph_count} source paragraphs</span><span>{reader.document.parser_name}</span><span>{analysis ? "Analysis persisted" : "Analysis unavailable"}</span></div>
      </div>
      <div className="overview-cards">
        {overviewItems.length ? overviewItems.map((item) => (
          <article className="overview-card" key={item.label}>
            <button type="button" className="overview-card-link" onClick={() => onNavigate(item.section)}>
              <span className="card-label">{item.label}</span>
              <p>{item.statement}</p>
            </button>
            <OriginBadge origin={item.origin} />
            <EvidenceButton evidenceIds={item.evidenceIds} title={item.label} onEvidence={onEvidence} />
          </article>
        )) : <EmptyState text="No supported overview statements are available." />}
      </div>
    </div>
  );
}

function ProblemSection({ analysis, onEvidence }: { analysis: Analysis | null; onEvidence: (ids: string[], title: string) => void }) {
  if (!analysis) return <EmptyAnalysis />;
  return (
    <div className="problem-grid">
      <StatementCard title="Research problem" claim={analysis.problem} onEvidence={onEvidence} />
      <StatementCard title="Motivation" claim={analysis.motivation} onEvidence={onEvidence} />
    </div>
  );
}

function StatementCard({ title, claim, onEvidence }: { title: string; claim: (ResearchClaim | ProblemClaim) | null; onEvidence: (ids: string[], title: string) => void }) {
  return (
    <article className="reader-card statement-card">
      <div className="card-label">{title}</div>
      {claim ? (
        <>
          <p className="statement-copy">{claim.statement}</p>
          {"context" in claim && claim.context ? <p className="claim-context">{claim.context}</p> : null}
          <OriginBadge origin={claim.origin} />
          <EvidenceButton evidenceIds={claim.evidence_ids} title={title} onEvidence={onEvidence} />
        </>
      ) : <EmptyState text="Not explicitly identified in the paper." />}
    </article>
  );
}

function ClaimList({ claims, emptyState, onEvidence, numbered = false }: { claims: ResearchClaim[]; emptyState?: ExtractionState; onEvidence: (ids: string[], title: string) => void; numbered?: boolean }) {
  if (!claims.length) return <StatusState state={emptyState} />;
  return (
    <div className="claim-list">
      {claims.map((claim, index) => (
        <article className="claim-item" key={claim.id}>
          {numbered ? <div className="claim-index">{String(index + 1).padStart(2, "0")}</div> : null}
          <div>
            <p className="statement-copy">{claim.statement}</p>
            <OriginBadge origin={claim.origin} />
            <EvidenceButton evidenceIds={claim.evidence_ids} title={claim.statement} onEvidence={onEvidence} />
          </div>
        </article>
      ))}
    </div>
  );
}

function MethodSection({ method, state, selectedNodeId, onEvidence, onNodeClick }: { method: MethodIR | null; state?: ExtractionState; selectedNodeId: string | null; onEvidence: (ids: string[], title: string) => void; onNodeClick: NodeMouseHandler<MethodFlowNode> }) {
  if (!method) return <StatusState state={state} />;
  const flow = methodToFlow(method);
  const graphNodes = flow.nodes.map((node) => ({ ...node, className: node.id === selectedNodeId ? "method-node-selected" : undefined }));
  return (
    <div className="method-section">
      <div className="reader-card method-summary">
        <p className="statement-copy">{method.summary}</p>
        <OriginBadge origin={method.origin} />
        <EvidenceButton evidenceIds={method.evidence_ids} title="Method summary" onEvidence={onEvidence} />
      </div>
      {flow.nodes.length ? (
        <>
          <div className="method-graph" aria-label="Interactive method flow diagram">
            <ReactFlow nodes={graphNodes} edges={flow.edges} fitView fitViewOptions={{ padding: 0.25 }} nodesConnectable={false} nodesDraggable={false} onNodeClick={onNodeClick}>
              <Background color="#d8d8d0" gap={24} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
          <div className="method-selected" aria-live="polite">
            {selectedNodeId ? (
              (() => {
                const step = method.steps.find((item) => item.id === selectedNodeId);
                return step ? <><strong>{step.label}</strong><p>{step.description}</p><OriginBadge origin={step.origin} /><EvidenceButton evidenceIds={step.evidence_ids} title={`Method · ${step.label}`} onEvidence={onEvidence} /></> : null;
              })()
            ) : <p>Select a method node to inspect its source-backed detail.</p>}
          </div>
        </>
      ) : null}
      <details className="method-outline" open={!flow.nodes.length}>
        <summary>Accessible method outline</summary>
        <ol>
          {method.steps.map((step) => <li key={step.id}><strong>{step.label}</strong><span>{step.description}</span></li>)}
        </ol>
      </details>
    </div>
  );
}

function EquationSection({ equations, state, onEvidence }: { equations: Analysis["equations"]; state?: ExtractionState; onEvidence: (ids: string[], title: string) => void }) {
  if (!equations.length) return <StatusState state={state} />;
  return <div className="equation-list">{equations.map((equation) => <EquationCard key={equation.id} equation={equation} onEvidence={onEvidence} />)}</div>;
}

function EquationCard({ equation, onEvidence }: { equation: Analysis["equations"][number]; onEvidence: (ids: string[], title: string) => void }) {
  const explanation = equation.explanation ?? equation.interpretation;
  const rendered = useMemo(() => {
    try {
      return katex.renderToString(equation.expression, { displayMode: true, throwOnError: true, trust: false });
    } catch {
      return null;
    }
  }, [equation.expression]);
  return (
    <article className="reader-card equation-card">
      <div className="card-label">{equation.equation_id || "Equation"}</div>
      {rendered ? <div className="equation-rendered" dangerouslySetInnerHTML={{ __html: rendered }} /> : <pre className="equation-fallback">{equation.expression}</pre>}
      {explanation ? <p className="claim-context">{explanation}</p> : <p className="claim-context">No interpretation was explicitly provided.</p>}
      {equation.variables.length ? <dl className="variable-list">{equation.variables.map((variable) => <div key={variable.symbol}><dt>{variable.symbol}</dt><dd>{variable.meaning || "Not explicitly defined in the paper."}</dd></div>)}</dl> : null}
      {equation.role ? <p className="claim-context"><strong>Role:</strong> {equation.role}</p> : null}
      <OriginBadge origin={equation.origin} />
      <EvidenceButton evidenceIds={equation.evidence_ids} title="Equation" onEvidence={onEvidence} />
    </article>
  );
}

function ExperimentSection({ experiments, state, onEvidence }: { experiments: ExperimentIR[]; state?: ExtractionState; onEvidence: (ids: string[], title: string) => void }) {
  if (!experiments.length) return <StatusState state={state} />;
  return <div className="experiment-grid">{experiments.map((experiment) => <ExperimentCard key={experiment.id} experiment={experiment} onEvidence={onEvidence} />)}</div>;
}

function ExperimentCard({ experiment, onEvidence }: { experiment: ExperimentIR; onEvidence: (ids: string[], title: string) => void }) {
  const fields = [
    ["Datasets", experiment.datasets],
    ["Models", experiment.models],
    ["Baselines", experiment.baselines],
    ["Metrics", experiment.metrics],
  ].filter((entry): entry is [string, string[]] => entry[1].length > 0);
  return (
    <article className="reader-card experiment-card">
      <div className="card-label">{experiment.name || "Experiment"}</div>
      {fields.length ? <dl className="experiment-fields">{fields.map(([label, values]) => <div key={label}><dt>{label}</dt><dd>{values.join(" · ")}</dd></div>)}</dl> : <EmptyState text="No experimental fields were explicitly identified." />}
      {experiment.setup ? <p className="claim-context">{experiment.setup}</p> : null}
      <OriginBadge origin={experiment.origin} />
      <EvidenceButton evidenceIds={experiment.evidence_ids} title={experiment.name || "Experiment"} onEvidence={onEvidence} />
    </article>
  );
}

function ResultsSection({ analysis, specs, state, onEvidence }: { analysis: Analysis | null; specs: ReaderResponse["visualizations"]; state?: ExtractionState; onEvidence: (ids: string[], title: string) => void }) {
  if (!analysis?.results.length) return <StatusState state={state} />;
  const chartSpec = specs.find((spec) => spec.type === "BAR_CHART" || spec.type === "METRIC");
  const numericRows = analysis.results.filter((result): result is ResultIR & { value: number } => typeof result.value === "number" && Number.isFinite(result.value));
  return (
    <div className="results-section">
      {chartSpec?.type === "BAR_CHART" && numericRows.length > 1 ? (
        <div className="reader-card chart-card">
          <div className="card-label">{chartSpec.title}</div>
          <div className="chart-wrap" role="img" aria-label="Bar chart of reported numeric results">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={numericRows.map((result) => ({ label: result.comparison_target || result.id, value: result.value }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="#d8d8d0" />
                <XAxis dataKey="label" tick={{ fill: "#64716d", fontSize: 11 }} />
                <YAxis tick={{ fill: "#64716d", fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="value" fill="#d65b3f" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="chart-caption">Numeric values are plotted without percentage conversion or rounding.</p>
        </div>
      ) : chartSpec?.type === "METRIC" && numericRows.length === 1 ? (
        <div className="reader-card metric-card"><div className="card-label">{chartSpec.title}</div><strong>{numericRows[0].value}{numericRows[0].unit ? ` ${numericRows[0].unit}` : ""}</strong><p>{numericRows[0].statement}</p></div>
      ) : null}
      <div className="result-list">
        {analysis.results.map((result) => (
          <article className="result-row" key={result.id}>
            <div><span className="result-metric">{result.metric || "Reported result"}</span><p>{result.statement}</p></div>
            <div className="result-value">{result.value !== null ? `${result.value}${result.unit ? ` ${result.unit}` : ""}` : "Value unavailable"}</div>
            <div><OriginBadge origin={result.origin} /><EvidenceButton evidenceIds={result.evidence_ids} title={result.metric || "Result"} onEvidence={onEvidence} /></div>
          </article>
        ))}
      </div>
    </div>
  );
}

function ReferencesSection({ references }: { references: ReaderResponse["document"]["references"] }) {
  return (
    <div className="reference-list">
      {references.map((reference) => (
        <article className="reference-item" key={reference.id}>
          <span className="reference-index">[{reference.order + 1}]</span>
          <div><strong>{reference.title || "Parsed reference"}</strong><p>{reference.authors?.join(", ") || reference.raw_text}</p>{reference.year ? <small>{reference.year}</small> : null}</div>
        </article>
      ))}
    </div>
  );
}

function EvidenceButton({ evidenceIds, title, onEvidence }: { evidenceIds: string[]; title: string; onEvidence: (ids: string[], title: string) => void }) {
  if (!evidenceIds.length) return null;
  return <button type="button" className="evidence-button" aria-label={`View evidence for ${title}`} onClick={() => void onEvidence(evidenceIds, title)}>View Evidence{evidenceIds.length > 1 ? ` (${evidenceIds.length})` : ""}</button>;
}

function EvidenceDrawerView({ drawer, onClose, onPage }: { drawer: EvidenceDrawer; onClose: () => void; onPage: (page: number | null) => void }) {
  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <aside className="evidence-drawer reader-drawer" role="dialog" aria-modal="true" aria-labelledby="reader-evidence-title" onClick={(event) => event.stopPropagation()}>
        <div className="drawer-header"><div><div className="card-label">Evidence / {drawer.requestedIds.length} linked</div><h2 id="reader-evidence-title">{drawer.title}</h2></div><button type="button" className="close-button" onClick={onClose} aria-label="Close evidence">×</button></div>
        {drawer.loading ? <p className="drawer-loading" aria-live="polite">Loading source passages…</p> : null}
        {drawer.error ? <p className="drawer-error" role="alert">{drawer.error}</p> : null}
        <div className="drawer-records">
          {drawer.records.map((record, index) => (
            <article className="drawer-record" key={record.id}>
              <div className="drawer-record-meta"><strong>Evidence {index + 1}</strong><span>{record.id}</span></div>
              <div className="drawer-location"><span>{record.section_id || "Section unavailable"}</span>{record.page !== null ? <button type="button" onClick={() => onPage(record.page)}>p. {record.page}</button> : <span>Page unavailable</span>}<span>{record.evidence_type}</span></div>
              <p>{record.source_text}</p>
              {record.source_region ? <small>Source coordinates preserved for future highlighting.</small> : null}
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}

function OriginBadge({ origin }: { origin: StatementOrigin }) {
  return <span className={`origin-badge ${origin === "AUTHOR_EXPLICIT" ? "origin-explicit" : "origin-inferred"}`}>{origin === "AUTHOR_EXPLICIT" ? "Explicit in paper" : "PaperLens interpretation"}</span>;
}

function StatusState({ state }: { state?: ExtractionState }) {
  const message = state?.status === "FAILED" ? "This component could not be extracted." : state?.status === "NO_EVIDENCE" ? "Not explicitly identified in the paper." : "This section is not available yet.";
  return <div className="reader-empty"><span className="status-dot" data-status={state?.status || "UNKNOWN"} /><p>{message}</p></div>;
}

function EmptyState({ text }: { text: string }) {
  return <p className="reader-empty-copy">{text}</p>;
}

function EmptyAnalysis({ onAnalyze, error }: { onAnalyze?: () => Promise<void>; error?: string | null } = {}) {
  const [loading, setLoading] = useState(false);
  async function handleAnalyze() {
    if (!onAnalyze) return;
    setLoading(true);
    try {
      await onAnalyze();
    } finally {
      setLoading(false);
    }
  }
  return <div className="reader-card empty-analysis"><div className="card-label">Analysis</div><h3>This paper has been ingested but has not been analyzed yet.</h3><p>Generate the persisted evidence-grounded PaperIR to populate the visual story.</p>{error ? <p className="drawer-error" role="alert">{error}</p> : null}{onAnalyze ? <button type="button" onClick={() => void handleAnalyze()} disabled={loading}>{loading ? "Analyzing…" : "Analyze paper"}</button> : null}</div>;
}

function ExtractionSummary({ analysis }: { analysis: Analysis }) {
  return <div className="extraction-summary reader-summary">{Object.entries(analysis.extraction).map(([name, state]) => <span key={name} data-status={state.status}>{name}: {state.status}</span>)}</div>;
}

function buildNavigation(reader: ReaderResponse): { id: ReaderSectionId; label: string; index: string }[] {
  const analysis = reader.analysis;
  const available: ReaderSectionId[] = ["overview"];
  if (analysis?.problem || analysis?.motivation) available.push("problem");
  if (analysis?.research_gap.length) available.push("gap");
  if (analysis?.contributions.length) available.push("contributions");
  if (analysis?.method) available.push("method");
  if (analysis?.equations.length) available.push("equations");
  if (analysis?.experiments.length) available.push("experiments");
  if (analysis?.results.length) available.push("results");
  if (analysis?.limitations.length) available.push("limitations");
  if (analysis?.future_work.length) available.push("future-work");
  if (reader.document.references.length > 0) available.push("references");
  return available.map((id, index) => ({ id, label: sectionLabels[id], index: String(index + 1).padStart(2, "0") }));
}

function hasSection(navigation: { id: ReaderSectionId }[], id: ReaderSectionId): boolean {
  return navigation.some((item) => item.id === id);
}
