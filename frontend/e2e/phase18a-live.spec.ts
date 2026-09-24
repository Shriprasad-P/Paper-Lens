import { expect, test, type Request, type Response } from "@playwright/test";
import fs from "node:fs";

const password = process.env.PAPERLENS_E2E_PASSWORD;

test.describe("Phase 18A real-provider real-paper closure", () => {
  test.skip(!password, "Set PAPERLENS_E2E_PASSWORD to run the real no-mock staging validation.");

  test("Ollama onboarding, paper reader, evidence, chat, research, and protection", async ({ page }) => {
    test.setTimeout(30 * 60 * 1000);
    const email = process.env.PAPERLENS_E2E_EMAIL ?? `phase18a-${Date.now()}@example.test`;
    const observations: Record<string, unknown> = {
      paper: "1406.2661",
      provider: "ollama/qwen3:4b + nomic-embed-text",
      mocks: false,
      email_domain: email.split("@")[1],
    };
    const failedRequests: string[] = [];
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    const timings: Record<string, number> = {};
    const started = new Map<string, number>();
    let paperId = "";
    let readerPayload: Record<string, unknown> | null = null;
    let chatPayload: Record<string, unknown> | null = null;

    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("request", (request: Request) => { if (request.url().includes("/api/")) started.set(`${request.method()} ${request.url()}`, Date.now()); });
    page.on("requestfinished", (request: Request) => {
      const key = `${request.method()} ${request.url()}`;
      const begin = started.get(key);
      if (begin) timings[request.url()] = Math.max(timings[request.url()] ?? 0, Date.now() - begin);
    });
    page.on("requestfailed", (request: Request) => failedRequests.push(`${request.failure()?.errorText ?? "failed"} ${request.method()} ${request.url()}`));
    page.on("response", async (response: Response) => {
      const url = response.url();
      if (url.includes("/api/") && response.status() >= 500) failedRequests.push(`${response.status()} ${response.request().method()} ${url}`);
      try {
        if (url.includes("/api/papers/") && url.includes("/reader") && response.ok()) readerPayload = await response.json() as Record<string, unknown>;
        if (url.includes("/messages") && response.request().method() === "POST" && response.ok()) chatPayload = await response.json() as Record<string, unknown>;
      } catch { /* request may not be JSON */ }
    });

    const loginStarted = Date.now();
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sign in to PaperLens" })).toBeVisible({ timeout: 20_000 });
    if (!process.env.PAPERLENS_E2E_EMAIL) {
      await page.getByRole("button", { name: "Need an account? Create one" }).click();
      await expect(page.getByRole("heading", { name: "Create your PaperLens account" })).toBeVisible();
      await page.getByLabel("Email").fill(email);
      await page.getByLabel("Password").fill(password!);
      await page.getByRole("button", { name: "Create account", exact: true }).click();
    } else {
      await page.getByLabel("Email").fill(email);
      await page.getByLabel("Password").fill(password!);
      await page.getByRole("button", { name: "Sign in", exact: true }).click();
    }
    await expect(page).toHaveURL(/\/setup\/provider/, { timeout: 30_000 });
    timings.auth_ms = Date.now() - loginStarted;
    observations.auth = "PASS";

    const providerStarted = Date.now();
    await expect(page.getByRole("heading", { name: "Choose your AI provider" })).toBeVisible();
    await expect(page.getByLabel("Base URL")).toHaveValue("http://127.0.0.1:11434");
    await expect(page.getByLabel("Generation model")).toHaveValue("qwen3:4b");
    await expect(page.getByLabel("Embedding model")).toHaveValue("nomic-embed-text");
    await page.getByRole("button", { name: "Save & continue" }).click();
    await expect(page).toHaveURL(/\/library/, { timeout: 180_000 });
    timings.provider_setup_ms = Date.now() - providerStarted;
    observations.provider_setup = "PASS";

    await page.goto("/workspaces");
    await page.getByLabel("Create workspace").fill(`Phase 18A ${Date.now()}`);
    await page.getByRole("button", { name: "Create workspace", exact: true }).click();
    await expect(page).toHaveURL(/\/workspaces\/workspace_/);
    observations.workspace = "PASS";

    await page.goto("/library");
    await page.getByLabel("Paper identifier, citation, or URL").fill("1406.2661");
    const ingestStarted = Date.now();
    await page.getByRole("button", { name: "Open Interactive Paper" }).click();
    await page.waitForURL(/\/papers\/paper_/, { timeout: 15 * 60 * 1000 });
    timings.ingestion_ms = Date.now() - ingestStarted;
    paperId = page.url().match(/\/papers\/(paper_[^/?#]+)/)?.[1] ?? "";
    expect(paperId).toMatch(/^paper_/);
    observations.paper_id = paperId;
    await expect(page.getByRole("heading", { name: /Generative Adversarial Networks/ })).toBeVisible({ timeout: 120_000 });
    await expect(page.locator(".paper-status")).toHaveText(/COMPLETED|PARSED/);
    observations.ingestion = "PASS";

    await expect(page.locator(".interactive-paper")).toBeVisible({ timeout: 120_000 });
    await expect(page.getByRole("heading", { name: "Paper in one minute" })).toBeVisible();
    observations.reader = "PASS";
    const readerEnvelope = readerPayload as unknown as Record<string, unknown> | null;
    const interactive = record(readerEnvelope?.["interactive_paper"]);
    const blocks = Array.isArray(interactive?.blocks) ? interactive.blocks as Record<string, unknown>[] : [];
    expect(interactive?.schema_version).toBe("interactive-paper-v1.1");
    expect(blocks.length).toBeGreaterThan(0);
    observations.reader_schema = interactive?.schema_version;
    observations.block_count = blocks.length;
    observations.block_types = [...new Set(blocks.map((block) => String(block.type)))];
    observations.document_id = interactive?.document_id ?? record(readerEnvelope?.["document"])?.id;
    observations.source_hash = interactive?.source_hash;
    observations.document_hash = interactive?.document_hash;

    const analyzeButton = page.getByRole("button", { name: "Analyze paper" });
    if (!(await analyzeButton.isVisible().catch(() => false))) {
      await page.locator("details.source-analysis summary").click().catch(() => undefined);
    }
    if (await analyzeButton.isVisible().catch(() => false)) {
      const analysisStarted = Date.now();
      await analyzeButton.click();
      await expect(page.getByRole("button", { name: "Analyzing…" })).toBeHidden({ timeout: 15 * 60 * 1000 });
      timings.analysis_ms = Date.now() - analysisStarted;
      observations.analysis = "PASS";
    } else {
      observations.analysis = "NOT_APPLICABLE";
    }
    await expect(page.locator(".interactive-paper")).toBeVisible({ timeout: 120_000 });

    const nav = page.locator("button.reader-nav-item");
    await expect(nav.first()).toBeVisible();
    await nav.nth(1).click().catch(() => nav.first().click());
    observations.outline_navigation = "PASS";

    await expect(page.locator(".visual-diagram").first()).toBeVisible({ timeout: 90_000 });
    const archifyFrame = page.locator("iframe.archify-frame").first();
    const flowNode = page.locator(".react-flow__node").first();
    if (await archifyFrame.count()) {
      await expect(archifyFrame).toBeVisible();
      observations.archify = "PASS";
    } else {
      await expect(flowNode).toBeVisible();
      observations.archify = "FALLBACK_FLOW";
    }
    observations.visual = "PASS";
    const visualNode = page.locator("button.visual-node-control").first();
    if (await visualNode.count()) {
      await visualNode.click();
      await expect(page.locator(".visual-detail").first()).toBeVisible();
      await page.locator(".visual-detail").first().getByRole("button", { name: /View source evidence/ }).click();
      await expect(page.getByRole("dialog")).toContainText("Evidence /");
      observations.visual_evidence = "PASS";
      await page.getByRole("button", { name: "Close evidence" }).click();
    }

    const equation = page.locator(".interactive-equation").first();
    await expect(equation).toBeVisible();
    expect((await equation.locator(".katex").count()) + (await equation.locator(".equation-fallback").count())).toBeGreaterThan(0);
    observations.equation = "PASS";
    await equation.getByRole("button", { name: /View source evidence/ }).click();
    await expect(page.getByRole("dialog")).toContainText("Evidence /");
    await page.getByRole("button", { name: "Close evidence" }).click();
    observations.equation_evidence = "PASS";

    const ask = page.getByRole("button", { name: /Ask about this|Ask PaperLens/ }).first();
    await ask.click();
    await expect(page.getByLabel("Question")).toBeVisible();
    await page.getByLabel("Question").fill("What does this paper propose?");
    const chatStarted = Date.now();
    await page.getByRole("button", { name: "Ask PaperLens" }).last().click();
    await expect(page.locator(".chat-assistant").last()).toBeVisible({ timeout: 180_000 });
    timings.chat_ms = Date.now() - chatStarted;
    await expect(page.locator(".chat-citations button").first()).toBeVisible({ timeout: 60_000 });
    observations.chat = "PASS";
    const chatEnvelope = chatPayload as unknown as Record<string, unknown> | null;
    observations.chat_status = chatEnvelope?.["status"] ?? record(chatEnvelope?.["message"])?.["status"] ?? null;
    await page.locator(".chat-citations button").first().click();
    await expect(page.getByRole("dialog")).toContainText("Evidence /");
    await page.getByRole("button", { name: "Close evidence" }).click();
    observations.chat_citation = "PASS";

    await page.reload();
    await expect(page.locator(".interactive-paper")).toBeVisible({ timeout: 120_000 });
    await expect(page.getByRole("button", { name: /View source evidence/ }).first()).toBeVisible();
    observations.reload = "PASS";

    await page.setViewportSize({ width: 390, height: 844 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 8);
    expect(overflow).toBeFalsy();
    observations.mobile = "PASS";
    await page.setViewportSize({ width: 1280, height: 800 });

    await page.goto("/research");
    await page.getByLabel("Research question").fill("Which ideas explain adversarial generative modeling?");
    await page.getByLabel("Depth").selectOption("QUICK");
    await page.getByRole("button", { name: "Start evidence search" }).click();
    await page.waitForURL(/\/research\/research_/, { timeout: 60_000 });
    await expect(page.locator(".run-status")).toBeVisible();
    let researchStatus = "";
    await expect.poll(async () => {
      researchStatus = (await page.locator(".run-status").getAttribute("data-status")) ?? "";
      return researchStatus;
    }, { timeout: 20 * 60 * 1000, intervals: [2_500, 5_000, 10_000] }).toMatch(/COMPLETED|FAILED|CANCELLED/);
    observations.research_worker = researchStatus === "COMPLETED" ? "PASS" : "FAIL_SAFE_TERMINAL";
    observations.research_status = researchStatus;
    if (researchStatus === "COMPLETED") {
      await expect(page.getByRole("heading", { name: "What the selected literature supports" })).toBeVisible();
    } else {
      observations.research_failure = await page.locator(".event-timeline li").last().innerText().catch(() => "terminal failure without timeline text");
    }

    await page.goto("/library");
    await page.getByLabel("Paper identifier, citation, or URL").fill("not-an-arxiv-id");
    await page.getByRole("button", { name: "Open Interactive Paper" }).click();
    await expect(page.locator(".error-card")).toContainText(/could not prepare|needs a DOI|recognizable title/);
    await expect(page.locator(".error-card")).not.toContainText("Traceback");
    observations.controlled_failure = "PASS";

    await page.getByRole("button", { name: "Log out", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Sign in to PaperLens" })).toBeVisible();
    observations.logout = "PASS";
    await page.goto(`/papers/${paperId}`);
    await expect(page.getByRole("heading", { name: "Sign in to PaperLens" })).toBeVisible();
    await expect(page.locator(".interactive-paper")).toHaveCount(0);
    observations.protected_route = "PASS";

    observations.timings_ms = timings;
    observations.failed_api_or_network = failedRequests;
    observations.page_errors = pageErrors;
    observations.console_errors = consoleErrors;
    const outPath = process.env.PHASE18A_OBSERVATIONS_PATH ?? "/tmp/paperlens-phase18a-observations.json";
    fs.writeFileSync(outPath, JSON.stringify(observations, null, 2));
    await test.info().attach("phase18a-observations", { body: JSON.stringify(observations, null, 2), contentType: "application/json" });
  });
});

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}
