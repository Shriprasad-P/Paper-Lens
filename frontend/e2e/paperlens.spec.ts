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
    figures: [{ id: "fig_1", label: "Figure 1", number: "1", caption: "Architecture diagram from the paper.", page: 1, source_region: null, image_reference: null, evidence_ids: ["ev_fixture"] }],
    tables: [{ id: "tbl_1", label: "Table 1", number: "1", caption: "Benchmark comparison.", headers: ["Model", "F1"], rows: [["Ours", "0.51"], ["Baseline", "0.40"]], raw_text: null, page: 1, source_region: null, evidence_ids: ["ev_fixture"] }],
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
  interactive_paper: {
    schema_version: "interactive-paper-v1.1",
    paper_id: "paper_fixture",
    document_id: "doc_fixture",
    source_hash: "hash",
    document_hash: "hash",
    analysis_fingerprint: "fp",
    generation_mode: "assembler",
    generation_config: {},
    cache_key: "cache",
    provider: "fixture",
    model: "fixture",
    prompt_version: "v1",
    status: "READY",
    overview: "A deterministic fixture paper.",
    outline: [
      { block_id: "block_overview", title: "Paper in one minute", type: "overview" },
      { block_id: "block_method", title: "How it works", type: "method" },
    ],
    concepts: [],
    generated_at: new Date().toISOString(),
    blocks: [
      {
        id: "block_overview",
        type: "overview",
        title: "Paper in one minute",
        simplified_explanation: "A deterministic fixture paper.",
        visual: null,
        equations: [],
        figures: [],
        tables: [],
        key_points: [],
        evidence_ids: ["ev_fixture"],
        status: "READY",
        inferred: false,
        validator_status: "PASSED",
        error: null,
      },
      {
        id: "block_method",
        type: "method",
        title: "How it works",
        simplified_explanation: "The system encodes then attends.",
        visual: {
          type: "pipeline",
          title: "How the proposed method works",
          reconstructed: true,
          nodes: [
            { id: "encoder", label: "Encoder", description: "Encode inputs.", role: "model", evidence_ids: ["ev_fixture"], inferred: false, related_equation_ids: ["eq_1"], related_figure_ids: [] },
            { id: "attention", label: "Attention", description: "Attend over features.", role: "model", evidence_ids: ["ev_fixture"], inferred: false, related_equation_ids: ["eq_1"], related_figure_ids: [] },
          ],
          edges: [{ id: "e1", source: "encoder", target: "attention", label: "features", evidence_ids: ["ev_fixture"], inferred: false }],
        },
        equations: [
          {
            id: "eq_1",
            equation_id: "eq_1",
            original_expression: "L = -\\sum y_i \\log(\\hat{y}_i)",
            latex: "L = -\\sum y_i \\log(\\hat{y}_i)",
            explanation: "Cross-entropy measures how far predicted probabilities are from the labels.",
            purpose: "Training objective for the model.",
            terms: [
              { symbol: "L", meaning: "total error", evidence_ids: ["ev_fixture"] },
              { symbol: "y_i", meaning: "true target", evidence_ids: ["ev_fixture"] },
            ],
            evidence_ids: ["ev_fixture"],
            page: 1,
            section_id: "sec_001",
            related_node_ids: ["attention"],
            origin: "SIMPLIFIED",
          },
        ],
        figures: [{ figure_id: "fig_1", simplified_explanation: "The paper's architecture figure.", evidence_ids: ["ev_fixture"], reconstructed: false }],
        tables: [{ table_id: "tbl_1", simplified_explanation: "The proposed model improves F1 versus the baseline.", important_cells: [], evidence_ids: ["ev_fixture"] }],
        key_points: [],
        evidence_ids: ["ev_fixture"],
        status: "READY",
        inferred: false,
        validator_status: "PASSED",
        error: null,
      },
    ],
  },
};

