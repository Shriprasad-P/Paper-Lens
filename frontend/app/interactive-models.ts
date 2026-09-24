export type BlockType =
  | "overview"
  | "problem"
  | "motivation"
  | "background"
  | "method"
  | "architecture"
  | "workflow"
  | "algorithm"
  | "equation_explanation"
  | "experiment"
  | "result"
  | "comparison"
  | "limitation"
  | "conclusion"
  | "figure_explanation"
  | "table_explanation"
  | "dataset"
  | "implementation_detail";

export type BlockStatus = "PLANNED" | "GENERATING" | "READY" | "FAILED";
export type DiagramType = "flow" | "architecture" | "pipeline" | "hierarchy" | "sequence" | "data_flow" | "comparison";
export type ProvenanceKind = "ORIGINAL" | "SIMPLIFIED" | "RECONSTRUCTED" | "INFERRED";

export type VisualNode = {
  id: string;
  label: string;
  description: string | null;
  role: string | null;
  evidence_ids: string[];
  inferred: boolean;
  related_equation_ids: string[];
  related_figure_ids: string[];
};

export type VisualEdge = {
  id: string;
  source: string;
  target: string;
  label: string | null;
  evidence_ids: string[];
  inferred: boolean;
};

export type VisualDiagramIR = {
  type: DiagramType;
  title: string;
  nodes: VisualNode[];
  edges: VisualEdge[];
  reconstructed: boolean;
};

export type FigureVisualAnalysis = {
  kind: string;
  summary: string;
  findings: string[];
  diagram: VisualDiagramIR | null;
  evidence_ids: string[];
  origin: ProvenanceKind;
};

export type EquationTerm = {
  symbol: string;
  meaning: string;
  evidence_ids: string[];
};

export type EquationExplanation = {
  id: string;
  equation_id: string | null;
  original_expression: string;
  latex: string | null;
  explanation: string | null;
  purpose: string | null;
  terms: EquationTerm[];
  evidence_ids: string[];
  page: number | null;
  section_id: string | null;
  related_node_ids: string[];
  origin: ProvenanceKind;
};

export type FigureBinding = {
  figure_id: string;
  simplified_explanation: string | null;
  evidence_ids: string[];
  reconstructed: boolean;
  visual_analysis: FigureVisualAnalysis | null;
};

export type TableBinding = {
  table_id: string;
  simplified_explanation: string | null;
  important_cells: { row: number; column: number | null; note: string }[];
  evidence_ids: string[];
};

export type InteractivePaperBlock = {
  id: string;
  type: BlockType;
  title: string;
  simplified_explanation: string | null;
  visual: VisualDiagramIR | null;
  archify_ir?: Record<string, unknown> | null;
  equations: EquationExplanation[];
  figures: FigureBinding[];
  tables: TableBinding[];
  key_points: string[];
  evidence_ids: string[];
  status: BlockStatus;
  inferred: boolean;
  validator_status: "PASSED" | "PARTIAL" | "REJECTED" | null;
  error: string | null;
};

export type OutlineItem = {
  block_id: string;
  title: string;
  type: BlockType;
};

export type InteractivePaper = {
  schema_version: string;
  paper_id: string;
  document_id: string;
  source_hash: string | null;
  document_hash: string | null;
  analysis_fingerprint: string | null;
  generation_mode: "assembler" | "simplified";
  cache_key: string;
  provider: string | null;
  model: string | null;
  prompt_version: string;
  status: BlockStatus;
  overview: string | null;
  blocks: InteractivePaperBlock[];
  outline: OutlineItem[];
  concepts: { id: string; label: string; evidence_ids: string[] }[];
  generated_at: string;
};

export type ChatFocus = {
  title: string;
  evidenceIds: string[];
};
