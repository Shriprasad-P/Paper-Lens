import { expect, test } from "@playwright/test";

const readerFixture = {
  paper: {
    id: "paper_fixture",
    status: "COMPLETED",
    metadata: {
      arxiv_id: "1706.03762",
      title: "Attention Is All You Need (fixture)",
      authors: ["A. Author"],
      abstract: "A deterministic fixture paper.",
      published_at: null,
      updated_at: null,
      categories: ["cs.CL"],
      source_url: "https://arxiv.org/abs/1706.03762",
      pdf_url: "https://arxiv.org/pdf/1706.03762.pdf",
    },
  },
  document: {
    id: "doc_fixture",
    paper_id: "paper_fixture",
    page_count: 2,
    parser_name: "fixture",
    parser_version: "1",
    document_hash: "hash",
    sections: [{ id: "sec_001", title: "Method", order: 0, page_start: 1, page_end: 1, paragraph_count: 1 }],
    references: [],
    figures: [],
    tables: [],
    equations: [],
    section_count: 1,
    paragraph_count: 1,
    figure_count: 0,
    table_count: 0,
    equation_count: 0,
    reference_count: 0,
  },
  analysis: {
    problem: null,
    motivation: null,
    research_gap: [],
    contributions: [],
    method: { summary: "The fixture method.", evidence_ids: ["ev_fixture"], origin: "AUTHOR_EXPLICIT", steps: [], relations: [] },
    equations: [],
    experiments: [],
    results: [],
    limitations: [],
    future_work: [],
    extraction: {},
  },
  visualizations: [],
  source: { available: true, endpoint: "/api/papers/paper_fixture/source", page_count: 2 },
  verification: null,
};

