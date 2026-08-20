import type { Edge, Node } from "@xyflow/react";

export type StatementOrigin = "AUTHOR_EXPLICIT" | "MODEL_INFERRED";
export type ExtractionState = { status: string; error: string | null };

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

export type ReaderResponse = {
  paper: ReaderPaper;
  document: ReaderDocumentSummary;
  analysis: Analysis | null;
  visualizations: VisualizationSpec[];
  source: { available: boolean; endpoint: string | null; page_count: number | null };
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

export function firstAvailableEvidence(items: Array<{ evidence_ids: string[] }>): string[] {
  return items.flatMap((item) => item.evidence_ids).filter((id, index, all) => all.indexOf(id) === index);
}