test.beforeEach(async ({ page }) => {
  // Phase 18 makes authentication and provider readiness part of the normal
  // entry path. Keep deterministic reader fixtures focused on reader behavior
  // by supplying that authenticated boundary explicitly.
  await page.route("**/api/auth/me", async (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ user: { id: "user_fixture", email: "fixture@example.test", created_at: new Date().toISOString() } }),
  }));
  await page.route("**/api/provider-configs", async (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify([{
      id: "provider_fixture",
      provider_type: "ollama",
      display_name: "Fixture Ollama",
      base_url: "http://127.0.0.1:11434",
      generation_model: "qwen3:4b",
      embedding_model: "nomic-embed-text",
      secret_configured: false,
      masked_secret: null,
      enabled: true,
      last_tested_at: new Date().toISOString(),
      last_test_status: "PASSED",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }]),
  }));
});

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
  await page.goto("/library");
  await page.getByLabel("Paper identifier, citation, or URL").fill("1706.03762");
  await page.getByRole("button", { name: "Open Interactive Paper" }).click();
  await expect(page).toHaveURL(/papers\/paper_fixture/);
  await expect(page.getByRole("heading", { name: /Attention Is All You Need/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Paper in one minute" })).toBeVisible();
  await page.locator("button.reader-nav-item", { hasText: "How it works" }).click();
  await expect(page.getByRole("heading", { name: "How it works" })).toBeVisible();
  await page.getByRole("button", { name: "Attention" }).click();
  await expect(page.locator(".visual-detail").getByText("Attend over features.")).toBeVisible();
  await page.getByRole("button", { name: /View source evidence for Attention/ }).click();
  await expect(page.getByRole("dialog")).toContainText("fixture method");
  await page.getByRole("button", { name: "Close evidence" }).click();
  await expect(page.getByText("Cross-entropy measures").first()).toBeVisible();
  await expect(page.getByRole("table", { name: "Formulas used in this section" })).toContainText("Training objective for the model.");
  await expect(page.getByText("Architecture diagram from the paper.").first()).toBeVisible();
  await expect(page.getByText("Benchmark comparison.").first()).toBeVisible();
  await expect(page.getByTitle("Original paper PDF")).toBeVisible();
  await expect(page.getByTitle("Original paper PDF")).toHaveAttribute("src", /^blob:/);
  await page.getByRole("button", { name: "Ask PaperLens" }).first().click();
  await expect(page.getByText("Ask this paper", { exact: true })).toBeVisible();
  await page.getByLabel("Question").fill("Explain the method.");
  await page.getByRole("button", { name: "Ask PaperLens" }).last().click();
  await expect(page.getByText("The fixture method is source grounded.")).toBeVisible();
  await page.getByRole("button", { name: "[1]" }).click();
  await expect(page.getByRole("dialog")).toContainText("fixture method");
  await page.getByRole("button", { name: "Close evidence" }).click();
  await page.getByText("Source analysis").click();
  await page.getByRole("button", { name: "Verify analysis" }).click();
});

test("unified paper outline remains usable at a mobile width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/papers/ingest", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "paper_fixture" }) }));
  await page.route("**/api/papers/paper_fixture/reader", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(readerFixture) }));
  await page.route("**/api/papers/paper_fixture/source", async (route) => route.fulfill({ status: 200, contentType: "application/pdf", body: "%PDF-fixture" }));
  await page.goto("/library");
  await page.getByLabel("Paper identifier, citation, or URL").fill("1706.03762");
  await page.getByRole("button", { name: "Open Interactive Paper" }).click();
  await expect(page.getByRole("heading", { name: "Paper in one minute" })).toBeVisible();
  await page.getByRole("button", { name: "Show outline" }).click();
  await page.locator("button.reader-nav-item", { hasText: "How it works" }).click();
  await expect(page.getByRole("heading", { name: "How it works" })).toBeVisible();
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
  await page.route("**/api/research/runs/research_fixture", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ run: { id: "research_fixture", workspace_id: null, research_question: "Which methods improve retrieval?", status: "COMPLETED", execution_state: "COMPLETED", created_at: new Date().toISOString(), updated_at: new Date().toISOString(), completed_at: new Date().toISOString(), max_iterations: 1, max_candidates: 1, max_ingested_papers: 1, planner_provider: "fixture", planner_model: "fixture", prompt_version: "v1", schema_version: "v1" }, plan: null, queries: ["retrieval methods"], candidates: [], events: [{ id: "event_fixture", research_run_id: "research_fixture", event_type: "RUN_COMPLETED", message: "Fixture report completed.", metadata: {}, created_at: new Date().toISOString() }], coverage: { sufficient: true, covered_concepts: ["retrieval"], missing_concepts: [], relevant_paper_ids: ["paper_fixture"], evidence_count: 1, summary: "Fixture coverage." }, report: { research_question: "Which methods improve retrieval?", executive_summary: [{ claim_id: "claim_fixture", statement: "The fixture method is source grounded.", source_papers: ["paper_fixture"], evidence_refs: [{ paper_id: "paper_fixture", document_id: "doc_fixture", evidence_id: "ev_fixture" }], origin: "AUTHOR_EXPLICIT", verification_status: "UNVERIFIED" }], themes: [], methods: [], agreements: [], contradictions: [], research_gaps: [], limitations: [], future_directions: [], papers: [], coverage: { sufficient: true, covered_concepts: ["retrieval"], missing_concepts: [], relevant_paper_ids: ["paper_fixture"], evidence_count: 1, summary: "Fixture coverage." }, discovery_queries: ["retrieval methods"], candidate_count: 1, selected_count: 1 } }) }));
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
  await expect(page.locator(".run-status")).toContainText("COMPLETED");
  await page.getByRole("button", { name: /paper_fixture · ev_fixture/ }).click();
  await expect(page.getByRole("dialog", { name: "Research evidence" })).toContainText("fixture method");
});

test("ingestion failure is visible and does not navigate", async ({ page }) => {
  await page.route("**/api/papers/ingest", async (route) => route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "Invalid arXiv identifier." }) }));
  await page.goto("/library");
  await page.getByLabel("Paper identifier, citation, or URL").fill("not-an-arxiv-id");
  await page.getByRole("button", { name: "Open Interactive Paper" }).click();
  await expect(page.locator(".error-card")).toContainText("Invalid arXiv identifier.");
  await expect(page).toHaveURL("http://127.0.0.1:3000/library");
});

test("plain-text ingestion failures retain the upstream reason", async ({ page }) => {
  await page.route("**/api/papers/ingest", async (route) => route.fulfill({ status: 502, contentType: "text/plain", body: "arXiv is temporarily unavailable." }));
  await page.goto("/library");
  await page.getByLabel("Paper identifier, citation, or URL").fill("1706.03762");
  await page.getByRole("button", { name: "Open Interactive Paper" }).click();
  await expect(page.locator(".error-card")).toContainText("arXiv is temporarily unavailable.");
  await expect(page.locator(".error-card")).not.toContainText("Request failed.");
});
