"use client";
/* eslint-disable @next/next/no-img-element */

import { Background, Controls, ReactFlow, type Edge, type Node, type NodeMouseHandler } from "@xyflow/react";
import katex from "katex";
import { useMemo, useState } from "react";

import { apiUrl } from "../reader-api";
import type { ReaderFigure, ReaderResponse, ReaderTable } from "../reader-models";
import type {
  ChatFocus,
  EquationExplanation,
  InteractivePaper,
  InteractivePaperBlock,
  VisualDiagramIR,
  VisualEdge,
  VisualNode,
} from "../interactive-models";

type Props = {
  paper: InteractivePaper;
  reader: ReaderResponse;
  onEvidence: (ids: string[], title: string) => void;
  onPage: (page: number | null) => void;
  onAsk: (focus: ChatFocus) => void;
};

export function InteractivePaperView({ paper, reader, onEvidence, onPage, onAsk }: Props) {
  const figures = new Map(reader.document.figures.map((item) => [item.id, item]));
  const tables = new Map(reader.document.tables.map((item) => [item.id, item]));
  const ready = paper.blocks.filter((block) => block.status !== "FAILED");
  return (
    <div className="interactive-paper">
      {ready.map((block) => (
        <InteractivePaperBlockView
          key={block.id}
          block={block}
          paperId={reader.paper.id}
          documentId={reader.document.id}
          figures={figures}
          tables={tables}
          onEvidence={onEvidence}
          onPage={onPage}
          onAsk={onAsk}
        />
      ))}
    </div>
  );
}

