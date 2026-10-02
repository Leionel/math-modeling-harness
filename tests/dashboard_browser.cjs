/* Optional browser regression. Start dashboard/server.py against a disposable
 * initialized project; run with Playwright available through NODE_PATH.
 * node tests/dashboard_browser.cjs URL OUTPUT_DIRECTORY
 */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

(async () => {
  const url = process.argv[2];
  const output = process.argv[3];
  assert.ok(url && output, "provide URL and screenshot output directory");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHANNEL
      ? { channel: process.env.PLAYWRIGHT_CHANNEL }
      : {}),
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      permissions: ["clipboard-read", "clipboard-write"],
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(url);
    await page.locator(".action").waitFor();
    await page.screenshot({
      path: path.join(output, "overview.png"),
      scale: "css",
    });
    await page
      .getByRole("button", { name: "复制检查命令", exact: true })
      .click();
    assert.match(
      await page.evaluate(() => navigator.clipboard.readText()),
      /harness'? '?check'? '?M1'? '?--project/,
    );
    for (const nav of [
      "题目与模型",
      "实验与验证",
      "论文与图表",
      "环境与来源",
      "成果中心",
    ]) {
      await page
        .locator("#nav")
        .getByRole("button", { name: nav, exact: true })
        .click();
      assert.ok(await page.locator("h1").isVisible());
    }
    await page.locator("#content [data-kind=artifact]").first().click();
    assert.ok(
      await page
        .locator("#inspector")
        .getByText("新鲜度 / 生命周期", { exact: true })
        .isVisible(),
    );
    await page.screenshot({
      path: path.join(output, "deliverables.png"),
      scale: "css",
    });
    await page
      .getByRole("textbox", { name: "搜索产物" })
      .fill("definitely-no-artifact");
    assert.ok(await page.locator(".empty").isVisible());
    await page.getByRole("textbox", { name: "搜索产物" }).fill("");
    await page.locator("[data-filter=paper]").click();
    await page.locator("[data-filter=all]").click();
    await page.locator("#theme").click();
    assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
    await page.locator("#lang").click();
    assert.ok(
      await page
        .getByRole("heading", { name: "Deliverables", exact: true })
        .isVisible(),
    );
    await page.locator("#lang").click();
    await page.locator("#theme").click();
    await page.locator("#theme").click();
    assert.equal(
      await page.locator("html").getAttribute("data-theme"),
      "light",
    );
    await page.locator("#pause").click();
    assert.equal(await page.locator("#connection").textContent(), "已暂停");
    await page.locator("#pause").click();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: path.join(output, "mobile.png"),
      scale: "css",
    });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      true,
    );
    await page.route("**/api/snapshot", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: '{"error":"test connection failure"}',
      }),
    );
    await page.locator("#refresh").click();
    await page
      .getByRole("alert")
      .getByText("快照请求失败：test connection failure")
      .waitFor();
    assert.ok(
      await page
        .getByRole("heading", { name: "成果中心", exact: true })
        .isVisible(),
    );
    await page.unroute("**/api/snapshot");
    const actual = await (await page.request.get(url + "/api/snapshot")).json();
    await page.route("**/api/snapshot", (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ...actual,
          gate_status: "ERROR",
          status_errors: ["test invalid manifest"],
          gates: actual.gates.map((g) => ({ ...g, state: "unknown" })),
        }),
      }),
    );
    await page.locator("#refresh").click();
    await page.getByRole("alert").getByText("test invalid manifest").waitFor();
    await page
      .locator("#nav")
      .getByRole("button", { name: "概览", exact: true })
      .click();
    assert.equal(await page.locator("h1").textContent(), "先恢复项目状态读取");
    assert.deepEqual(errors, []);
    console.log(
      "Dashboard browser regression passed: navigation, inspector, search, filters, copy, themes, language, pause, mobile, transport and state errors.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
