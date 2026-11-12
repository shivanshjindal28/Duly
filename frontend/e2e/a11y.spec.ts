// Automated accessibility check (axe-core, WCAG 2.1 A + AA) of the main screens for every role.
// Complements manual keyboard checks; colour contrast, labels, landmarks, ARIA and headings are covered.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const SCREENS: { who: string; paths: string[] }[] = [
  { who: "Hetal Shah", paths: ["/portal", "/upload"] }, // supplier
  { who: "Asha Kulkarni", paths: ["/", "/dashboard", "/queue", "/invoices", "/assistant", "/payments", "/bank-changes", "/suppliers", "/inbox", "/impact", "/trust", "/architecture", "/assumptions"] },
  { who: "Rohan Mehta", paths: ["/approvals"] },
  { who: "Imran Shaikh", paths: ["/receiving"] },
  { who: "Meera Iyer", paths: ["/audit", "/controls"] },
  { who: "Sanjay Patil", paths: ["/admin/demo"] },
];

async function signInAs(page: Page, name: string) {
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function scan(page: Page, label: string) {
  // Let data, charts and diagrams render before scanning.
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(/^Loading/).first()).toBeHidden();
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  return result.violations.map((v) => ({
    screen: label,
    rule: v.id,
    impact: v.impact,
    help: v.help,
    nodes: v.nodes.slice(0, 3).map((n) => `${n.target.join(" ")} :: ${n.failureSummary?.split("\n")[1] ?? ""}`),
  }));
}

test("main screens have no WCAG 2.1 AA violations", async ({ page }) => {
  test.setTimeout(300_000);
  const found: Awaited<ReturnType<typeof scan>> = [];
  await page.goto("/login");
  found.push(...(await scan(page, "/login")));
  for (const { who, paths } of SCREENS) {
    await signInAs(page, who);
    for (const path of paths) {
      await page.goto(path);
      found.push(...(await scan(page, `${path} (${who})`)));
    }
  }
  // Command palette open, invoice detail (the hero screen) and the supplier portal in Hindi.
  await signInAs(page, "Asha Kulkarni");
  await page.goto("/dashboard");
  await page.keyboard.press("Control+K");
  await page.getByRole("combobox").fill("inv");
  found.push(...(await scan(page, "command palette")));
  await page.keyboard.press("Escape");
  await page.goto("/queue?status=open");
  await page.locator("a.row-link").first().click();
  await expect(page).toHaveURL(/\/invoices\/\d+/);
  found.push(...(await scan(page, "/invoices/:id (clerk)")));
  await signInAs(page, "Hetal Shah");
  await page.goto("/portal");
  await page.getByRole("button", { name: /हिन्दी|Hindi/ }).first().click();
  found.push(...(await scan(page, "/portal (hi)")));

  for (const v of found) console.log(`[a11y] ${v.screen} · ${v.impact} · ${v.rule}: ${v.help}\n    ${v.nodes.join("\n    ")}`);
  expect(found.map((v) => `${v.screen} ${v.rule}`)).toEqual([]);
});
