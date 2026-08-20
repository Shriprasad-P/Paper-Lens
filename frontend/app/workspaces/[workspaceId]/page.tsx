"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { addPaperToWorkspace, compareWorkspace, loadCitationGraph, loadEvidence, loadWorkspace, removePaperFromWorkspace } from "../../reader-api";
import type { CitationGraph, PaperComparisonIR, WorkspaceResponse } from "../../reader-models";

export default function WorkspaceDetailPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceResponse | null>(null);
  const [paperId, setPaperId] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<PaperComparisonIR | null>(null);
  const [graph, setGraph] = useState<CitationGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async (id = workspaceId) => {
    if (!id) return;
    setLoading(true);
    try { setWorkspace(await loadWorkspace(id)); setError(null); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Workspace could not be loaded."); } finally { setLoading(false); }
  }, [workspaceId]);

  useEffect(() => { void params.then(({ workspaceId: id }) => { setWorkspaceId(id); void refresh(id); }); }, [params, refresh]);

  async function addPaper(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workspaceId || !paperId.trim()) return;
    try { const next = await addPaperToWorkspace(workspaceId, paperId.trim()); setWorkspace(next); setPaperId(""); setError(null); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Paper could not be added."); }
  }

  async function compare() {
    if (!workspaceId || selected.length < 2) return;
    try { setComparison(await compareWorkspace(workspaceId, selected)); setError(null); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Comparison could not be generated."); }
  }

  async function showGraph(paper: string) {
    try { setGraph(await loadCitationGraph(paper)); setError(null); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Citation graph could not be loaded."); }
  }

  async function removePaper(paper: string) {
    if (!workspaceId) return;
    try { setWorkspace(await removePaperFromWorkspace(workspaceId, paper)); setSelected((current) => current.filter((id) => id !== paper)); setError(null); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Paper could not be removed."); }
  }

  if (loading && !workspace) return <main className="reader-loading"><div className="eyebrow">PAPERLENS / WORKSPACE</div><h1>Loading workspace…</h1></main>;
  if (!workspace) return <main className="reader-loading"><h1>Workspace unavailable</h1><p>{error || "The workspace was not found."}</p><Link className="back-link" href="/workspaces">← Workspaces</Link></main>;
  return (
    <main className="page-shell workspace-shell workspace-detail-shell">
      <div className="workspace-topline"><Link className="back-link" href="/workspaces">← Workspaces</Link><div className="eyebrow">PAPERLENS / WORKSPACE</div></div>
      <section className="workspace-hero"><h1>{workspace.workspace.name}</h1><p>Select analyzed papers to build a source-preserving comparison. Citation graph matching only uses papers already present in this local corpus.</p></section>
      <form className="workspace-create" onSubmit={addPaper}><label htmlFor="paper-id">Add ingested paper ID</label><div className="input-row"><input id="paper-id" value={paperId} onChange={(event) => setPaperId(event.target.value)} placeholder="paper_…" /><button type="submit">Add paper</button></div></form>
      {error ? <div className="status-card error-card" role="alert"><p>{error}</p></div> : null}
      <section className="workspace-list"><div className="card-label">Papers in workspace</div>{workspace.papers.length ? <div className="workspace-paper-list">{workspace.papers.map((paper) => <div className="workspace-paper-row" key={paper.paper_id}><input aria-label={`Select ${paper.title}`} type="checkbox" checked={selected.includes(paper.paper_id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, paper.paper_id] : current.filter((id) => id !== paper.paper_id))} /><span><strong>{paper.title}</strong><small>{paper.arxiv_id} · {paper.analyzed ? "Analyzed" : "Ingested only"}</small></span><Link href={`/papers/${paper.paper_id}`}>Reader</Link><button type="button" className="secondary-button" onClick={() => void showGraph(paper.paper_id)}>Citations</button><button type="button" className="secondary-button" onClick={() => void removePaper(paper.paper_id)}>Remove</button></div>)}</div> : <p className="workspace-muted">Add a paper from the visual reader URL or ingest response.</p>}<button type="button" className="workspace-compare-button" onClick={() => void compare()} disabled={selected.length < 2}>Compare selected ({selected.length})</button></section>
      {comparison ? <ComparisonView comparison={comparison} /> : null}
      {graph ? <CitationGraphView graph={graph} /> : null}
    </main>
  );
}

function ComparisonView({ comparison }: { comparison: PaperComparisonIR }) {
  const [records, setRecords] = useState<Record<string, string[]>>({});
  async function showEvidence(paperId: string, evidenceIds: string[]) {
    const loaded = await Promise.all(evidenceIds.map((id) => loadEvidence(paperId, id)));
    setRecords((current) => ({ ...current, [`${paperId}:${evidenceIds.join(",")}`]: loaded.map((item) => `${item.id}: ${item.source_text}`) }));
  }
  return <section className="comparison-panel"><div className="card-label">Comparison IR</div><p className="workspace-muted">Each cell retains its paper ID and linked evidence. Comparability is descriptive; no unsupported winner is inferred.</p><div className="comparison-table-wrap"><table className="comparison-table"><thead><tr><th>Dimension</th>{comparison.paper_ids.map((paperId) => <th key={paperId}>{paperId}</th>)}</tr></thead><tbody>{comparison.dimensions.map((dimension) => <tr key={dimension.name}><th>{dimension.name}<small>{dimension.comparability || "Context"}</small></th>{comparison.paper_ids.map((paperId) => { const entry = dimension.entries.find((item) => item.paper_id === paperId); const key = `${paperId}:${entry?.evidence_ids.join(",") || ""}`; return <td key={paperId}>{entry?.statement || entry?.values.join(" · ") || "Not explicitly available."}{entry?.evidence_ids.length ? <><button type="button" className="evidence-button" onClick={() => void showEvidence(paperId, entry.evidence_ids)}>View Evidence</button>{records[key]?.map((record) => <small key={record}>{record}</small>)}</> : null}</td>; })}</tr>)}</tbody></table></div></section>;
}

function CitationGraphView({ graph }: { graph: CitationGraph }) {
  return <section className="comparison-panel"><div className="card-label">Citation graph</div><p className="workspace-muted">{graph.nodes.length} nodes · {graph.edges.length} matched citation edges</p><ul className="citation-list">{graph.edges.map((edge) => <li key={`${edge.reference_id}-${edge.target_node_id}`}>{edge.reference_id} → {graph.nodes.find((node) => node.id === edge.target_node_id)?.title || edge.target_node_id}</li>)}</ul></section>;
}
