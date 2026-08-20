"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { createWorkspace, listWorkspaces } from "../reader-api";
import type { Workspace } from "../reader-models";

export default function WorkspacesPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setWorkspaces(await listWorkspaces());
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Workspaces could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      const workspace = await createWorkspace(name.trim());
      setName("");
      window.location.href = `/workspaces/${workspace.id}`;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Workspace could not be created.");
    }
  }

  return (
    <main className="page-shell workspace-shell">
      <div className="workspace-topline"><Link className="back-link" href="/">← New paper</Link><div className="eyebrow">PAPERLENS / RESEARCH WORKSPACES</div></div>
      <section className="workspace-hero"><h1>Keep a small, evidence-linked literature set in view.</h1><p>Workspaces persist selected papers locally. Comparison preserves each paper’s document and evidence identity and refuses unsafe numeric rankings.</p></section>
      <form className="workspace-create" onSubmit={submit}><label htmlFor="workspace-name">Create workspace</label><div className="input-row"><input id="workspace-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Efficient vision models" /><button type="submit">Create workspace</button></div></form>
      {error ? <div className="status-card error-card" role="alert"><p>{error}</p></div> : null}
      <section className="workspace-list" aria-labelledby="workspace-list-title"><div className="card-label" id="workspace-list-title">Saved workspaces</div>{loading ? <p className="workspace-muted">Loading…</p> : workspaces.length ? <div className="workspace-cards">{workspaces.map((workspace) => <Link className="workspace-card" key={workspace.id} href={`/workspaces/${workspace.id}`}><strong>{workspace.name}</strong><span>Open workspace →</span></Link>)}</div> : <p className="workspace-muted">No workspaces yet. Create one, then add ingested paper IDs.</p>}</section>
    </main>
  );
}
