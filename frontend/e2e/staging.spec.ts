import { expect, test } from "@playwright/test";

const password = process.env.PAPERLENS_E2E_PASSWORD;

test.describe("Phase 16A real staging", () => {
  test.skip(!password, "Set PAPERLENS_E2E_PASSWORD to run against a real staging API.");

  test("auth, reader, evidence, chat, refresh, research, and logout work", async ({ page }) => {
    test.setTimeout(12 * 60 * 1000);
    const email = process.env.PAPERLENS_E2E_EMAIL ?? `phase16a-${Date.now()}@example.test`;
    const paperIdPattern = /\/papers\/(paper_[^/?]+)/;

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sign in to PaperLens" })).toBeVisible();
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

    await page.goto("/workspaces");
    await page.getByLabel("Create workspace").fill(`Phase 16A browser ${Date.now()}`);
    await page.getByRole("button", { name: "Create workspace", exact: true }).click();
    await expect(page).toHaveURL(/\/workspaces\/workspace_/);

    await page.goto("/");
    await page.getByLabel("arXiv URL or identifier").fill("1406.2661");
    await page.getByRole("button", { name: "Open visual reader" }).click();
    await page.waitForURL(paperIdPattern, { timeout: 180_000 });
    const paperMatch = page.url().match(paperIdPattern);
    const paperId = paperMatch?.[1];
    expect(paperId).toMatch(/^paper_/);
    await expect(page.getByRole("heading", { name: /Generative Adversarial Networks/ })).toBeVisible({ timeout: 60_000 });

    await page.locator("button.reader-nav-item", { hasText: "Paper in one minute" }).click().catch(async () => {
      await page.locator("button.reader-nav-item").first().click();
    });
    const evidenceButton = page.locator('button[aria-label^="View source evidence"], button[aria-label^="View evidence"]').first();
    await expect(evidenceButton).toBeVisible({ timeout: 30_000 });
    await evidenceButton.click();
    await expect(page.getByRole("dialog")).toContainText("Evidence /");
    await page.getByRole("button", { name: "Close evidence" }).click();

    await page.getByRole("button", { name: "Ask PaperLens" }).first().click();
    await page.getByLabel("Question").fill("What are the two models in the proposed framework?");
    await page.getByRole("button", { name: "Ask PaperLens" }).last().click();
    await expect(page.locator(".chat-assistant").last()).toContainText(/model|generat|discrimin/i, { timeout: 180_000 });
    const citation = page.locator('.chat-citations button').first();
    await expect(citation).toBeVisible();
    await citation.click();
    await expect(page.getByRole("dialog")).toContainText("Evidence /");
    await page.getByRole("button", { name: "Close evidence" }).click();

    await page.goto("/");
    await page.getByLabel("arXiv URL or identifier").fill("not-an-arxiv-id");
    await page.getByRole("button", { name: "Open visual reader" }).click();
    await expect(page.locator(".error-card")).toContainText("could not prepare");
    await expect(page.locator(".error-card")).not.toContainText("Traceback");

    await page.goto("/research");
    await page.getByLabel("Research question").fill("Which ideas explain adversarial generative modeling?");
    await page.getByLabel("Depth").selectOption("QUICK");
    await page.getByRole("button", { name: "Start evidence search" }).click();
    await page.waitForURL(/\/research\/research_/, { timeout: 30_000 });
    await page.reload();
    await expect(page.locator(".run-status")).toBeVisible();
    await expect.poll(async () => page.locator(".run-status").getAttribute("data-status"), { timeout: 8 * 60 * 1000, intervals: [2_500, 5_000, 10_000] }).toBe("COMPLETED");
    await expect(page.getByRole("heading", { name: "What the selected literature supports" })).toBeVisible();

    await page.getByRole("button", { name: "Log out", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Sign in to PaperLens" })).toBeVisible();
    await page.goto(`/papers/${paperId}`);
    await expect(page.getByRole("heading", { name: "Sign in to PaperLens" })).toBeVisible();
  });
});
