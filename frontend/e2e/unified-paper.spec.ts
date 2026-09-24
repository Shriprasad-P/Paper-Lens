import { expect, test, type Request, type Response } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const password = process.env.PAPERLENS_E2E_PASSWORD;
test.describe("Phase 17 unified interactive paper", () => {
  test.skip(!password, "Set PAPERLENS_E2E_PASSWORD to run against a real PaperLens API.");

  test("live unmocked unified reader closure", async ({ page }) => {
    test.setTimeout(25 * 60 * 1000);
    const email = process.env.PAPERLENS_E2E_EMAIL ?? `phase17a-${Date.now()}@example.test`;
    const paperIdPattern = /\/papers\/(paper_[^/?#]+)/;
    const observations: Record<string, unknown> = {
      paper: "1406.2661",
      email_domain: email.split("@")[1],
      mocks: false,
    };
    const failedRequests: string[] = [];
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    let lastReader: Record<string, unknown> | null = null;
    let lastChat: Record<string, unknown> | null = null;

    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("requestfailed", (request: Request) => {
      failedRequests.push(`${request.failure()?.errorText ?? "failed"} ${request.method()} ${request.url()}`);
    });
    page.on("response", async (response: Response) => {
      const url = response.url();
      if (url.includes("/api/") && response.status() >= 500) {
        failedRequests.push(`${response.status()} ${response.request().method()} ${url}`);
      }
      try {
        if (url.includes("/api/papers/") && url.includes("/reader") && response.ok()) {
          lastReader = (await response.json()) as Record<string, unknown>;
        }
        if (url.includes("/messages") && response.request().method() === "POST" && response.ok()) {
          lastChat = (await response.json()) as Record<string, unknown>;
        }
      } catch {
        // Ignore non-JSON responses while capturing live API evidence.
      }
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sign in to PaperLens" })).toBeVisible({ timeout: 15_000 });
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
    await expect(page.getByText(`Signed in as ${email}`)).toBeVisible();
    observations.login = "PASS";

    await page.goto("/workspaces");
    const workspaceName = `Phase 17A ${Date.now()}`;
    await page.getByLabel("Create workspace").fill(workspaceName);
    await page.getByRole("button", { name: "Create workspace", exact: true }).click();
    await expect(page).toHaveURL(/\/workspaces\/workspace_/);
    await expect(page.getByText(workspaceName)).toBeVisible();
    observations.workspace = "PASS";

    await page.goto("/library");
    await page.getByLabel("Paper identifier, citation, or URL").fill("1406.2661");
    await page.getByRole("button", { name: "Open Interactive Paper" }).click();
    await page.waitForURL(paperIdPattern, { timeout: 180_000 });
    const paperId = page.url().match(paperIdPattern)?.[1];
    expect(paperId).toMatch(/^paper_/);
    observations.paper_id = paperId;
    await expect(page.getByRole("heading", { name: /Generative Adversarial Networks/ })).toBeVisible({ timeout: 60_000 });
    await expect(page.locator(".paper-status")).toHaveText(/COMPLETED|PARSED/);
    observations.ingestion = "PASS";

    await expect(page.locator(".interactive-paper")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("heading", { name: "Paper in one minute" })).toBeVisible({ timeout: 60_000 });
    observations.interactive_load = "PASS";

    const analyzeButton = page.getByRole("button", { name: "Analyze paper" });
    if (!(await analyzeButton.isVisible().catch(() => false))) {
      await page.locator("details.source-analysis summary").click().catch(() => undefined);
    }
    if (await analyzeButton.isVisible().catch(() => false)) {
      await analyzeButton.click();
      await expect(page.getByRole("button", { name: "Analyzing…" })).toBeHidden({ timeout: 15 * 60 * 1000 });
      await expect(page.locator(".interactive-paper")).toBeVisible({ timeout: 60_000 });
    }
    observations.analysis_clicked = !(await analyzeButton.isVisible().catch(() => false));

    const interactive = asRecord(lastReader?.["interactive_paper"]);
    expect(interactive?.schema_version).toBe("interactive-paper-v1.1");
    const blocks = Array.isArray(interactive?.blocks) ? (interactive.blocks as Record<string, unknown>[]) : [];
    expect(blocks.length).toBeGreaterThan(0);
    observations.schema_version = interactive?.schema_version;
    observations.document_id = interactive?.document_id ?? asRecord(lastReader?.["document"])?.id;
    observations.source_hash = interactive?.source_hash;
    observations.document_hash = interactive?.document_hash;
    observations.block_count = blocks.length;
    observations.block_types = [...new Set(blocks.map((block) => String(block.type)))];

    const proseBlock = blocks.find((block) => typeof block.simplified_explanation === "string" && String(block.simplified_explanation).length > 0);
    expect(proseBlock).toBeTruthy();
    observations.simplified_block = {
      id: proseBlock?.id,
      type: proseBlock?.type,
      title: proseBlock?.title,
      evidence_ids: proseBlock?.evidence_ids,
    };

    const outlineButtons = page.locator("button.reader-nav-item");
    await expect(outlineButtons.first()).toBeVisible();
    const secondOutline = outlineButtons.nth(1);
    const outlineLabel = ((await secondOutline.count()) ? await secondOutline.innerText() : await outlineButtons.first().innerText()).replace(/^\d+\s*/, "").trim();
    if (await secondOutline.count()) await secondOutline.click();
    else await outlineButtons.first().click();
    await expect(page).toHaveURL(/\/papers\/paper_/);
    expect(page.url()).not.toMatch(/\/visualiz/);
    const targetBlock = blocks.find((block) => String(block.title) === outlineLabel) ?? blocks[1] ?? blocks[0];
    if (targetBlock?.id) {
      await expect(page.locator(`#${String(targetBlock.id)}`)).toBeVisible();
      expect(page.url()).toContain(`#${String(targetBlock.id)}`);
    }
    observations.outline = "PASS";

    const visualBlock = blocks.find((block) => block.visual);
    const diagram = asRecord(visualBlock?.visual);
    await expect(page.locator(".visual-diagram").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".react-flow__node").first()).toBeVisible();
    observations.inline_visual = "PASS";
    observations.diagram_type = diagram?.diagram_type ?? null;
    observations.visual_reconstructed = diagram?.reconstructed ?? null;

    const nodeButton = page.locator("button.visual-node-control").first();
    await expect(nodeButton).toBeVisible();
    await nodeButton.click();
    await expect(page.locator(".visual-detail").first()).toBeVisible();
    await expect(page.locator(".visual-detail").first().getByRole("button", { name: /View source evidence/ })).toBeVisible();
    observations.node_interaction = "PASS";

    await page.locator(".visual-detail").first().getByRole("button", { name: /View source evidence/ }).click();
    const evidenceDialog = page.getByRole("dialog");
    await expect(evidenceDialog).toContainText("Evidence /");
    await expect(evidenceDialog).toContainText(/ev_/);
    await expect(evidenceDialog.locator(".drawer-record p").first()).not.toHaveText(/^$/);
    observations.node_evidence = "PASS";
    await page.getByRole("button", { name: "Close evidence" }).click();

    const diagramRoot = page.locator(".visual-diagram").first();
    const edgeButton = diagramRoot.locator("button.visual-edge-control").first();
    if (await edgeButton.count()) {
      await edgeButton.click();
      await expect(diagramRoot.locator(".visual-detail").first()).toBeVisible();
      const inferred = (await edgeButton.getAttribute("class"))?.includes("inferred") ?? false;
      observations.edge_interaction = "PASS";
      observations.inferred_relationship = inferred ? "PASS" : "NOT_INFERRED";
      if (inferred) await expect(page.locator(".visual-detail .provenance-inferred")).toContainText(/inferred/i);
    } else {
      observations.edge_interaction = "NOT_APPLICABLE";
      observations.inferred_relationship = "NOT_APPLICABLE";
    }

    const equationCard = page.locator(".interactive-equation").first();
    await expect(equationCard).toBeVisible();
    const katexRendered = (await equationCard.locator(".katex").count()) > 0;
    const fallbackRendered = (await equationCard.locator(".equation-fallback").count()) > 0;
    expect(katexRendered || fallbackRendered).toBeTruthy();
    observations.equation_render = katexRendered ? "PASS_KATEX" : "PASS_FALLBACK";
    const equationExplanation = (await equationCard.getByText("In simple terms").count()) > 0;
    observations.equation_explanation = equationExplanation ? "PASS" : "NOT_APPLICABLE";
    const variableBreakdown = (await equationCard.locator(".variable-list").count()) > 0;
    observations.variable_breakdown = variableBreakdown ? "PASS" : "NOT_APPLICABLE";
    await equationCard.getByRole("button", { name: /View source evidence/ }).click();
    await expect(page.getByRole("dialog")).toContainText("Evidence /");
    observations.equation_evidence = "PASS";
    await page.getByRole("button", { name: "Close evidence" }).click();
    const equationPayload = firstEquation(blocks);
    observations.node_equation_relation =
      Array.isArray(equationPayload?.related_node_ids) && (equationPayload.related_node_ids as unknown[]).length ? "PASS" : "NOT_APPLICABLE";

    const figureCard = page.locator(".interactive-paper .artifact-card").filter({ has: page.locator(".card-label", { hasText: /figure|reconstruction/i }) }).first();
    if (await figureCard.isVisible().catch(() => false)) {
      const reconstructed = (await figureCard.getByText("PaperLens reconstruction").count()) > 0;
      observations.figure = reconstructed ? "PASS_RECONSTRUCTION_LABELED" : "PASS";
    } else {
      observations.figure = "NOT_APPLICABLE";
    }

    const tableCard = page.locator(".interactive-paper .artifact-card").filter({ has: page.locator(".card-label", { hasText: /table/i }) }).first();
    if (await tableCard.isVisible().catch(() => false)) {
      observations.table = "PASS";
    } else {
      observations.table = "NOT_APPLICABLE";
    }

    const resultBlock = blocks.find((block) => block.type === "result");
    observations.result_block = resultBlock ? "PASS" : "NOT_APPLICABLE";
    if (resultBlock) {
      await page.locator("button.reader-nav-item", { hasText: String(resultBlock.title) }).first().click();
      await expect(page.locator(`#${String(resultBlock.id)}`)).toBeVisible();
    }
    const limitationBlock = blocks.find((block) => block.type === "limitation");
    observations.limitation_block = limitationBlock ? "PASS" : "NOT_APPLICABLE";
    if (limitationBlock) {
      await page.locator("button.reader-nav-item", { hasText: String(limitationBlock.title) }).first().click();
      await expect(page.locator(`#${String(limitationBlock.id)}`)).toBeVisible();
    }

    const askAbout = page.getByRole("button", { name: "Ask about this" }).first();
    if (await askAbout.count()) await askAbout.click();
    else await page.getByRole("button", { name: "Ask PaperLens" }).first().click();
    await expect(page.getByLabel("Question")).toBeVisible();
    if (await page.locator(".chat-focus").count()) {
      observations.chat_focus = "PASS";
    }
    const beforeChatUrl = page.url();
    await page.getByLabel("Question").fill("What does this paper propose?");
    await page.getByRole("button", { name: "Ask PaperLens" }).last().click();
    await expect(page.locator(".chat-assistant").last()).toBeVisible({ timeout: 180_000 });
    expect(page.url()).toBe(beforeChatUrl);
    observations.contextual_chat = "PASS";
    observations.chat_status = lastChat?.["status"] ?? asRecord(lastChat?.["message"])?.["status"] ?? null;

    const citation = page.locator(".chat-citations button").first();
    await expect(citation).toBeVisible({ timeout: 30_000 });
    await citation.click();
    await expect(page.getByRole("dialog")).toContainText("Evidence /");
    observations.chat_citation = "PASS";
    await page.getByRole("button", { name: "Close evidence" }).click();
    await page.getByRole("button", { name: "Hide PaperLens" }).click().catch(() => undefined);

    const beforeReload = page.url();
    await page.reload();
    await expect(page.locator(".interactive-paper")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("heading", { name: /Generative Adversarial Networks/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /View source evidence/ }).first()).toBeVisible();
    observations.reload = "PASS";
    observations.reload_url = page.url();
    observations.reload_same_paper = page.url().includes(String(paperId));
    if (beforeReload.includes("#")) expect(page.url()).toContain(String(paperId));

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".interactive-paper")).toBeVisible();
    const hideOriginal = page.getByRole("button", { name: /Hide original/ });
    if (await hideOriginal.isVisible().catch(() => false)) await hideOriginal.click();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 8);
    observations.responsive_overflow = overflow;
    expect(overflow).toBeFalsy();
    await expect(page.getByRole("button", { name: /Hide outline|Show outline/ })).toBeVisible();
    await page.getByRole("button", { name: /Hide outline|Show outline/ }).click();
    await expect(page.locator(".visual-diagram").first()).toBeVisible();
    await expect(page.getByRole("button", { name: /View source evidence/ }).first()).toBeVisible();
    observations.responsive = "PASS";
    await page.setViewportSize({ width: 1280, height: 800 });

    await page.goto("/library");
    await page.getByLabel("Paper identifier, citation, or URL").fill("not-an-arxiv-id");
    await page.getByRole("button", { name: "Open Interactive Paper" }).click();
    await expect(page.locator(".error-card")).toContainText("could not prepare");
    await expect(page.locator(".error-card")).not.toContainText("Traceback");
    observations.controlled_failure = "PASS";

    await page.getByRole("button", { name: "Log out", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Sign in to PaperLens" })).toBeVisible();
    observations.logout = "PASS";

    await page.goto(`/papers/${paperId}`);
    await expect(page.getByRole("heading", { name: "Sign in to PaperLens" })).toBeVisible();
    await expect(page.locator(".interactive-paper")).toHaveCount(0);
    observations.protected_route = "PASS";

    observations.failed_api_or_network = failedRequests;
    observations.page_errors = pageErrors;
    observations.console_errors = consoleErrors;
    observations.chat_payload_keys = lastChat ? Object.keys(lastChat) : [];
    const outPath = process.env.PHASE17A_OBSERVATIONS_PATH || path.join("/tmp", "paperlens-phase17a-observations.json");
    fs.writeFileSync(outPath, JSON.stringify(observations, null, 2));
    await test.info().attach("phase17a-observations", {
      body: JSON.stringify(observations, null, 2),
      contentType: "application/json",
    });
  });
});

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function firstEquation(blocks: Record<string, unknown>[]): Record<string, unknown> | null {
  for (const block of blocks) {
    const equations = Array.isArray(block.equations) ? (block.equations as Record<string, unknown>[]) : [];
    if (equations[0]) return equations[0];
  }
  return null;
}
