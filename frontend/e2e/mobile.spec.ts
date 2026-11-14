// Phone layout (375 x 812): the menu is a drawer, nothing scrolls sideways, and the main screens pass axe.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

test.use({ viewport: { width: 375, height: 812 }, hasTouch: true });

const SCREENS: { who: string; paths: string[] }[] = [
  { who: "Hetal Shah", paths: ["/portal", "/upload"] },
  { who: "Asha Kulkarni", paths: ["/", "/dashboard", "/queue", "/invoices", "/payments", "/suppliers", "/impact", "/trust"] },
  { who: "Rohan Mehta", paths: ["/approvals"] },
  { who: "Imran Shaikh", paths: ["/receiving"] },
  { who: "Meera Iyer", paths: ["/audit", "/controls"] },
  { who: "Sanjay Patil", paths: ["/admin/demo", "/policy"] },
];

async function signInAs(page: Page, name: string) {
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

/** Elements that stick out past the right edge without sitting inside a sideways-scrolling container. */
async function overflow(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const w = document.documentElement.clientWidth;
    const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll("body *"))) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.right <= w + 2 || el.closest(".sidebar")) continue;
      let p = el.parentElement;
      let clipped = false;
      while (p && p !== document.body) {
        const ox = getComputedStyle(p).overflowX;
        if ((ox === "auto" || ox === "hidden" || ox === "scroll") && p.getBoundingClientRect().right <= w + 2) {
          clipped = true;
          break;
        }
        p = p.parentElement;
      }
      if (!clipped) out.push(`${el.tagName.toLowerCase()}.${String(el.className).trim().split(/\s+/).join(".")}`);
    }
    return Array.from(new Set(out)).slice(0, 5);
  });
}

test("phone: drawer menu navigates and closes", async ({ page }) => {
  await signInAs(page, "Asha Kulkarni");
  const nav = page.getByRole("complementary", { name: "Main navigation" });
  await expect(nav).toBeHidden();
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(nav).toBeVisible();
  await nav.getByRole("link", { name: "Payments" }).click();
  await expect(page).toHaveURL(/\/payments/);
  await expect(nav).toBeHidden();
  await page.getByRole("button", { name: "Open menu" }).click();
  await page.keyboard.press("Escape");
  await expect(nav).toBeHidden();
});

test("phone: no screen scrolls sideways and axe finds no violations", async ({ page }) => {
  test.setTimeout(300_000);
  const problems: string[] = [];
  const check = async (label: string) => {
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/^Loading/).first()).toBeHidden();
    const o = await overflow(page);
    if (o.length) problems.push(`${label} overflows: ${o.join(", ")}`);
    const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    for (const v of axe.violations) problems.push(`${label} axe ${v.id}: ${v.nodes[0]?.target.join(" ")}`);
  };
  await page.goto("/login");
  await check("/login");
  for (const { who, paths } of SCREENS) {
    await signInAs(page, who);
    for (const path of paths) {
      await page.goto(path);
      await check(`${path} (${who})`);
    }
  }
  await signInAs(page, "Asha Kulkarni");
  await page.goto("/queue?status=open");
  await page.locator("a.row-link").first().click();
  await expect(page).toHaveURL(/\/invoices\/\d+/);
  await check("/invoices/:id");
  expect(problems, problems.join("\n")).toEqual([]);
});
