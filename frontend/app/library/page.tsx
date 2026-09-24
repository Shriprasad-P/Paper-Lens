"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { listPapers, requestJson, resolvePaper, uploadPaper } from "../reader-api";
import type { ReaderPaper, ResolvedPaper } from "../reader-models";

export default function LibraryPage() {
  const router = useRouter();
  const [papers, setPapers] = useState<ReaderPaper[]>([]);
  const [source, setSource] = useState("");
  const [resolved, setResolved] = useState<ResolvedPaper | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function refresh() { try { setPapers(await listPapers()); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Your library could not be loaded."); } }
  useEffect(() => { void refresh(); }, []);

  async function addPaper(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!source.trim()) return;
    const needsCandidate = resolved && Boolean(resolved.resolver_provenance.needs_candidate_confirmation)
      && resolved.candidates.length > 1;
    if (needsCandidate) {
      setError("Select the intended paper match before opening the Interactive Paper.");
      return;
    }
    setBusy(true); setError(null); setMessage(null);
    try { const paper = await requestJson<{ id: string }>("/api/papers/ingest", { method: "POST", body: JSON.stringify({ source: source.trim() }) }); router.push(`/papers/${paper.id}`); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "The paper could not be prepared."); }
    finally { setBusy(false); }
  }
  async function preview() { if (!source.trim()) return; setBusy(true); setError(null); try { setResolved(await resolvePaper(source.trim())); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "The paper could not be resolved."); } finally { setBusy(false); } }
  function chooseCandidate(candidate: Record<string, unknown>) {
    const doi = typeof candidate.doi === "string" ? candidate.doi.trim() : "";
    if (!doi) {
      setError("This match has no DOI. Use its publisher link or upload the PDF to continue.");
      return;
    }
    setSource(doi);
    setResolved(null);
    setError(null);
  }
  async function onFile(event: React.ChangeEvent<HTMLInputElement>) { const file = event.target.files?.[0]; if (!file) return; setBusy(true); setError(null); try { const paper = await uploadPaper(file); router.push(`/papers/${paper.id}`); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "The PDF could not be uploaded."); } finally { setBusy(false); event.target.value = ""; } }

  const ambiguous = resolved && Boolean(resolved.resolver_provenance.needs_candidate_confirmation) && resolved.candidates.length > 1;
  return <main className="page-shell library-shell"><header className="library-header"><div><div className="eyebrow">PAPERLENS / LIBRARY</div><h1>Your research library</h1><p className="hero-copy">Add a paper once, then read one evidence-linked Interactive Paper from overview to takeaway.</p></div><Link className="secondary-button" href="/setup/provider">Provider settings</Link></header><section className="library-add" aria-labelledby="add-paper-title"><div className="card-label" id="add-paper-title">Add research paper</div><p>Paste an arXiv ID, DOI, PubMed/PMC ID, scholarly URL, APA/IEEE citation, BibTeX, or RIS record.</p><form onSubmit={addPaper}><label htmlFor="paper-source">Identifier, citation, or URL<input id="paper-source" aria-label="Paper identifier, citation, or URL" value={source} onChange={(event) => setSource(event.target.value)} placeholder="10.1145/... · arXiv:1706.03762 · citation text" /></label><div className="input-row"><button type="submit" disabled={busy || Boolean(ambiguous)}>{busy ? "Preparing…" : ambiguous ? "Select a match first" : "Open Interactive Paper"}</button><button type="button" className="secondary-button" onClick={() => void preview()} disabled={busy}>Preview match</button><label className="upload-button">Upload PDF<input type="file" accept="application/pdf,.pdf" onChange={onFile} hidden /></label></div></form>{resolved ? <div className="resolved-paper"><div className="card-label">Resolved paper · {resolved.source_type}</div><strong>{resolved.title}</strong><p>{resolved.authors.join(" · ") || "Author metadata unavailable"}{resolved.year ? ` · ${resolved.year}` : ""}</p>{ambiguous ? <><p role="status">Several scholarly matches were found. Select one to continue safely.</p><div className="candidate-list">{resolved.candidates.slice(0, 5).map((candidate, index) => <button type="button" className="candidate-button" key={`${String(candidate.doi ?? candidate.title ?? index)}-${index}`} onClick={() => chooseCandidate(candidate)}><strong>{String(candidate.title ?? "Untitled match")}</strong><span>{[candidate.doi, candidate.venue, candidate.year].filter(Boolean).map(String).join(" · ")}</span></button>)}</div></> : resolved.open_access_pdf_url ? <span>Open-access PDF found.</span> : <span>Paper identified. Upload the PDF to continue full-paper analysis.</span>}</div> : null}{message ? <div className="status-card" role="status"><p>{message}</p></div> : null}{error ? <div className="status-card error-card" role="alert"><p>{error}</p></div> : null}</section><section className="library-list" aria-labelledby="library-list-title"><div className="card-label" id="library-list-title">Saved papers</div>{papers.length ? <div className="paper-library-grid">{papers.map((paper) => <Link className="paper-library-card" key={paper.id} href={`/papers/${paper.id}`}><span className="paper-library-status">{paper.status}</span><h2>{paper.metadata.title}</h2><p>{paper.metadata.authors.join(" · ") || "Authors unavailable"}</p>{paper.last_opened_at ? <small>Last opened {new Date(paper.last_opened_at).toLocaleDateString()}</small> : null}<span>Open reader →</span></Link>)}</div> : <p className="workspace-muted">No papers yet. Add a scholarly identifier or upload a PDF above.</p>}</section><div className="landing-links"><Link href="/research">Ask across papers →</Link><span>·</span><Link href="/workspaces">Open research workspaces →</Link></div></main>;
}
