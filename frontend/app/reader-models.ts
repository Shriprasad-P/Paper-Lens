import type { Edge, Node } from "@xyflow/react";

export type StatementOrigin = "AUTHOR_EXPLICIT" | "MODEL_INFERRED";
export type ExtractionState = { status: string; error: string | null };
export type VerificationStatus = "SUPPORTED" | "PARTIALLY_SUPPORTED" | "UNSUPPORTED" | "CONTRADICTORY" | "UNVERIFIED";

export type ResearchClaim = {
  id: string;
  statement: string;
  evidence_ids: string[];
  origin: StatementOrigin;
  confidence: number | null;
};

export type ProblemClaim = ResearchClaim & { context: string | null };

export type MethodStep = {
  id: string;
  label: string;
  description: string;
  order: number;
  evidence_ids: string[];
  origin: StatementOrigin;
};

export type MethodRelation = {
  source_step_id: string;
  target_step_id: string;
  relationship: string;
};

export type MethodIR = {
  summary: string;
  evidence_ids: string[];
  origin: StatementOrigin;
  steps: MethodStep[];
  relations: MethodRelation[];
};

export type EquationIR = {
  id: string;
  equation_id: string | null;
  expression: string;
  explanation: string | null;
  interpretation: string | null;
  role: string | null;
  variables: { symbol: string; meaning: string | null }[];
  evidence_ids: string[];
  origin: StatementOrigin;
};

export type ExperimentIR = {
  id: string;
  name: string | null;
  datasets: string[];
  models: string[];
  baselines: string[];
  metrics: string[];
  setup: string | null;
  evidence_ids: string[];
  origin: StatementOrigin;
};

export type ResultIR = {
  id: string;
  statement: string;
  metric: string | null;
  value: number | string | null;
  unit: string | null;
  comparison_target: string | null;
  evidence_ids: string[];
  origin: StatementOrigin;
};

export type Analysis = {
  problem: ProblemClaim | null;
  motivation: ResearchClaim | null;
  research_gap: ResearchClaim[];
  contributions: ResearchClaim[];
  method: MethodIR | null;
  equations: EquationIR[];
  experiments: ExperimentIR[];
  results: ResultIR[];
  limitations: ResearchClaim[];
  future_work: ResearchClaim[];
  extraction: Record<string, ExtractionState>;
};

export type ReaderPaper = {
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
};

export type ReaderSectionSummary = {
  id: string;
  title: string;
  order: number;
  page_start: number | null;
  page_end: number | null;
  paragraph_count: number;
};

export type ReaderReference = {
  id: string;
  order: number;
  raw_text: string;
  title: string | null;
  authors: string[] | null;
  year: number | null;
  venue: string | null;
  doi: string | null;
  arxiv_id: string | null;
  url: string | null;
  evidence_ids: string[];
};

export type ReaderFigure = {
  id: string;
  label: string | null;
  number: string | null;
  caption: string | null;
  page: number | null;
  source_region: Evidence["source_region"];
  image_reference: string | null;
  evidence_ids: string[];
};

export type ReaderTable = {
  id: string;
  label: string | null;
  number: string | null;
  caption: string | null;
  headers: string[];
  rows: string[][];
  raw_text: string | null;
  page: number | null;
  source_region: Evidence["source_region"];
  evidence_ids: string[];
};

export type ReaderEquation = {
  id: string;
  raw_text: string;
  label: string | null;
  explanation: string | null;
  page: number | null;
  source_region: Evidence["source_region"];
  evidence_ids: string[];
};

export type ReaderDocumentSummary = {
  id: string;
  paper_id: string;
  page_count: number | null;
  parser_name: string;
  parser_version: string | null;
  document_hash: string | null;
  sections: ReaderSectionSummary[];
  references: ReaderReference[];
  figures: ReaderFigure[];
  tables: ReaderTable[];
  equations: ReaderEquation[];
  section_count: number;
  paragraph_count: number;
  figure_count: number;
  table_count: number;
  equation_count: number;
  reference_count: number;
};

export type Evidence = {
  id: string;
  paper_id: string;
  document_id: string;
  evidence_type: string;
  source_text: string;
  page: number | null;
  section_id: string | null;
  paragraph_id: string | null;
  equation_id: string | null;
  source_region: { page: number; x0: number | null; y0: number | null; x1: number | null; y1: number | null } | null;
};

export type VisualizationSpec = {
  id: string;
  type: "BAR_CHART" | "LINE_CHART" | "TABLE" | "METRIC" | "METHOD_FLOW" | "COMPARISON";
  title: string;
  data: Record<string, unknown>;
  evidence_ids: string[];
};

export type ClaimVerification = {
  claim_id: string;
  status: VerificationStatus;
  evidence_ids: string[];
  rationale: string | null;
  confidence: number | null;
  verified_at: string;
  verifier_provider: string | null;
  verifier_model: string | null;
  prompt_version: string;
  schema_version: string;
  document_hash: string | null;
  claim_hash: string;
  evidence_hash: string;
  cache_key: string;
};

