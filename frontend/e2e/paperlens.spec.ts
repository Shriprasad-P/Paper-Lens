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
  await page.route("**/api/papers/ingest", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "paper_fixture" }) }));
  await page.route("**/api/papers/paper_fixture/reader", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(readerFixture) }));
  await page.route("**/api/papers/paper_fixture/source", async (route) => route.fulfill({ status: 200, contentType: "application/pdf", body: "%PDF-fixture" }));
  await page.route("**/api/papers/paper_fixture/evidence/ev_fixture", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "ev_fixture", paper_id: "paper_fixture", document_id: "doc_fixture", evidence_type: "PARAGRAPH", source_text: "The fixture method is source grounded.", page: 1, section_id: "sec_001", paragraph_id: "para_001", equation_id: null, source_region: null }) }));
  await page.route("**/api/papers/paper_fixture/chat/sessions", async (route) => route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ session_id: "session_fixture", paper_id: "paper_fixture", document_id: "doc_fixture", document_hash: "hash", created_at: new Date().toISOString(), updated_at: new Date().toISOString() }) }));
  await page.route("**/api/papers/paper_fixture/chat/sessions/session_fixture", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session: { id: "session_fixture", paper_id: "paper_fixture", document_id: "doc_fixture", document_hash: "hash", created_at: new Date().toISOString(), updated_at: new Date().toISOString() }, messages: [] }) }));
  await page.goto("/");
  await page.getByLabel("arXiv URL or identifier").fill("1706.03762");
  await page.getByRole("button", { name: "Open visual reader" }).click();
  await expect(page).toHaveURL(/papers\/paper_fixture/);
  await expect(page.getByRole("heading", { name: /Attention Is All You Need/ })).toBeVisible();
  await expect(page.getByTitle("Original paper PDF")).toBeVisible();
  await page.getByRole("region", { name: "Method" }).getByRole("button", { name: "View evidence for Method summary" }).click();
  await expect(page.getByRole("dialog")).toContainText("fixture method");
  await page.getByRole("button", { name: "Open Paper Chat" }).click();
  await expect(page.getByText("Paper Chat", { exact: true })).toBeVisible();
});

test("workspace and research entry points remain navigable without live providers", async ({ page }) => {
  await page.route("**/api/workspaces", async (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "workspace_fixture", name: "Fixture workspace", created_at: new Date().toISOString(), updated_at: new Date().toISOString() }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/research/runs", async (route) => route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ run: { id: "research_fixture", status: "CREATED" } }) }));
  await page.goto("/workspaces");
  await page.getByLabel("Create workspace").fill("Fixture workspace");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/workspaces\/workspace_fixture/);
  await page.goto("/research");
  await page.getByLabel("Research question").fill("Which methods improve retrieval?");
  await page.getByRole("button", { name: "Start evidence search" }).click();
  await expect(page).toHaveURL(/research\/research_fixture/);
});

test("ingestion failure is visible and does not navigate", async ({ page }) => {
  await page.route("**/api/papers/ingest", async (route) => route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "Invalid arXiv identifier." }) }));
  await page.goto("/");
  await page.getByLabel("arXiv URL or identifier").fill("not-an-arxiv-id");
  await page.getByRole("button", { name: "Open visual reader" }).click();
  await expect(page.locator(".error-card")).toContainText("could not prepare");
  await expect(page).toHaveURL("http://127.0.0.1:3000/");
});
