// Smoke test of the stage demo in a real browser: persona login, upload, live GR release,
// clerk view and dashboard, supplier payment assistant (offline), auditor chain check.
// The backend is a fresh seeded database (see playwright.config.ts), so the order below matters.
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DEMO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../demo/invoices");

async function signInAs(page: Page, name: string) {
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

test.describe.configure({ mode: "serial" });

let invoiceUrl = "";

test("supplier uploads an invoice before the goods arrive: blocked (S04)", async ({ page }) => {
  await signInAs(page, "Hetal Shah"); // Navrang Packaging Works
  await page.goto("/upload");
  await page.getByLabel("Invoice file").setInputFiles(path.join(DEMO, "S04_packaging_missing_gr.pdf"));
  await page.getByRole("button", { name: "Upload and check" }).click();
  await expect(page).toHaveURL(/\/invoices\/\d+$/);
  invoiceUrl = new URL(page.url()).pathname;
  await expect(page.getByRole("heading", { name: "NPW-311" })).toBeVisible();
  await expect(page.getByText(/no goods receipt has been posted/i).first()).toBeVisible();
});

test("stores posts the goods receipt; Duly re-checks and releases the invoice", async ({ page }) => {
  await signInAs(page, "Imran Shaikh");
  await page.goto("/receiving");
  const card = page.locator("section.po-card", { has: page.getByRole("heading", { name: "4500001004" }) });
  await card.getByLabel("Quantity received for PKG-FFS-25").fill("20000");
  await card.getByRole("button", { name: "Post goods receipt" }).click();
  await expect(card.getByRole("status")).toContainText("1 released from block");

  await signInAs(page, "Asha Kulkarni");
  await page.goto(invoiceUrl);
  await expect(page.getByText(/Awaiting L1 Finance Manager/).first()).toBeVisible();
});

test("clerk dashboard shows live KPIs from the seeded history", async ({ page }) => {
  await signInAs(page, "Asha Kulkarni");
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Exceptions dashboard" })).toBeVisible();
  await expect(page.getByText(/touchless rate/i).first()).toBeVisible();
  await expect(page.getByText(/duplicates prevented/i).first()).toBeVisible();
});

test("supplier asks the payment assistant (offline) about INV/0042", async ({ page }) => {
  await signInAs(page, "Dinesh Patel"); // Kesar Engineering Spares
  await page.goto("/portal");
  await page.getByRole("button", { name: "Payment assistant" }).click();
  const chat = page.getByRole("region", { name: "Where is my payment?" });
  await chat.getByRole("textbox").fill("When will I get paid for INV/0042?");
  await chat.getByRole("button", { name: "Ask" }).click();
  await expect(chat.getByText(/Expected payment/).first()).toBeVisible();
});

test("auditor verifies the tamper-evident audit chain", async ({ page }) => {
  await signInAs(page, "Meera Iyer");
  await page.goto("/audit");
  await page.getByRole("button", { name: "Verify chain" }).click();
  await expect(page.getByRole("heading", { name: "Chain verified" })).toBeVisible();
});