export type VerificationSummary = {
  total_claims: number;
  supported: number;
  partially_supported: number;
  unsupported: number;
  contradictory: number;
  unverified: number;
  verified_at: string | null;
};

export type PaperVerificationResponse = {
  paper_id: string;
  document_id: string | null;
  document_hash: string | null;
  available: boolean;
  error: string | null;
  summary: VerificationSummary;
  results: ClaimVerification[];
};

export type ReaderResponse = {
  paper: ReaderPaper;
  document: ReaderDocumentSummary;
  analysis: Analysis | null;
  visualizations: VisualizationSpec[];
  source: { available: boolean; endpoint: string | null; page_count: number | null };
  verification: PaperVerificationResponse | null;
  capabilities?: {
    ai_analysis_enabled: boolean;
    semantic_retrieval_enabled: boolean;
    research_agent_enabled: boolean;
    supported_sources: string[];
    beta: boolean;
  } | null;
};

export type ChatCitation = {
  evidence_id: string;
  page: number | null;
  section_id: string | null;
};

export type ChatMessage = {
  id: string;
  session_id: string;
  role: "USER" | "ASSISTANT";
  content: string;
  status: "ANSWERED" | "INSUFFICIENT_EVIDENCE" | "GENERATION_FAILED" | null;
  citations: ChatCitation[];
  sufficient_evidence: boolean | null;
  document_id: string;
  retrieval_query: string | null;
  retrieved_evidence_ids: string[];
  retrieval_scores: Record<string, number>;
  retriever_version: string | null;
  provider: string | null;
  model: string | null;
  created_at: string;
};

export type ChatSession = {
  id: string;
  paper_id: string;
  document_id: string;
  document_hash: string | null;
  created_at: string;
  updated_at: string;
};

export type Workspace = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
};

export type WorkspacePaper = {
  paper_id: string;
  title: string;
  arxiv_id: string;
  analyzed: boolean;
  added_at: string;
};

export type WorkspaceResponse = {
  workspace: Workspace;
  papers: WorkspacePaper[];
};

export type ResearchRunStatus = "CREATED" | "PLANNING" | "DISCOVERING" | "SELECTING" | "INGESTING" | "ANALYZING" | "SYNTHESIZING" | "VERIFYING" | "COMPLETED" | "PARTIAL" | "FAILED" | "CANCELLED" | "INTERRUPTED";
export type ResearchExecutionState = "IDLE" | "QUEUED" | "CLAIMED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCEL_REQUESTED" | "CANCELLED";
export type ResearchEvidenceRef = { paper_id: string; document_id: string; evidence_id: string };
export type ResearchReportClaim = { claim_id: string; statement: string; source_papers: string[]; evidence_refs: ResearchEvidenceRef[]; origin: string; verification_status: string };
export type ResearchCandidate = { candidate_id: string; title: string; authors: string[]; abstract: string | null; year: number | null; arxiv_id: string | null; doi: string | null; canonical_url: string | null; pdf_url: string | null; discovery_provider: string; discovery_query: string; discovery_rank: number; ranking_score: number | null; selected: boolean; ingestion_status: string; paper_id: string | null; error: string | null };
export type ResearchReport = {
  research_question: string;
  executive_summary: ResearchReportClaim[];
  themes: { name: string; summary: string; claims: ResearchReportClaim[] }[];
  methods: { paper_id: string; method: string; evidence_refs: ResearchEvidenceRef[] }[];
  agreements: ResearchReportClaim[];
  contradictions: { id: string; topic: string; claim_a: string; evidence_a: ResearchEvidenceRef[]; claim_b: string; evidence_b: ResearchEvidenceRef[]; contradiction_type: string; explanation: string; verification_status: string }[];
  research_gaps: { id: string; statement: string; evidence_refs: ResearchEvidenceRef[]; origin: string; verification_status: string }[];
  limitations: ResearchReportClaim[];
  future_directions: ResearchReportClaim[];
  papers: { paper_id: string; title: string; authors: string[]; year: number | null; why_selected: string; ingestion_status: string; analysis_status: string; verification_status: string }[];
  coverage: { sufficient: boolean; covered_concepts: string[]; missing_concepts: string[]; relevant_paper_ids: string[]; evidence_count: number; summary: string };
  discovery_queries: string[];
  candidate_count: number;
  selected_count: number;
};
export type ResearchRun = { id: string; workspace_id: string | null; research_question: string; status: ResearchRunStatus; execution_state: ResearchExecutionState; active_attempt_id: string | null; attempt_count: number; cancel_requested_at: string | null; next_attempt_at: string | null; created_at: string; updated_at: string; completed_at: string | null; max_iterations: number; max_candidates: number; max_ingested_papers: number; planner_provider: string | null; planner_model: string | null; prompt_version: string; schema_version: string };
export type ResearchEvent = { id: string; research_run_id: string; event_type: string; message: string; metadata: Record<string, unknown>; created_at: string; attempt_id: string | null; sequence: number | null };
export type ResearchPlan = { research_question: string; search_queries: string[]; concepts: string[]; inclusion_criteria: string[]; exclusion_criteria: string[]; desired_paper_count: number; rationale_summary: string | null };
export type ResearchAttempt = { attempt_id: string; research_run_id: string; worker_id: string; attempt_number: number; status: string; claimed_at: string; lease_expires_at: string; heartbeat_at: string | null; started_at: string | null; completed_at: string | null; next_retry_at: string | null; retryable: boolean | null; error_class: string | null; error_message: string | null };
export type ResearchRunResponse = { run: ResearchRun; plan: ResearchPlan | null; queries: string[]; candidates: ResearchCandidate[]; events: ResearchEvent[]; coverage: ResearchReport["coverage"] | null; report: ResearchReport | null; attempt: ResearchAttempt | null };