test("reader, evidence drawer, PDF navigation, and grounded chat work with deterministic mocks", async ({ page }) => {
  let chatAnswered = false;
  await page.route("**/api/papers/ingest", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "paper_fixture" }) }));
  await page.route("**/api/papers/paper_fixture/reader", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(readerFixture) }));
  await page.route("**/api/papers/paper_fixture/source", async (route) => route.fulfill({ status: 200, contentType: "application/pdf", body: "%PDF-fixture" }));
  await page.route("**/api/papers/paper_fixture/evidence/ev_fixture", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "ev_fixture", paper_id: "paper_fixture", document_id: "doc_fixture", evidence_type: "PARAGRAPH", source_text: "The fixture method is source grounded.", page: 1, section_id: "sec_001", paragraph_id: "para_001", equation_id: null, source_region: null }) }));
  await page.route("**/api/papers/paper_fixture/verify", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ paper_id: "paper_fixture", document_id: "doc_fixture", document_hash: "hash", available: true, error: null, summary: { total_claims: 1, supported: 1, partially_supported: 0, unsupported: 0, contradictory: 0, unverified: 0, verified_at: new Date().toISOString() }, results: [] }) }));
  await page.route("**/api/papers/paper_fixture/chat/sessions", async (route) => route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ session_id: "session_fixture", paper_id: "paper_fixture", document_id: "doc_fixture", document_hash: "hash", created_at: new Date().toISOString(), updated_at: new Date().toISOString() }) }));
  await page.route("**/api/papers/paper_fixture/chat/sessions/session_fixture/messages", async (route) => {
    chatAnswered = true;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ message_id: "message_fixture", answer: "The fixture method is source grounded.", status: "ANSWERED", sufficient_evidence: true, citations: [{ evidence_id: "ev_fixture", page: 1, section_id: "sec_001" }] }) });
  });
  await page.route("**/api/papers/paper_fixture/chat/sessions/session_fixture", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session: { id: "session_fixture", paper_id: "paper_fixture", document_id: "doc_fixture", document_hash: "hash", created_at: new Date().toISOString(), updated_at: new Date().toISOString() }, messages: chatAnswered ? [{ id: "user_fixture", session_id: "session_fixture", role: "USER", content: "Explain the method.", status: null, citations: [], sufficient_evidence: null, document_id: "doc_fixture", retrieval_query: "explain method", retrieved_evidence_ids: ["ev_fixture"], retrieval_scores: {}, retriever_version: "bm25-v1", provider: "fixture", model: "fixture", created_at: new Date().toISOString() }, { id: "message_fixture", session_id: "session_fixture", role: "ASSISTANT", content: "The fixture method is source grounded.", status: "ANSWERED", citations: [{ evidence_id: "ev_fixture", page: 1, section_id: "sec_001" }], sufficient_evidence: true, document_id: "doc_fixture", retrieval_query: "explain method", retrieved_evidence_ids: ["ev_fixture"], retrieval_scores: {}, retriever_version: "bm25-v1", provider: "fixture", model: "fixture", created_at: new Date().toISOString() }] : [] }) }));
  await page.goto("/");
  await page.getByLabel("arXiv URL or identifier").fill("1706.03762");
  await page.getByRole("button", { name: "Open visual reader" }).click();
  await expect(page).toHaveURL(/papers\/paper_fixture/);
  await expect(page.getByRole("heading", { name: /Attention Is All You Need/ })).toBeVisible();
  await page.getByRole("button", { name: /Visualize/ }).click();
  await expect(page.getByRole("heading", { name: "Visualize", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "How the proposed method works" })).toBeVisible();
  await expect(page.getByText("Paper visual map", { exact: true })).toBeVisible();
  await expect(page.getByTitle("Original paper PDF")).toBeVisible();
  await page.getByRole("region", { name: "Method" }).getByRole("button", { name: "View evidence for Method summary" }).click();
  await expect(page.getByRole("dialog")).toContainText("fixture method");
  await page.getByRole("button", { name: "Close evidence" }).click();
  await page.getByRole("button", { name: "Open Paper Chat" }).click();
  await expect(page.getByText("Paper Chat", { exact: true })).toBeVisible();
  await page.getByLabel("Question").fill("Explain the method.");
  await page.getByRole("button", { name: "Ask paper" }).click();
  await expect(page.getByText("The fixture method is source grounded.")).toBeVisible();
  await page.getByRole("button", { name: "[1]" }).click();
  await expect(page.getByRole("dialog")).toContainText("fixture method");
  await page.getByRole("button", { name: "Close evidence" }).click();
  await page.getByRole("button", { name: "Verify analysis" }).click();
});

