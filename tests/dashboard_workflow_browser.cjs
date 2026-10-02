/* Read-only regression against a project produced by examples/user_walkthrough.
 * node tests/dashboard_workflow_browser.cjs URL OUTPUT_DIRECTORY */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

(async () => {
  const [url, output] = process.argv.slice(2);
  assert.ok(url && output);
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 },
      permissions: ["clipboard-read", "clipboard-write"] });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const snapshot = await (await page.request.get(url + "/api/snapshot")).json();
    assert.equal(snapshot.question_workbench.questions[0].question_id, "q2");
    await page.goto(url);
    await page.locator(".action").waitFor();
    await page.getByRole("button", { name: "复制 bash 复查", exact: true }).click();
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    assert.ok(copied.includes(snapshot.project_root));
    assert.ok(await page.locator("#notice").getByText("已复制 bash 命令").isVisible());
    await page.locator('#nav [data-view="model"]').click();
    await page.locator('[data-kind="question"][data-id="q2"]').click();
    assert.ok(await page.locator("#inspector").getByText("raw_results.json", { exact: true }).isVisible());
    assert.ok(await page.locator("#inspector").getByText("VAL-Q2 · PASS", { exact: true }).isVisible());
    assert.ok(await page.locator("#inspector").getByText("未验证", { exact: true }).first().isVisible());
    await page.screenshot({ path: path.join(output, "question-q2.png"), scale: "css" });
    await page.locator('[data-kind="source"][data-id="authoring:model_contract"]').click();
    await page.locator("#load-source").click();
    await page.locator("#source-content pre").getByText(/MODEL-Q2/).waitFor();
    await page.getByRole("button", { name: "复制路径", exact: true }).click();
    assert.ok((await page.evaluate(() => navigator.clipboard.readText())).endsWith("model_contract.yaml"));
    await page.locator('#nav [data-view="runs"]').click();
    const log = snapshot.user_sources.find(s => s.kind === "log" && s.source_id.endsWith(":stdout"));
    assert.ok(log);
    await page.locator(`[data-kind="source"][data-id="${log.source_id}"]`).click();
    await page.locator("#load-source").click();
    await page.locator("#source-content pre").waitFor();
    assert.ok((await page.locator("#source-content pre").textContent()).length > 0);
    await page.screenshot({ path: path.join(output, "execution-log.png"), scale: "css" });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    console.log("Workflow browser regression passed: Q2, actual validation, author source, log, shell command and mobile.");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
