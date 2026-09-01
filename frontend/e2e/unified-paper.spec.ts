import { expect, test } from "@playwright/test";

const password = process.env.PAPERLENS_E2E_PASSWORD;

test.describe("Phase 17 unified interactive paper", () => {
  test.skip(!password, "Set PAPERLENS_E2E_PASSWORD to run against a real PaperLens API.");

  test("login, ingest, read unified paper, inspect evidence, and ask a contextual question", async ({ page }) => {
    test.setTimeout(12 * 60 * 1000);
    const email = process.env.PAPERLENS_E2E_EMAIL ?? `phase17-${Date.now()}@example.test`;
    const paperIdPattern = /\/papers\/(paper_[^/?]+)/;

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sign in to PaperLens" })).toBeVisible();
    if (!process.env.PAPERLENS_E2E_EMAIL) {
      await page.getByRole("button", { name: "Need an account? Create one" }).click();
      await page.getByLabel("Email").fill(email);
      await page.getByLabel("Password").fill(password!);
      await page.getByRole("button", { name: "Create account", exact: true }).click();
    } else {
      await page.getByLabel("Email").fill(email);
      await page.getByLabel("Password").fill(password!);
      await page.getByRole("button", { name: "Sign in", exact: true }).click();
    }
    await expect(page.getByText(`Signed in as ${email}`)).toBeVisible();

    await page.goto("/");
    await page.getByLabel("arXiv URL or identifier").fill("1406.2661");
    await page.getByRole("button", { name: "Open visual reader" }).click();
    await page.waitForURL(paperIdPattern, { timeout: 180_000 });
    await expect(page.getByRole("heading", { name: /Generative Adversarial Networks/ })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("heading", { name: "Paper in one minute" })).toBeVisible({ timeout: 60_000 });

    const methodNav = page.locator("button.reader-nav-item", { hasText: /How it works|Method|Experiments|Results|Limitations/ }).first();
    if (await methodNav.count()) {
      await methodNav.click();
    }
    const node = page.getByRole("button", { name: /Encoder|Generator|Discriminator|Dataset|Evaluation|Attention|Proposed method/ }).first();
    if (await node.count()) {
      await node.click();
      const nodeEvidence = page.getByRole("button", { name: /View source evidence/ }).first();
      await expect(nodeEvidence).toBeVisible();
      await nodeEvidence.click();
      await expect(page.getByRole("dialog")).toContainText("Evidence /");
      await page.getByRole("button", { name: "Close evidence" }).click();
    } else {
      await page.getByRole("button", { name: /View source evidence/ }).first().click();
      await expect(page.getByRole("dialog")).toContainText("Evidence /");
      await page.getByRole("button", { name: "Close evidence" }).click();
    }

    const equation = page.locator(".interactive-equation").first();
    if (await equation.count()) {
      await expect(equation).toBeVisible();
    }
    const figureOrTable = page.locator(".artifact-card").first();
    if (await figureOrTable.count()) {
      await expect(figureOrTable).toBeVisible();
    }

    const before = page.url();
    await page.getByRole("button", { name: "Ask PaperLens" }).first().click();
    await page.getByLabel("Question").fill("What does this paper propose?");
    await page.getByRole("button", { name: "Ask PaperLens" }).last().click();
    await expect(page.locator(".chat-assistant").last()).toBeVisible({ timeout: 180_000 });
    expect(page.url()).toBe(before);
  });
});