test("workspace and research entry points remain navigable without live providers", async ({ page }) => {
  await page.route("**/api/workspaces", async (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "workspace_fixture", name: "Fixture workspace", created_at: new Date().toISOString(), updated_at: new Date().toISOString() }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  const workspaceFixture = { workspace: { id: "workspace_fixture", name: "Fixture workspace", created_at: new Date().toISOString(), updated_at: new Date().toISOString() }, papers: [] };
  await page.route("**/api/workspaces/workspace_fixture", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(workspaceFixture) }));
  await page.route("**/api/workspaces/workspace_fixture/papers/*", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...workspaceFixture, papers: [{ paper_id: "paper_a", title: "Paper A", arxiv_id: "1706.03762", analyzed: true, added_at: new Date().toISOString() }, { paper_id: "paper_b", title: "Paper B", arxiv_id: "1706.03763", analyzed: true, added_at: new Date().toISOString() }] }) }));
  await page.route("**/api/workspaces/workspace_fixture/compare", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ paper_ids: ["paper_a", "paper_b"], dimensions: [{ name: "Method", entries: [], comparability: "NOT_COMPARABLE", note: "Fixture" }] }) }));
  await page.route("**/api/research/runs", async (route) => route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ run: { id: "research_fixture", status: "CREATED" } }) }));
  await page.route("**/api/research/runs/research_fixture", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ run: { id: "research_fixture", workspace_id: null, research_question: "Which methods improve retrieval?", status: "COMPLETED", created_at: new Date().toISOString(), updated_at: new Date().toISOString(), completed_at: new Date().toISOString(), max_iterations: 1, max_candidates: 1, max_ingested_papers: 1, planner_provider: "fixture", planner_model: "fixture", prompt_version: "v1", schema_version: "v1" }, plan: null, queries: ["retrieval methods"], candidates: [], events: [{ id: "event_fixture", research_run_id: "research_fixture", event_type: "RUN_COMPLETED", message: "Fixture report completed.", metadata: {}, created_at: new Date().toISOString() }], coverage: { sufficient: true, covered_concepts: ["retrieval"], missing_concepts: [], relevant_paper_ids: ["paper_fixture"], evidence_count: 1, summary: "Fixture coverage." }, report: { research_question: "Which methods improve retrieval?", executive_summary: [{ claim_id: "claim_fixture", statement: "The fixture method is source grounded.", source_papers: ["paper_fixture"], evidence_refs: [{ paper_id: "paper_fixture", document_id: "doc_fixture", evidence_id: "ev_fixture" }], origin: "AUTHOR_EXPLICIT", verification_status: "UNVERIFIED" }], themes: [], methods: [], agreements: [], contradictions: [], research_gaps: [], limitations: [], future_directions: [], papers: [], coverage: { sufficient: true, covered_concepts: ["retrieval"], missing_concepts: [], relevant_paper_ids: ["paper_fixture"], evidence_count: 1, summary: "Fixture coverage." }, discovery_queries: ["retrieval methods"], candidate_count: 1, selected_count: 1 } }) }));
  await page.route("**/api/papers/paper_fixture/evidence/ev_fixture", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "ev_fixture", paper_id: "paper_fixture", document_id: "doc_fixture", evidence_type: "PARAGRAPH", source_text: "The fixture method is source grounded.", page: 1, section_id: "sec_001", paragraph_id: "para_001", equation_id: null, source_region: null }) }));
  await page.goto("/workspaces");
  await page.getByLabel("Create workspace").fill("Fixture workspace");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/workspaces\/workspace_fixture/);
  await expect(page.getByRole("heading", { name: "Fixture workspace" })).toBeVisible();
  await page.getByLabel("Add ingested paper ID").fill("paper_a");
  await page.getByRole("button", { name: "Add paper" }).click();
  await page.getByLabel("Select Paper A").check();
  await page.getByLabel("Select Paper B").check();
  await page.getByRole("button", { name: /Compare selected/ }).click();
  await expect(page.getByText("Comparison IR", { exact: true })).toBeVisible();
  await page.goto("/research");
  await page.getByLabel("Research question").fill("Which methods improve retrieval?");
  await page.getByRole("button", { name: "Start evidence search" }).click();
  await expect(page).toHaveURL(/research\/research_fixture/);
  await expect(page.getByText("COMPLETED", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /paper_fixture · ev_fixture/ }).click();
  await expect(page.getByRole("dialog", { name: "Research evidence" })).toContainText("fixture method");
});

test("ingestion failure is visible and does not navigate", async ({ page }) => {
  await page.route("**/api/papers/ingest", async (route) => route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "Invalid arXiv identifier." }) }));
  await page.goto("/");
  await page.getByLabel("arXiv URL or identifier").fill("not-an-arxiv-id");
  await page.getByRole("button", { name: "Open visual reader" }).click();
  await expect(page.locator(".error-card")).toContainText("could not prepare");
  await expect(page).toHaveURL("http://127.0.0.1:3000/");
});

test("plain-text ingestion failures retain the upstream reason", async ({ page }) => {
  await page.route("**/api/papers/ingest", async (route) => route.fulfill({ status: 502, contentType: "text/plain", body: "arXiv is temporarily unavailable." }));
  await page.goto("/");
  await page.getByLabel("arXiv URL or identifier").fill("1706.03762");
  await page.getByRole("button", { name: "Open visual reader" }).click();
  await expect(page.locator(".error-card")).toContainText("arXiv is temporarily unavailable.");
  await expect(page.locator(".error-card")).not.toContainText("Request failed.");
});