export type ComparisonEntry = {
  paper_id: string;
  document_id: string | null;
  statement: string | null;
  values: string[];
  evidence_ids: string[];
};

export type ComparisonDimension = {
  name: string;
  entries: ComparisonEntry[];
  comparability: "COMPARABLE" | "PARTIALLY_COMPARABLE" | "NOT_COMPARABLE" | null;
  note: string | null;
};

export type PaperComparisonIR = {
  paper_ids: string[];
  dimensions: ComparisonDimension[];
};

export type CitationNode = {
  id: string;
  type: string;
  title: string;
  paper_id: string | null;
  reference_id: string | null;
  authors: string[];
  year: number | null;
  raw_text: string | null;
};

export type CitationEdge = {
  source_paper_id: string;
  reference_id: string;
  target_node_id: string;
  relationship: string;
};

export type CitationGraph = {
  paper_id: string;
  nodes: CitationNode[];
  edges: CitationEdge[];
};

export type ChatSessionResponse = {
  session: ChatSession;
  messages: ChatMessage[];
};

export type ChatAnswerResponse = {
  message_id: string;
  answer: string;
  status: "ANSWERED" | "INSUFFICIENT_EVIDENCE" | "GENERATION_FAILED";
  sufficient_evidence: boolean;
  citations: ChatCitation[];
};

export type MethodNodeData = {
  label: string;
  description: string;
  origin: StatementOrigin;
  evidenceIds: string[];
};

export type MethodFlowNode = Node<MethodNodeData>;
export type MethodFlowEdge = Edge;

export function methodToFlow(method: MethodIR): { nodes: MethodFlowNode[]; edges: MethodFlowEdge[] } {
  const steps = [...method.steps].sort((left, right) => left.order - right.order);
  const ids = new Set(steps.map((step) => step.id));
  const nodes = steps.map<MethodFlowNode>((step, index) => ({
    id: step.id,
    type: "default",
    position: { x: 40, y: index * 142 },
    data: {
      label: step.label,
      description: step.description,
      origin: step.origin,
      evidenceIds: step.evidence_ids,
    },
  }));
  const edges = method.relations
    .filter((relation) => ids.has(relation.source_step_id) && ids.has(relation.target_step_id))
    .map<MethodFlowEdge>((relation, index) => ({
      id: `${relation.source_step_id}-${relation.target_step_id}-${index}`,
      source: relation.source_step_id,
      target: relation.target_step_id,
      label: relation.relationship,
      animated: false,
    }));
  return { nodes, edges };
}

export function documentSectionsToFlow(sections: ReaderSectionSummary[]): { nodes: MethodFlowNode[]; edges: MethodFlowEdge[] } {
  const ordered = [...sections].sort((left, right) => left.order - right.order);
  const nodes = ordered.map<MethodFlowNode>((section, index) => ({
    id: `section-${section.id}`,
    type: "default",
    position: { x: 40, y: index * 142 },
    data: {
      label: section.title || `Section ${index + 1}`,
      description: `${section.paragraph_count} source paragraphs${section.page_start !== null ? ` · page ${section.page_start}${section.page_end && section.page_end !== section.page_start ? `–${section.page_end}` : ""}` : ""}`,
      origin: "AUTHOR_EXPLICIT",
      evidenceIds: [],
    },
  }));
  const edges = ordered.slice(1).map<MethodFlowEdge>((section, index) => ({
    id: `section-flow-${index}`,
    source: `section-${ordered[index].id}`,
    target: `section-${section.id}`,
    label: "next",
    animated: false,
  }));
  return { nodes, edges };
}

export function firstAvailableEvidence(items: Array<{ evidence_ids: string[] }>): string[] {
  return items.flatMap((item) => item.evidence_ids).filter((id, index, all) => all.indexOf(id) === index);
}
