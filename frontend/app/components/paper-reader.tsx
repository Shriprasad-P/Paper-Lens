"use client";
/* eslint-disable @next/next/no-img-element */

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

import { apiUrl, createChatSession, loadChatSession, loadEvidence, sendChatMessage } from "../reader-api";
import {
  type Analysis,
  type ClaimVerification,
  type ChatMessage,
  type ChatSession,
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
  type VerificationStatus,
  documentSectionsToFlow,
} from "../reader-models";
import { InteractivePaperView } from "./interactive-paper";
import type { ChatFocus } from "../interactive-models";

type ReaderSectionId = string;

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
  onVerify?: () => Promise<void>;
  verificationError?: string | null;
};

type VerificationLookup = Map<string, ClaimVerification>;

const sectionLabels: Record<string, string> = {
  overview: "Overview",
  visualize: "Visualize",
  problem: "Problem",
  gap: "Research Gap",
  contributions: "Contributions",
  method: "Method",
  equations: "Equations",
  experiments: "Experiments",
  results: "Results",
  figures: "Figures",
  tables: "Tables",
  limitations: "Limitations",
  "future-work": "Future Work",
  references: "References",
};

export function PaperReader({ reader, onAnalyze, analysisError, onVerify, verificationError }: PaperReaderProps) {
  const [activeSection, setActiveSection] = useState<ReaderSectionId>("overview");
  const [pdfOpen, setPdfOpen] = useState(false);
  const [pdfPage, setPdfPage] = useState<number | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [drawer, setDrawer] = useState<EvidenceDrawer | null>(null);
  const [selectedMethodNode, setSelectedMethodNode] = useState<MethodFlowNode | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatSession, setChatSession] = useState<ChatSession | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatSending, setChatSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [chatFocus, setChatFocus] = useState<ChatFocus | null>(null);
  const [outlineOpen, setOutlineOpen] = useState(false);
  const evidenceCache = useRef(new Map<string, Evidence>());

  const analysis = reader.analysis;
  const navigation = useMemo(() => buildNavigation(reader), [reader]);
  const legacyNavigation = useMemo(() => buildLegacyNavigation(reader), [reader]);
  const verificationByClaim = useMemo(
    () => new Map((reader.verification?.results ?? []).map((result) => [result.claim_id, result])),
    [reader.verification],
  );
  const sourceUrl = reader.source.endpoint ? apiUrl(reader.source.endpoint) : null;

  useEffect(() => {
    const hash = window.location.hash.replace("#", "") as ReaderSectionId;
    if (navigation.some((item) => item.id === hash)) setActiveSection(hash);
  }, [navigation]);

  useEffect(() => {
    if (reader.source.available && window.matchMedia("(min-width: 761px)").matches) setPdfOpen(true);
  }, [reader.source.available]);

  useEffect(() => {
    if (pdfOpen && sourceUrl) setPdfLoading(true);
  }, [pdfOpen, pdfPage, sourceUrl]);

  useEffect(() => {
    if (reader.source.available && window.matchMedia("(min-width: 761px)").matches) setPdfOpen(true);
  }, [reader.source.available]);

  const goToSection = useCallback((section: string) => {
    setActiveSection(section);
    setOutlineOpen(false);
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

  const ensureChatSession = useCallback(async () => {
    if (chatSession) return chatSession;
    setChatLoading(true);
    setChatError(null);
    try {
      const session = await createChatSession(reader.paper.id);
      const loaded = await loadChatSession(reader.paper.id, session.id);
      setChatSession(loaded.session);
      setChatMessages(loaded.messages);
      return loaded.session;
    } catch (requestError) {
      setChatError(requestError instanceof Error ? requestError.message : "Paper Chat could not be opened.");
      return null;
    } finally {
      setChatLoading(false);
    }
  }, [chatSession, reader.paper.id]);

  const startNewChat = useCallback(async () => {
    setChatSession(null);
    setChatMessages([]);
    setChatLoading(true);
    setChatError(null);
    try {
      const session = await createChatSession(reader.paper.id);
      const loaded = await loadChatSession(reader.paper.id, session.id);
      setChatSession(loaded.session);
      setChatMessages(loaded.messages);
    } catch (requestError) {
      setChatError(requestError instanceof Error ? requestError.message : "A new chat could not be created.");
    } finally {
      setChatLoading(false);
    }
  }, [reader.paper.id]);

  const submitChat = useCallback(async (question: string) => {
    const session = await ensureChatSession();
    if (!session || !question.trim()) return;
    const focused = chatFocus
      ? `Regarding "${chatFocus.title}"${chatFocus.evidenceIds.length ? ` (evidence ${chatFocus.evidenceIds.slice(0, 6).join(", ")})` : ""}: ${question}`
      : question;
    setChatSending(true);
    setChatError(null);
    try {
      await sendChatMessage(reader.paper.id, session.id, focused);
      const loaded = await loadChatSession(reader.paper.id, session.id);
      setChatSession(loaded.session);
      setChatMessages(loaded.messages);
    } catch (requestError) {
      try {
        const loaded = await loadChatSession(reader.paper.id, session.id);
        setChatSession(loaded.session);
        setChatMessages(loaded.messages);
      } catch {
        // Keep the original, user-facing request error if history is unavailable too.
      }
      setChatError(requestError instanceof Error ? requestError.message : "The grounded answer could not be generated.");
    } finally {
      setChatSending(false);
    }
  }, [ensureChatSession, reader.paper.id, chatFocus]);

  useEffect(() => {
    if (chatOpen && !chatSession && !chatLoading) void ensureChatSession();
  }, [chatOpen, chatLoading, chatSession, ensureChatSession]);

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
          {reader.capabilities?.ai_analysis_enabled === false ? <span className="beta-unavailable">AI features unavailable</span> : <button type="button" className="secondary-button" onClick={() => setChatOpen((open) => !open)} aria-expanded={chatOpen}>
            {chatOpen ? "Hide PaperLens" : "Ask PaperLens"}
          </button>}
          {sourceUrl ? (
            <button type="button" className="secondary-button" onClick={() => setPdfOpen((open) => !open)}>
              {pdfOpen ? "Hide original" : "Show original"}
            </button>
          ) : null}
        </div>
      </header>

      <div className={`reader-layout${pdfOpen && sourceUrl ? " reader-with-source" : ""}`}>
        <aside className={`reader-sidebar${outlineOpen ? " open" : ""}`} aria-label="Paper outline">
          <button type="button" className="reader-outline-toggle" aria-expanded={outlineOpen} onClick={() => setOutlineOpen((open) => !open)}>
            {outlineOpen ? "Hide outline" : "Show outline"}
          </button>
          <div className="sidebar-label">{reader.interactive_paper?.blocks.length ? "Paper outline" : "Research story"}</div>
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
          {reader.interactive_paper?.blocks.some((block) => block.status !== "FAILED") ? (
            <InteractivePaperView
              paper={reader.interactive_paper}
              reader={reader}
              onEvidence={openEvidence}
              onPage={openPage}
              onAsk={(focus) => {
                setChatFocus(focus);
                setChatOpen(true);
              }}
            />
          ) : null}

          <details className="source-analysis" open={!reader.interactive_paper?.blocks.length}>
            <summary>Source analysis</summary>
          <ReaderSection id="overview" title="Overview" eyebrow="01 / ORIENTATION">
            <OverviewSection reader={reader} analysis={analysis} verification={verificationByClaim} onEvidence={openEvidence} onNavigate={goToSection} />
          </ReaderSection>

          <ReaderSection id="visualize" title="Visualize" eyebrow="02 / PAPER MAP">
            <VisualizationBoard reader={reader} analysis={analysis} verification={verificationByClaim} selectedMethodNodeId={selectedMethodNode?.id ?? null} onEvidence={openEvidence} onNodeClick={handleMethodNodeClick} onPage={openPage} />
          </ReaderSection>

          {hasSection(legacyNavigation, "problem") ? (
            <ReaderSection id="problem" title="Problem" eyebrow="03 / QUESTION">
              <ProblemSection analysis={analysis} verification={verificationByClaim} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(legacyNavigation, "gap") ? (
            <ReaderSection id="gap" title="Research Gap" eyebrow="04 / GAP">
              <ClaimList claims={analysis?.research_gap ?? []} emptyState={analysis?.extraction.research_gap} verification={verificationByClaim} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(legacyNavigation, "contributions") ? (
            <ReaderSection id="contributions" title="Contributions" eyebrow="05 / WHAT THIS PAPER ADDS">
              <ClaimList claims={analysis?.contributions ?? []} emptyState={analysis?.extraction.contributions} verification={verificationByClaim} onEvidence={openEvidence} numbered />
            </ReaderSection>
          ) : null}
          {hasSection(legacyNavigation, "method") ? (
            <ReaderSection id="method" title="Method" eyebrow="06 / HOW IT WORKS">
              <MethodSection method={analysis?.method ?? null} state={analysis?.extraction.method} verification={verificationByClaim} selectedNodeId={selectedMethodNode?.id ?? null} onEvidence={openEvidence} onNodeClick={handleMethodNodeClick} />
            </ReaderSection>
          ) : null}
          {hasSection(legacyNavigation, "equations") ? (
            <ReaderSection id="equations" title="Equations" eyebrow="07 / MATHEMATICAL OBJECTS">
              <EquationSection equations={analysis?.equations ?? []} sourceEquations={reader.document.equations} state={analysis?.extraction.equations} verification={verificationByClaim} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(legacyNavigation, "experiments") ? (
            <ReaderSection id="experiments" title="Experiments" eyebrow="08 / EVALUATION SETUP">
              <ExperimentSection experiments={analysis?.experiments ?? []} state={analysis?.extraction.experiments} verification={verificationByClaim} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(legacyNavigation, "results") ? (
            <ReaderSection id="results" title="Results" eyebrow="09 / FINDINGS">
              <ResultsSection analysis={analysis} specs={reader.visualizations} state={analysis?.extraction.results} verification={verificationByClaim} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(legacyNavigation, "figures") ? (
            <ReaderSection id="figures" title="Figures" eyebrow="10 / VISUAL EVIDENCE">
              <FiguresSection figures={reader.document.figures} paperId={reader.paper.id} documentId={reader.document.id} onEvidence={openEvidence} onPage={openPage} />
            </ReaderSection>
          ) : null}
          {hasSection(legacyNavigation, "tables") ? (
            <ReaderSection id="tables" title="Tables" eyebrow="11 / STRUCTURED RESULTS">
              <TablesSection tables={reader.document.tables} onEvidence={openEvidence} onPage={openPage} />
            </ReaderSection>
          ) : null}
          {hasSection(legacyNavigation, "limitations") ? (
            <ReaderSection id="limitations" title="Limitations" eyebrow="12 / BOUNDARIES">
              <ClaimList claims={analysis?.limitations ?? []} emptyState={analysis?.extraction.limitations} verification={verificationByClaim} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(legacyNavigation, "future-work") ? (
            <ReaderSection id="future-work" title="Future Work" eyebrow="13 / WHAT COMES NEXT">
              <ClaimList claims={analysis?.future_work ?? []} emptyState={analysis?.extraction.future_work} verification={verificationByClaim} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}
          {hasSection(legacyNavigation, "references") ? (
            <ReaderSection id="references" title="References" eyebrow="14 / SOURCES">
              <ReferencesSection references={reader.document.references} onEvidence={openEvidence} />
            </ReaderSection>
          ) : null}

          {analysis ? <><VerificationSummaryCard verification={reader.verification} onVerify={onVerify} error={verificationError} /><ExtractionSummary analysis={analysis} /></> : <EmptyAnalysis onAnalyze={onAnalyze} error={analysisError} />}
          </details>
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
      {chatOpen ? (
        <ChatPanel
          messages={chatMessages}
          loading={chatLoading}
          sending={chatSending}
          error={chatError}
          focus={chatFocus}
          onClearFocus={() => setChatFocus(null)}
          onClose={() => setChatOpen(false)}
          onNewChat={() => void startNewChat()}
          onSend={(question) => void submitChat(question)}
          onCitation={(citation) => void openEvidence([citation.evidence_id], `Paper Chat citation · ${citation.evidence_id}`)}
        />
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

function OverviewSection({ reader, analysis, verification, onEvidence, onNavigate }: { reader: ReaderResponse; analysis: Analysis | null; verification: VerificationLookup; onEvidence: (ids: string[], title: string) => void; onNavigate: (section: ReaderSectionId) => void }) {
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
    analysis.problem ? { claimId: analysis.problem.id, label: "Research problem", statement: analysis.problem.statement, origin: analysis.problem.origin, evidenceIds: analysis.problem.evidence_ids, section: "problem" as ReaderSectionId } : null,
    analysis.research_gap[0] ? { claimId: analysis.research_gap[0].id, label: "Research gap", statement: analysis.research_gap[0].statement, origin: analysis.research_gap[0].origin, evidenceIds: analysis.research_gap[0].evidence_ids, section: "gap" as ReaderSectionId } : null,
    analysis.contributions[0] ? { claimId: analysis.contributions[0].id, label: "Main contribution", statement: analysis.contributions[0].statement, origin: analysis.contributions[0].origin, evidenceIds: analysis.contributions[0].evidence_ids, section: "contributions" as ReaderSectionId } : null,
    analysis.method ? { claimId: "method_001", label: "Method summary", statement: analysis.method.summary, origin: analysis.method.origin, evidenceIds: analysis.method.evidence_ids, section: "method" as ReaderSectionId } : null,
    analysis.results[0] ? { claimId: analysis.results[0].id, label: "Main result", statement: analysis.results[0].statement, origin: analysis.results[0].origin, evidenceIds: analysis.results[0].evidence_ids, section: "results" as ReaderSectionId } : null,
  ].filter((item): item is { claimId: string; label: string; statement: string; origin: StatementOrigin; evidenceIds: string[]; section: ReaderSectionId } => item !== null)
    .filter((item) => {
      const status = verification.get(item.claimId)?.status;
      return !status || status === "SUPPORTED" || status === "PARTIALLY_SUPPORTED";
    });
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
            <div className="claim-badges"><OriginBadge origin={item.origin} /><VerificationBadge verification={verification.get(item.claimId)} /></div>
            <EvidenceButton evidenceIds={item.evidenceIds} title={item.label} onEvidence={onEvidence} />
          </article>
        )) : <EmptyState text="No supported overview statements are available." />}
      </div>
    </div>
  );
}

function ProblemSection({ analysis, verification, onEvidence }: { analysis: Analysis | null; verification: VerificationLookup; onEvidence: (ids: string[], title: string) => void }) {
  if (!analysis) return <EmptyAnalysis />;
  return (
    <div className="problem-grid">
      <StatementCard title="Research problem" claim={analysis.problem} verification={analysis.problem ? verification.get(analysis.problem.id) : undefined} onEvidence={onEvidence} />
      <StatementCard title="Motivation" claim={analysis.motivation} verification={analysis.motivation ? verification.get(analysis.motivation.id) : undefined} onEvidence={onEvidence} />
    </div>
  );
}

function StatementCard({ title, claim, verification, onEvidence }: { title: string; claim: (ResearchClaim | ProblemClaim) | null; verification?: ClaimVerification; onEvidence: (ids: string[], title: string) => void }) {
  return (
    <article className={`reader-card statement-card${verificationTone(verification?.status)}`}>
      <div className="card-label">{title}</div>
      {claim ? (
        <>
          <p className="statement-copy">{claim.statement}</p>
          {"context" in claim && claim.context ? <p className="claim-context">{claim.context}</p> : null}
          <div className="claim-badges"><OriginBadge origin={claim.origin} /><VerificationBadge verification={verification} /></div>
          <EvidenceButton evidenceIds={claim.evidence_ids} title={title} onEvidence={onEvidence} />
        </>
      ) : <EmptyState text="Not explicitly identified in the paper." />}
    </article>
  );
}

function ClaimList({ claims, emptyState, verification, onEvidence, numbered = false }: { claims: ResearchClaim[]; emptyState?: ExtractionState; verification: VerificationLookup; onEvidence: (ids: string[], title: string) => void; numbered?: boolean }) {
  if (!claims.length) return <StatusState state={emptyState} />;
  return (
    <div className="claim-list">
      {claims.map((claim, index) => (
        <article className={`claim-item${verificationTone(verification.get(claim.id)?.status)}`} key={claim.id}>
          {numbered ? <div className="claim-index">{String(index + 1).padStart(2, "0")}</div> : null}
          <div>
            <p className="statement-copy">{claim.statement}</p>
            <div className="claim-badges"><OriginBadge origin={claim.origin} /><VerificationBadge verification={verification.get(claim.id)} /></div>
            <EvidenceButton evidenceIds={claim.evidence_ids} title={claim.statement} onEvidence={onEvidence} />
          </div>
        </article>
      ))}
    </div>
  );
}

function VisualizationBoard({ reader, analysis, verification, selectedMethodNodeId, onEvidence, onNodeClick, onPage }: { reader: ReaderResponse; analysis: Analysis | null; verification: VerificationLookup; selectedMethodNodeId: string | null; onEvidence: (ids: string[], title: string) => void; onNodeClick: NodeMouseHandler<MethodFlowNode>; onPage: (page: number | null) => void }) {
  const flow = analysis?.method ? methodToFlow(analysis.method) : documentSectionsToFlow(reader.document.sections);
  const tableChart = reader.document.tables.map(tableChartData).find((item): item is TableChartData => item !== null);
  const previewFigures = reader.document.figures.slice(0, 3);
  const previewTables = reader.document.tables.slice(0, 2);
  const previewEquations = analysis?.equations.length
    ? analysis.equations.slice(0, 3).map((equation) => ({ id: equation.id, label: equation.equation_id || "Equation", expression: equation.expression, evidenceIds: equation.evidence_ids }))
    : reader.document.equations.slice(0, 3).map((equation) => ({ id: equation.id, label: equation.label || "Equation", expression: equation.raw_text, evidenceIds: equation.evidence_ids }));
  const graphNodes = flow.nodes.map((node) => {
    const status = verification.get(node.id)?.status;
    const classes = [node.id === selectedMethodNodeId ? "method-node-selected" : "", status === "UNSUPPORTED" ? "method-node-unsupported" : "", status === "CONTRADICTORY" ? "method-node-contradictory" : ""].filter(Boolean).join(" ");
    return { ...node, className: classes || undefined };
  });

  return (
    <div className="visualization-board">
      <div className="visualization-lede">
        <div>
          <div className="card-label">Paper visual map</div>
          <p>One source-grounded view of the paper’s flow, method functions, reported results, and visual artifacts.</p>
        </div>
        <div className="visualization-counts" aria-label="Paper artifact counts">
          <span><strong>{reader.document.figure_count}</strong> figures</span>
          <span><strong>{reader.document.table_count}</strong> tables</span>
          <span><strong>{reader.document.equation_count}</strong> equations</span>
          <span><strong>{reader.document.reference_count}</strong> references</span>
        </div>
      </div>

      <div className="visualization-board-grid">
        <section className="reader-card visualization-flow-card" aria-labelledby="visualization-flow-title">
          <div className="card-label">{analysis?.method ? "Method / function flow" : "Paper structure flow"}</div>
          <h3 id="visualization-flow-title">{analysis?.method ? "How the proposed method works" : "How the paper is organized"}</h3>
          <p className="claim-context">{analysis?.method ? "Nodes are the method functions extracted from the paper. Select one to inspect its evidence." : "Semantic method extraction is unavailable, so this map stays faithful to the parsed section order instead of inventing functions."}</p>
          {flow.nodes.length ? (
            <div className="method-graph visualization-method-graph" aria-label={analysis?.method ? "Interactive method function flow diagram" : "Paper section flow diagram"}>
              <ReactFlow nodes={graphNodes} edges={flow.edges} fitView fitViewOptions={{ padding: 0.25 }} nodesConnectable={false} nodesDraggable={false} onNodeClick={analysis?.method ? onNodeClick : undefined}>
                <Background color="#d8d8d0" gap={24} />
                <Controls showInteractive={false} />
              </ReactFlow>
            </div>
          ) : <EmptyState text="No ordered method or section nodes were recovered." />}
          {analysis?.method ? (
            <div className="visualization-function-list">
              {analysis.method.steps.map((step) => <div className="visualization-function" key={step.id}><span>{String(step.order + 1).padStart(2, "0")}</span><div><strong>{step.label}</strong><p>{step.description}</p></div><EvidenceButton evidenceIds={step.evidence_ids} title={`Method · ${step.label}`} onEvidence={onEvidence} /></div>)}
            </div>
          ) : null}
        </section>

        <section className="reader-card visualization-artifacts-card" aria-labelledby="visualization-artifacts-title">
          <div className="card-label">Source artifacts</div>
          <h3 id="visualization-artifacts-title">Tables, figures, and equations</h3>
          <div className="visualization-artifact-stack">
            {previewFigures.length ? <div><div className="visualization-subheading">Figures</div><div className="visualization-figure-strip">{previewFigures.map((figure) => <button type="button" className="visualization-figure-thumb" key={figure.id} onClick={() => onPage(figure.page)} title={figure.caption || figure.label || "Open figure page"}>{figure.image_reference ? <img src={apiUrl(`/api/papers/${encodeURIComponent(reader.paper.id)}/documents/${encodeURIComponent(reader.document.id)}/figures/${encodeURIComponent(figure.id)}`)} alt={figure.caption || figure.label || "Paper figure"} /> : <span>{figure.label || "Figure"}</span>}<small>{figure.label || "Figure"}</small></button>)}</div></div> : null}
            {previewTables.length ? <div><div className="visualization-subheading">Tables</div>{previewTables.map((table) => <div className="visualization-table-preview" key={table.id}><strong>{table.label || "Table"}</strong>{table.headers.length && table.rows.length ? <div className="artifact-table-wrap"><table className="artifact-table"><thead><tr>{table.headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{table.rows.slice(0, 4).map((row, rowIndex) => <tr key={`${table.id}-${rowIndex}`}>{row.map((cell, cellIndex) => <td key={`${table.id}-${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div> : <pre className="artifact-raw">{table.raw_text || "Structured table cells were not recovered."}</pre>}<EvidenceButton evidenceIds={table.evidence_ids} title={table.label || "Table"} onEvidence={onEvidence} /></div>)}</div> : null}
            {previewEquations.length ? <div><div className="visualization-subheading">Equations</div><div className="visualization-equation-list">{previewEquations.map((equation) => <div className="visualization-equation" key={equation.id}><span>{equation.label}</span><code>{equation.expression}</code><EvidenceButton evidenceIds={equation.evidenceIds} title={equation.label} onEvidence={onEvidence} /></div>)}</div></div> : null}
            {!previewFigures.length && !previewTables.length && !previewEquations.length ? <EmptyState text="No visual artifacts were recovered from the source document." /> : null}
          </div>
        </section>
      </div>

      {tableChart ? <section className="reader-card visualization-table-chart" aria-labelledby="visualization-table-chart-title"><div className="card-label">Table-derived chart</div><h3 id="visualization-table-chart-title">{tableChart.title}</h3><div className="chart-wrap" role="img" aria-label={`Chart derived from ${tableChart.label}`}><ResponsiveContainer width="100%" height={260}><BarChart data={tableChart.data}><CartesianGrid strokeDasharray="3 3" stroke="#d8d8d0" /><XAxis dataKey="label" tick={{ fill: "#64716d", fontSize: 11 }} /><YAxis tick={{ fill: "#64716d", fontSize: 11 }} /><Tooltip /><Bar dataKey="value" fill="#477c78" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div><p className="chart-caption">Parsed numeric values from {tableChart.label}; no unsupported ranking or percentage conversion is inferred.</p><EvidenceButton evidenceIds={tableChart.evidenceIds} title={tableChart.label} onEvidence={onEvidence} /></section> : null}

      {analysis?.results.length ? <section className="visualization-results-block" aria-labelledby="visualization-results-title"><div className="visualization-subheading" id="visualization-results-title">Reported results</div><ResultsSection analysis={analysis} specs={reader.visualizations} state={analysis.extraction.results} verification={verification} onEvidence={onEvidence} /></section> : null}
    </div>
  );
}

type TableChartData = { title: string; label: string; data: { label: string; value: number }[]; evidenceIds: string[] };

function tableChartData(table: ReaderResponse["document"]["tables"][number]): { title: string; label: string; data: { label: string; value: number }[]; evidenceIds: string[] } | null {
  if (!table.headers.length || !table.rows.length) return null;
  const numericColumn = table.headers.findIndex((_header, columnIndex) => table.rows.some((row) => parseTableNumber(row[columnIndex]) !== null));
  if (numericColumn < 0) return null;
  const labelColumn = numericColumn === 0 && table.headers.length > 1 ? 1 : 0;
  const data = table.rows.slice(0, 12).flatMap((row, index) => {
    const value = parseTableNumber(row[numericColumn]);
    return value === null ? [] : [{ label: row[labelColumn]?.trim() || `Row ${index + 1}`, value }];
  });
  if (data.length < 2) return null;
  return { title: table.caption || table.label || "Table comparison", label: table.label || "table", data, evidenceIds: table.evidence_ids };
}

function parseTableNumber(value: string | undefined): number | null {
  const match = value?.replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  const number = Number(match[0]);
  return Number.isFinite(number) ? number : null;
}

function MethodSection({ method, state, verification, selectedNodeId, onEvidence, onNodeClick }: { method: MethodIR | null; state?: ExtractionState; verification: VerificationLookup; selectedNodeId: string | null; onEvidence: (ids: string[], title: string) => void; onNodeClick: NodeMouseHandler<MethodFlowNode> }) {
  if (!method) return <StatusState state={state} />;
  const flow = methodToFlow(method);
  const graphNodes = flow.nodes.map((node) => {
    const status = verification.get(node.id)?.status;
    const classes = [node.id === selectedNodeId ? "method-node-selected" : "", status === "UNSUPPORTED" ? "method-node-unsupported" : "", status === "CONTRADICTORY" ? "method-node-contradictory" : ""].filter(Boolean).join(" ");
    return { ...node, className: classes || undefined };
  });
  return (
    <div className="method-section">
      <div className={`reader-card method-summary${verificationTone(verification.get("method_001")?.status)}`}>
        <p className="statement-copy">{method.summary}</p>
        <div className="claim-badges"><OriginBadge origin={method.origin} /><VerificationBadge verification={verification.get("method_001")} /></div>
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
                return step ? <><strong>{step.label}</strong><p>{step.description}</p><div className="claim-badges"><OriginBadge origin={step.origin} /><VerificationBadge verification={verification.get(step.id)} /></div><EvidenceButton evidenceIds={step.evidence_ids} title={`Method · ${step.label}`} onEvidence={onEvidence} /></> : null;
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

function EquationSection({ equations, sourceEquations, state, verification, onEvidence }: { equations: Analysis["equations"]; sourceEquations: ReaderResponse["document"]["equations"]; state?: ExtractionState; verification: VerificationLookup; onEvidence: (ids: string[], title: string) => void }) {
  if (!equations.length && sourceEquations.length) return <div className="equation-list">{sourceEquations.map((equation) => <article className="reader-card equation-card" key={equation.id}><div className="card-label">{equation.label ? `Equation (${equation.label})` : "Extracted equation"}</div><pre className="equation-fallback">{equation.raw_text}</pre><EvidenceButton evidenceIds={equation.evidence_ids} title={equation.label || "Equation"} onEvidence={onEvidence} /></article>)}</div>;
  if (!equations.length) return <StatusState state={state} />;
  return <div className="equation-list">{equations.map((equation) => <EquationCard key={equation.id} equation={equation} verification={verification.get(equation.id)} onEvidence={onEvidence} />)}</div>;
}

function EquationCard({ equation, verification, onEvidence }: { equation: Analysis["equations"][number]; verification?: ClaimVerification; onEvidence: (ids: string[], title: string) => void }) {
  const explanation = equation.explanation ?? equation.interpretation;
  const rendered = useMemo(() => {
    try {
      return katex.renderToString(equation.expression, { displayMode: true, throwOnError: true, trust: false });
    } catch {
      return null;
    }
  }, [equation.expression]);
  return (
    <article className={`reader-card equation-card${verificationTone(verification?.status)}`}>
      <div className="card-label">{equation.equation_id || "Equation"}</div>
      {rendered ? <div className="equation-rendered" dangerouslySetInnerHTML={{ __html: rendered }} /> : <pre className="equation-fallback">{equation.expression}</pre>}
      {explanation ? <p className="claim-context">{explanation}</p> : <p className="claim-context">No interpretation was explicitly provided.</p>}
      {equation.variables.length ? <dl className="variable-list">{equation.variables.map((variable) => <div key={variable.symbol}><dt>{variable.symbol}</dt><dd>{variable.meaning || "Not explicitly defined in the paper."}</dd></div>)}</dl> : null}
      {equation.role ? <p className="claim-context"><strong>Role:</strong> {equation.role}</p> : null}
      <div className="claim-badges"><OriginBadge origin={equation.origin} />{verification ? <VerificationBadge verification={verification} /> : null}</div>
      <EvidenceButton evidenceIds={equation.evidence_ids} title="Equation" onEvidence={onEvidence} />
    </article>
  );
}

function ExperimentSection({ experiments, state, verification, onEvidence }: { experiments: ExperimentIR[]; state?: ExtractionState; verification: VerificationLookup; onEvidence: (ids: string[], title: string) => void }) {
  if (!experiments.length) return <StatusState state={state} />;
  return <div className="experiment-grid">{experiments.map((experiment) => <ExperimentCard key={experiment.id} experiment={experiment} verification={verification.get(experiment.id)} onEvidence={onEvidence} />)}</div>;
}

function ExperimentCard({ experiment, verification, onEvidence }: { experiment: ExperimentIR; verification?: ClaimVerification; onEvidence: (ids: string[], title: string) => void }) {
  const fields = [
    ["Datasets", experiment.datasets],
    ["Models", experiment.models],
    ["Baselines", experiment.baselines],
    ["Metrics", experiment.metrics],
  ].filter((entry): entry is [string, string[]] => entry[1].length > 0);
  return (
    <article className={`reader-card experiment-card${verificationTone(verification?.status)}`}>
      <div className="card-label">{experiment.name || "Experiment"}</div>
      {fields.length ? <dl className="experiment-fields">{fields.map(([label, values]) => <div key={label}><dt>{label}</dt><dd>{values.join(" · ")}</dd></div>)}</dl> : <EmptyState text="No experimental fields were explicitly identified." />}
      {experiment.setup ? <p className="claim-context">{experiment.setup}</p> : null}
      <div className="claim-badges"><OriginBadge origin={experiment.origin} />{verification ? <VerificationBadge verification={verification} /> : null}</div>
      <EvidenceButton evidenceIds={experiment.evidence_ids} title={experiment.name || "Experiment"} onEvidence={onEvidence} />
    </article>
  );
}

function ResultsSection({ analysis, specs, state, verification, onEvidence }: { analysis: Analysis | null; specs: ReaderResponse["visualizations"]; state?: ExtractionState; verification: VerificationLookup; onEvidence: (ids: string[], title: string) => void }) {
  if (!analysis?.results.length) return <StatusState state={state} />;
  const chartSpec = specs.find((spec) => spec.type === "BAR_CHART" || spec.type === "METRIC");
  const numericRows = analysis.results.filter((result): result is ResultIR & { value: number } => typeof result.value === "number" && Number.isFinite(result.value));
  const chartAllowed = numericRows.every((result) => {
    const status = verification.get(result.id)?.status;
    return !status || status === "SUPPORTED" || status === "PARTIALLY_SUPPORTED";
  });
  return (
    <div className="results-section">
      {chartAllowed && chartSpec?.type === "BAR_CHART" && numericRows.length > 1 ? (
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
      ) : chartAllowed && chartSpec?.type === "METRIC" && numericRows.length === 1 ? (
        <div className="reader-card metric-card"><div className="card-label">{chartSpec.title}</div><strong>{numericRows[0].value}{numericRows[0].unit ? ` ${numericRows[0].unit}` : ""}</strong><p>{numericRows[0].statement}</p></div>
      ) : null}
      <div className="result-list">
        {analysis.results.map((result) => (
          <article className={`result-row${verificationTone(verification.get(result.id)?.status)}`} key={result.id}>
            <div><span className="result-metric">{result.metric || "Reported result"}</span><p>{result.statement}</p></div>
            <div className="result-value">{result.value !== null ? `${result.value}${result.unit ? ` ${result.unit}` : ""}` : "Value unavailable"}</div>
            <div><div className="claim-badges"><OriginBadge origin={result.origin} /><VerificationBadge verification={verification.get(result.id)} /></div><EvidenceButton evidenceIds={result.evidence_ids} title={result.metric || "Result"} onEvidence={onEvidence} /></div>
          </article>
        ))}
      </div>
    </div>
  );
}

function ReferencesSection({ references, onEvidence }: { references: ReaderResponse["document"]["references"]; onEvidence: (ids: string[], title: string) => void }) {
  return (
    <div className="reference-list">
      {references.map((reference) => (
        <article className="reference-item" key={reference.id}>
          <span className="reference-index">[{reference.order + 1}]</span>
          <div><strong>{reference.title || "Parsed reference"}</strong><p>{reference.authors?.join(", ") || reference.raw_text}</p>{reference.year ? <small>{reference.year}{reference.venue ? ` · ${reference.venue}` : ""}</small> : null}{reference.evidence_ids.length ? <EvidenceButton evidenceIds={reference.evidence_ids} title={reference.title || "Reference"} onEvidence={onEvidence} /> : null}</div>
        </article>
      ))}
    </div>
  );
}

function FiguresSection({ figures, paperId, documentId, onEvidence, onPage }: { figures: ReaderResponse["document"]["figures"]; paperId: string; documentId: string; onEvidence: (ids: string[], title: string) => void; onPage: (page: number | null) => void }) {
  return <div className="artifact-grid">{figures.map((figure) => <article className="reader-card artifact-card" key={figure.id}><div className="card-label">{figure.label || "Figure"}</div>{figure.image_reference ? <img className="artifact-image" src={apiUrl(`/api/papers/${encodeURIComponent(paperId)}/documents/${encodeURIComponent(documentId)}/figures/${encodeURIComponent(figure.id)}`)} alt={figure.caption || figure.label || "Extracted paper figure"} /> : null}<p>{figure.caption || "Caption unavailable; visual interpretation is not asserted."}</p><div className="artifact-meta">{figure.page !== null ? <button type="button" onClick={() => onPage(figure.page)}>Page {figure.page}</button> : <span>Page unavailable</span>}</div><EvidenceButton evidenceIds={figure.evidence_ids} title={figure.label || "Figure"} onEvidence={onEvidence} /></article>)}</div>;
}

function TablesSection({ tables, onEvidence, onPage }: { tables: ReaderResponse["document"]["tables"]; onEvidence: (ids: string[], title: string) => void; onPage: (page: number | null) => void }) {
  return <div className="artifact-grid">{tables.map((table) => <article className="reader-card artifact-card" key={table.id}><div className="card-label">{table.label || "Table"}</div><p>{table.caption || "Caption unavailable."}</p>{table.headers.length && table.rows.length ? <div className="artifact-table-wrap"><table><thead><tr>{table.headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{table.rows.map((row, rowIndex) => <tr key={`${table.id}-${rowIndex}`}>{row.map((cell, cellIndex) => <td key={`${table.id}-${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div> : <pre className="artifact-raw">{table.raw_text || "Structured table cells were not recovered reliably."}</pre>}<div className="artifact-meta">{table.page !== null ? <button type="button" onClick={() => onPage(table.page)}>Page {table.page}</button> : <span>Page unavailable</span>}</div><EvidenceButton evidenceIds={table.evidence_ids} title={table.label || "Table"} onEvidence={onEvidence} /></article>)}</div>;
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

function ChatPanel({
  messages,
  loading,
  sending,
  error,
  focus,
  onClearFocus,
  onClose,
  onNewChat,
  onSend,
  onCitation,
}: {
  messages: ChatMessage[];
  loading: boolean;
  sending: boolean;
  error: string | null;
  focus: ChatFocus | null;
  onClearFocus: () => void;
  onClose: () => void;
  onNewChat: () => void;
  onSend: (question: string) => void;
  onCitation: (citation: ChatMessage["citations"][number]) => void;
}) {
  const [input, setInput] = useState("");
  const suggestions = [
    "What problem does this paper address?",
    "What are the main contributions?",
    "Explain the methodology.",
    "What are the key results?",
  ];
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = input.trim();
    if (!question || sending) return;
    setInput("");
    onSend(question);
  }
  return (
    <aside className="chat-panel" aria-label="Ask PaperLens">
      <div className="chat-panel-header">
        <div><div className="card-label">Ask PaperLens</div><strong>Ask this paper</strong></div>
        <div className="chat-panel-actions"><button type="button" className="secondary-button" onClick={onNewChat} disabled={loading || sending}>New chat</button><button type="button" className="close-button" onClick={onClose} aria-label="Close Ask PaperLens">×</button></div>
      </div>
      {focus ? (
        <p className="chat-focus">
          Asking about <strong>{focus.title}</strong>
          <button type="button" className="secondary-button" onClick={onClearFocus}>Clear</button>
        </p>
      ) : null}
      <p className="chat-grounding-note">Answers use only retrieved passages from the current paper. Citations open the source evidence.</p>
      <div className="chat-messages" aria-live="polite">
        {loading ? <p className="chat-state">Opening a document-bound chat…</p> : null}
        {!loading && !messages.length ? <div className="chat-empty"><strong>Start with a paper question.</strong><div className="chat-suggestions">{suggestions.map((suggestion) => <button type="button" key={suggestion} onClick={() => onSend(suggestion)} disabled={sending}>{suggestion}</button>)}</div></div> : null}
        {messages.map((message) => (
          <article className={`chat-message chat-${message.role.toLowerCase()}`} key={message.id}>
            <div className="chat-message-label">{message.role === "USER" ? "You" : "PaperLens"}</div>
            <p>{message.content}</p>
            {message.role === "ASSISTANT" && message.citations.length ? <div className="chat-citations" aria-label="Answer citations">{message.citations.map((citation, index) => <button type="button" key={`${message.id}-${citation.evidence_id}`} onClick={() => onCitation(citation)} title={`${citation.evidence_id}${citation.page ? ` · page ${citation.page}` : ""}`}>[{index + 1}]</button>)}</div> : null}
            {message.status === "INSUFFICIENT_EVIDENCE" ? <small className="chat-insufficient">Insufficient retrieved evidence</small> : null}
            {message.status === "GENERATION_FAILED" ? <small className="chat-failure">Grounded generation failed</small> : null}
          </article>
        ))}
        {sending ? <p className="chat-state">Retrieving evidence and checking citations…</p> : null}
      </div>
      {error ? <p className="chat-error" role="alert">{error}</p> : null}
      <form className="chat-composer" onSubmit={submit}>
        <label htmlFor="paper-chat-question">Question</label>
        <textarea id="paper-chat-question" value={input} onChange={(event) => setInput(event.target.value)} placeholder="Ask about the paper…" rows={3} disabled={sending || loading} />
        <button type="submit" disabled={sending || loading || !input.trim()}>{sending ? "Answering…" : "Ask PaperLens"}</button>
      </form>
    </aside>
  );
}

function OriginBadge({ origin }: { origin: StatementOrigin }) {
  return <span className={`origin-badge ${origin === "AUTHOR_EXPLICIT" ? "origin-explicit" : "origin-inferred"}`}>{origin === "AUTHOR_EXPLICIT" ? "Explicit in paper" : "PaperLens interpretation"}</span>;
}

function VerificationBadge({ verification }: { verification?: ClaimVerification }) {
  const status = verification?.status ?? "UNVERIFIED";
  const labels: Record<VerificationStatus | "MISSING", string> = {
    SUPPORTED: "Supported by evidence",
    PARTIALLY_SUPPORTED: "Partially supported",
    UNSUPPORTED: "Not sufficiently supported",
    CONTRADICTORY: "Contradicted by evidence",
    UNVERIFIED: "Not yet verified",
    MISSING: "Not yet verified",
  };
  return <span className={`verification-badge verification-${status.toLowerCase()}`} title={verification?.rationale || undefined}>{labels[verification ? status : "MISSING"]}</span>;
}

function verificationTone(status?: VerificationStatus): string {
  if (status === "UNSUPPORTED") return " claim-unsupported";
  if (status === "CONTRADICTORY") return " claim-contradictory";
  if (status === "PARTIALLY_SUPPORTED") return " claim-partial";
  return "";
}

function VerificationSummaryCard({ verification, onVerify, error }: { verification: ReaderResponse["verification"]; onVerify?: () => Promise<void>; error?: string | null }) {
  const [loading, setLoading] = useState(false);
  async function handleVerify() {
    if (!onVerify) return;
    setLoading(true);
    try {
      await onVerify();
    } finally {
      setLoading(false);
    }
  }
  if (!verification?.available) {
    return <div className="reader-card verification-summary verification-not-ready"><div><div className="card-label">Verification</div><strong>Not yet verified</strong><p>{error || verification?.error || "Check each semantic claim against its linked evidence."}</p></div>{onVerify ? <button type="button" onClick={() => void handleVerify()} disabled={loading}>{loading ? "Verifying…" : "Verify analysis"}</button> : null}</div>;
  }
  const summary = verification.summary;
  return <div className="reader-card verification-summary"><div className="verification-summary-heading"><div><div className="card-label">Verification</div><strong>Evidence faithfulness checks</strong></div>{onVerify ? <button type="button" className="secondary-button" onClick={() => void handleVerify()} disabled={loading}>{loading ? "Verifying…" : "Reverify"}</button> : null}</div><div className="verification-counts"><span className="verification-supported">{summary.supported} supported</span><span className="verification-partial">{summary.partially_supported} partial</span><span className="verification-unsupported">{summary.unsupported} unsupported</span><span className="verification-contradictory">{summary.contradictory} contradictory</span><span className="verification-unverified">{summary.unverified} unverified</span></div>{error ? <p className="drawer-error" role="alert">{error}</p> : null}</div>;
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

function buildLegacyNavigation(reader: ReaderResponse): { id: ReaderSectionId; label: string; index: string }[] {
  const analysis = reader.analysis;
  const available: ReaderSectionId[] = ["overview", "visualize"];
  if (analysis?.problem || analysis?.motivation) available.push("problem");
  if (analysis?.research_gap.length) available.push("gap");
  if (analysis?.contributions.length) available.push("contributions");
  if (analysis?.method) available.push("method");
  if (analysis?.experiments.length) available.push("experiments");
  if (analysis?.results.length) available.push("results");
  if (analysis?.equations.length || reader.document.equations.length) available.push("equations");
  if (reader.document.figures.length > 0) available.push("figures");
  if (reader.document.tables.length > 0) available.push("tables");
  if (analysis?.limitations.length) available.push("limitations");
  if (analysis?.future_work.length) available.push("future-work");
  if (reader.document.references.length > 0) available.push("references");
  return available.map((id, index) => ({ id, label: sectionLabels[id] || id, index: String(index + 1).padStart(2, "0") }));
}

function buildNavigation(reader: ReaderResponse): { id: ReaderSectionId; label: string; index: string }[] {
  const interactive = reader.interactive_paper;
  const outline = interactive?.outline.filter((item) => interactive.blocks.some((block) => block.id === item.block_id && block.status !== "FAILED")) ?? [];
  if (outline.length) {
    return outline.map((item, index) => ({ id: item.block_id, label: item.title, index: String(index + 1).padStart(2, "0") }));
  }
  return buildLegacyNavigation(reader);
}

function hasSection(navigation: { id: ReaderSectionId }[], id: ReaderSectionId): boolean {
  return navigation.some((item) => item.id === id);
}