function InteractivePaperBlockView({
  block,
  paperId,
  documentId,
  figures,
  tables,
  onEvidence,
  onPage,
  onAsk,
}: {
  block: InteractivePaperBlock;
  paperId: string;
  documentId: string;
  figures: Map<string, ReaderFigure>;
  tables: Map<string, ReaderTable>;
  onEvidence: (ids: string[], title: string) => void;
  onPage: (page: number | null) => void;
  onAsk: (focus: ChatFocus) => void;
}) {
  if (block.status === "PLANNED" || block.status === "GENERATING") {
    return (
      <section id={block.id} className="interactive-block interactive-block-pending" aria-labelledby={`${block.id}-title`}>
        <h2 id={`${block.id}-title`}>{block.title}</h2>
        <p className="interactive-pending">{block.status === "GENERATING" ? "Writing this section…" : "This section is planned."}</p>
      </section>
    );
  }
  return (
    <section id={block.id} className="interactive-block" aria-labelledby={`${block.id}-title`}>
      <header className="interactive-block-header">
        <h2 id={`${block.id}-title`}>{block.title}</h2>
        <ProvenanceLabel inferred={block.inferred} reconstructed={Boolean(block.visual?.reconstructed)} />
      </header>
      {block.simplified_explanation ? <SimplifiedExplanation text={block.simplified_explanation} /> : null}
      {block.key_points.length ? (
        <ul className="interactive-points">
          {block.key_points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      ) : null}
      {block.visual ? <VisualDiagram diagram={block.visual} equations={block.equations} figures={block.figures} onEvidence={onEvidence} onAsk={onAsk} /> : null}
      {block.equations.map((equation) => (
        <EquationCard key={equation.id} equation={equation} onEvidence={onEvidence} onAsk={onAsk} />
      ))}
      {block.figures.map((binding) => {
        const figure = figures.get(binding.figure_id);
        return figure ? (
          <FigureCard
            key={binding.figure_id}
            paperId={paperId}
            documentId={documentId}
            figure={figure}
            explanation={binding.simplified_explanation}
            reconstructed={binding.reconstructed}
            onEvidence={onEvidence}
            onPage={onPage}
          />
        ) : null;
      })}
      {block.tables.map((binding) => {
        const table = tables.get(binding.table_id);
        return table ? (
          <TableCard
            key={binding.table_id}
            table={table}
            explanation={binding.simplified_explanation}
            onEvidence={onEvidence}
            onPage={onPage}
          />
        ) : null;
      })}
      {block.error ? <p className="interactive-note">{block.error}</p> : null}
      <div className="interactive-block-actions">
        <EvidenceTrigger evidenceIds={block.evidence_ids} title={block.title} onEvidence={onEvidence} />
        <button
          type="button"
          className="secondary-button"
          onClick={() => onAsk({ title: block.title, evidenceIds: block.evidence_ids })}
        >
          Ask about this
        </button>
      </div>
    </section>
  );
}

function SimplifiedExplanation({ text }: { text: string }) {
  return <p className="interactive-prose">{text}</p>;
}

function VisualDiagram({
  diagram,
  equations,
  figures,
  onEvidence,
  onAsk,
}: {
  diagram: VisualDiagramIR;
  equations: EquationExplanation[];
  figures: { figure_id: string }[];
  onEvidence: (ids: string[], title: string) => void;
  onAsk: (focus: ChatFocus) => void;
}) {
  const [selected, setSelected] = useState<VisualNode | VisualEdge | null>(null);
  const flow = useMemo(() => diagramToFlow(diagram), [diagram]);
  const onNodeClick: NodeMouseHandler = (_event, node) => {
    const match = diagram.nodes.find((item) => item.id === node.id) ?? null;
    setSelected(match);
  };
  const selectedNode = selected && "role" in selected ? (selected as VisualNode) : null;
  const selectedEdge = selected && "source" in selected && !("role" in selected) ? (selected as VisualEdge) : null;
  const relatedEquations = selectedNode
    ? equations.filter((equation) => selectedNode.related_equation_ids.includes(equation.id) || equation.related_node_ids.includes(selectedNode.id))
    : [];
  return (
    <div className="visual-diagram">
      <div className="visual-diagram-label">
        <span>{diagram.reconstructed ? "PaperLens reconstruction" : "Original structure"}</span>
        <strong>{diagram.title}</strong>
      </div>
      <div className="visual-diagram-canvas" aria-label={diagram.title}>
        <ReactFlow
          nodes={flow.nodes}
          edges={flow.edges}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          nodesConnectable={false}
          nodesDraggable={false}
          onNodeClick={onNodeClick}
        >
          <Background color="#d8d8d0" gap={24} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <ol className="visual-outline">
        {diagram.nodes.map((node) => (
          <li key={node.id}>
            <button
              type="button"
              className={`visual-node-control${selectedNode?.id === node.id ? " selected" : ""}`}
              aria-pressed={selectedNode?.id === node.id}
              onClick={() => setSelected(node)}
            >
              {node.label}
              {node.inferred ? " (inferred)" : ""}
            </button>
          </li>
        ))}
      </ol>
      {diagram.edges.map((edge) => (
        <button
          key={edge.id}
          type="button"
          className={`visual-edge-control${edge.inferred ? " inferred" : ""}`}
          onClick={() => setSelected(edge)}
        >
          {edge.label || `${edge.source} → ${edge.target}`}
          {edge.inferred ? " · inferred" : ""}
        </button>
      ))}
      {selectedNode ? (
        <div className="visual-detail" aria-live="polite">
          <strong>{selectedNode.label}</strong>
          {selectedNode.description ? <p>{selectedNode.description}</p> : null}
          {selectedNode.inferred ? <p className="provenance-inferred">This component is inferred rather than stated.</p> : null}
          {relatedEquations.map((equation) => (
            <EquationCard key={equation.id} equation={equation} onEvidence={onEvidence} onAsk={onAsk} />
          ))}
          {figures.length && selectedNode.related_figure_ids.length ? <p className="interactive-note">Related figures are shown in this block.</p> : null}
          <EvidenceTrigger evidenceIds={selectedNode.evidence_ids} title={selectedNode.label} onEvidence={onEvidence} />
          <button type="button" className="secondary-button" onClick={() => onAsk({ title: selectedNode.label, evidenceIds: selectedNode.evidence_ids })}>
            Ask about this
          </button>
        </div>
      ) : null}
      {selectedEdge ? (
        <div className="visual-detail" aria-live="polite">
          <strong>{selectedEdge.label || "Relationship"}</strong>
          {selectedEdge.inferred ? <p className="provenance-inferred">This relationship is inferred rather than explicitly stated.</p> : null}
          <EvidenceTrigger evidenceIds={selectedEdge.evidence_ids} title={selectedEdge.label || "Relationship"} onEvidence={onEvidence} />
        </div>
      ) : null}
    </div>
  );
}

function EquationCard({
  equation,
  onEvidence,
  onAsk,
}: {
  equation: EquationExplanation;
  onEvidence: (ids: string[], title: string) => void;
  onAsk: (focus: ChatFocus) => void;
}) {
  const latex = equation.latex || equation.original_expression;
  const rendered = useMemo(() => {
    try {
      return katex.renderToString(latex, { displayMode: true, throwOnError: true, trust: false });
    } catch {
      return null;
    }
  }, [latex]);
  return (
    <article className="equation-card interactive-equation">
      <div className="card-label">Original equation</div>
      {rendered ? (
        <div className="equation-rendered" role="img" aria-label={equation.original_expression} dangerouslySetInnerHTML={{ __html: rendered }} />
      ) : (
        <pre className="equation-fallback">{equation.original_expression}</pre>
      )}
      {equation.explanation ? (
        <>
          <div className="card-label">In simple terms</div>
          <p className="claim-context">{equation.explanation}</p>
        </>
      ) : null}
      {equation.terms.length ? (
        <>
          <div className="card-label">Terms</div>
          <dl className="variable-list">
            {equation.terms.map((term) => (
              <div key={term.symbol}>
                <dt>{term.symbol}</dt>
                <dd>{term.meaning}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : null}
      <span className="provenance-chip">{equation.origin === "ORIGINAL" ? "Original" : "Simplified"}</span>
      <EvidenceTrigger evidenceIds={equation.evidence_ids} title="Equation" onEvidence={onEvidence} />
      <button type="button" className="secondary-button" onClick={() => onAsk({ title: equation.equation_id || "this equation", evidenceIds: equation.evidence_ids })}>
        Ask about this
      </button>
    </article>
  );
}

function FigureCard({
  paperId,
  documentId,
  figure,
  explanation,
  reconstructed,
  onEvidence,
  onPage,
}: {
  paperId: string;
  documentId: string;
  figure: ReaderFigure;
  explanation: string | null;
  reconstructed: boolean;
  onEvidence: (ids: string[], title: string) => void;
  onPage: (page: number | null) => void;
}) {
  return (
    <article className="reader-card artifact-card">
      <div className="card-label">{reconstructed ? "PaperLens reconstruction" : "Original figure"}</div>
      {figure.image_reference ? (
        <img
          className="artifact-image"
          src={apiUrl(`/api/papers/${encodeURIComponent(paperId)}/documents/${encodeURIComponent(documentId)}/figures/${encodeURIComponent(figure.id)}`)}
          alt={figure.caption || figure.label || "Paper figure"}
        />
      ) : null}
      {figure.caption ? <p>{figure.caption}</p> : null}
      {explanation && explanation !== figure.caption ? <p className="claim-context">{explanation}</p> : null}
      <div className="artifact-meta">
        {figure.page !== null ? (
          <button type="button" onClick={() => onPage(figure.page)}>
            Page {figure.page}
          </button>
        ) : (
          <span>Page unavailable</span>
        )}
      </div>
      <EvidenceTrigger evidenceIds={figure.evidence_ids} title={figure.label || "Figure"} onEvidence={onEvidence} />
    </article>
  );
}

function TableCard({
  table,
  explanation,
  onEvidence,
  onPage,
}: {
  table: ReaderTable;
  explanation: string | null;
  onEvidence: (ids: string[], title: string) => void;
  onPage: (page: number | null) => void;
}) {
  return (
    <article className="reader-card artifact-card">
      <div className="card-label">Original table</div>
      {table.caption ? <p>{table.caption}</p> : null}
      {explanation && explanation !== table.caption ? <p className="claim-context">{explanation}</p> : null}
      {table.headers.length && table.rows.length ? (
        <div className="artifact-table-wrap">
          <table>
            <thead>
              <tr>
                {table.headers.map((header) => (
                  <th key={header}>{header}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, rowIndex) => (
                <tr key={`${table.id}-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${table.id}-${rowIndex}-${cellIndex}`}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <pre className="artifact-raw">{table.raw_text || "Structured table cells were not recovered reliably."}</pre>
      )}
      <div className="artifact-meta">
        {table.page !== null ? (
          <button type="button" onClick={() => onPage(table.page)}>
            Page {table.page}
          </button>
        ) : (
          <span>Page unavailable</span>
        )}
      </div>
      <EvidenceTrigger evidenceIds={table.evidence_ids} title={table.label || "Table"} onEvidence={onEvidence} />
    </article>
  );
}

function EvidenceTrigger({ evidenceIds, title, onEvidence }: { evidenceIds: string[]; title: string; onEvidence: (ids: string[], title: string) => void }) {
  if (!evidenceIds.length) return null;
  return (
    <button type="button" className="evidence-button" aria-label={`View source evidence for ${title}`} onClick={() => void onEvidence(evidenceIds, title)}>
      View source evidence{evidenceIds.length > 1 ? ` (${evidenceIds.length})` : ""}
    </button>
  );
}

function ProvenanceLabel({ inferred, reconstructed }: { inferred: boolean; reconstructed: boolean }) {
  if (inferred) return <span className="provenance-chip">Inferred</span>;
  if (reconstructed) return <span className="provenance-chip">Reconstructed</span>;
  return <span className="provenance-chip">Simplified</span>;
}

function diagramToFlow(diagram: VisualDiagramIR): { nodes: Node[]; edges: Edge[] } {
  const nodes = diagram.nodes.map((node, index) => ({
    id: node.id,
    type: "default",
    position: { x: 36, y: index * 118 },
    className: node.inferred ? "visual-node-inferred" : undefined,
    data: { label: node.label },
  }));
  const edges = diagram.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.label || undefined,
    className: edge.inferred ? "visual-edge-inferred" : undefined,
    animated: false,
  }));
  return { nodes, edges };
}
