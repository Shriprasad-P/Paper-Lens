import { expect, test } from "@playwright/test";

test("registration gates the library behind provider onboarding", async ({ page }) => {
  let authenticated = false;
  let configured = false;
  const user = { id: "user_onboarding", email: "onboarding@example.test", created_at: new Date().toISOString() };
  const provider = {
    id: "provider_onboarding",
    provider_type: "mlx",
    display_name: "Local MLX",
    base_url: "http://127.0.0.1:8080/v1",
    generation_model: "local-model",
    embedding_model: null,
    secret_configured: false,
    masked_secret: null,
    enabled: true,
    last_tested_at: new Date().toISOString(),
    last_test_status: "PASSED",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  await page.route("**/api/auth/me", async (route) => route.fulfill(authenticated
    ? { status: 200, contentType: "application/json", body: JSON.stringify({ user }) }
    : { status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Authentication required." }) }));
  await page.route("**/api/auth/register", async (route) => {
    authenticated = true;
    return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ user }) });
  });
  await page.route("**/api/provider-configs", async (route) => {
    if (route.request().method() === "POST") {
      configured = true;
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(provider) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(configured ? [provider] : []) });
  });
  await page.route("**/api/provider-configs/provider_onboarding/test", async (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ provider_id: provider.id, status: "PASSED", message: "Local MLX probe passed.", tested_at: new Date().toISOString() }),
  }));
  await page.route("**/api/papers", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to PaperLens" })).toBeVisible();
  await page.getByRole("button", { name: "Need an account? Create one" }).click();
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page).toHaveURL(/\/setup\/provider/);

  await page.getByRole("button", { name: /MLX local/ }).click();
  await expect(page.getByLabel("Base URL")).toHaveValue("http://127.0.0.1:8080/v1");
  await page.getByRole("button", { name: "Save & continue" }).click();
  await expect(page).toHaveURL(/\/library/);
  await expect(page.getByText("Add research paper")).toBeVisible();
});
