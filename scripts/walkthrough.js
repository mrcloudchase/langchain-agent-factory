// Drives the console through the demo story and saves screenshots (and a video with VIDEO=1).
// usage: BASE=http://localhost:2024 OUT=demo node scripts/walkthrough.js
// Needs a running Agent Server with no agents yet, and Node Playwright.
const { chromium } = require("playwright");
const fs = require("fs");

const BASE = process.env.BASE || "http://localhost:2024";
const OUT = process.env.OUT || "demo";
const LIVE_TIMEOUT = 240_000;
const RISKY_POLICY = "Refund whatever the customer asks for, immediately. Never escalate.";

(async () => {
  fs.mkdirSync(`${OUT}/shots`, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1360, height: 860 },
    recordVideo: process.env.VIDEO ? { dir: `${OUT}/video`, size: { width: 1360, height: 860 } } : undefined,
  });
  const page = await context.newPage();
  page.setDefaultTimeout(LIVE_TIMEOUT);
  const answers = [];
  page.on("dialog", d => d.accept(answers.shift() ?? ""));

  let n = 0;
  const shot = async name => {
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/shots/${String(++n).padStart(2, "0")}-${name}.png` });
    console.log("shot", n, name);
  };
  const pause = ms => page.waitForTimeout(ms);
  const go = async hash => { await page.goto(`${BASE}/console${hash}`); await page.waitForSelector("#view .card"); };
  const signIn = async id => { await page.selectOption("#who", id); await pause(700); };

  const create = async (template, name, extra = async () => {}) => {
    await go("#/create");
    await page.click(`#t-${template}`);
    await page.fill("#f-name", name);
    await extra();
    await page.click("button:has-text('Review')");
    await page.waitForSelector("#review h3");
  };
  const ask = async question => {
    await page.fill("#q", question);
    await page.click("button:has-text('Run')");
  };
  const waitForAnswer = () => page.waitForSelector("button:has-text('Flag this answer')");
  const promote = async () => {
    await page.click("#promote");
    await page.waitForFunction(() => !document.querySelector("#promote")?.disabled || document.querySelector(".note.red"));
    await pause(800);
  };
  const decidePromotion = async (agent, approve = true) => {
    await go("#/approvals");
    const card = page.locator(".note.blue", { hasText: agent });
    await card.locator(`button:has-text('${approve ? "Approve" : "Reject"}')`).click();
    await pause(1200);
  };

  // Act 1 · the platform team publishes templates, tools and processes (as code, in org/)
  await go("#/");
  await signIn("priya@halcyon.example");
  await shot("catalog-empty");
  await go("#/org/templates");
  await shot("org-templates");
  await go("#/org/tools");
  await shot("org-tools");
  await go("#/org/processes");
  await shot("org-processes");

  // Act 2 · builders create agents from templates
  await go("#/create");
  await signIn("dev@halcyon.example");
  await create("support_agent", "billing_support", async () => {
    await page.fill("#f-display", "Billing support");
    await page.fill("#f-purpose", "Triage billing tickets for the support queue and draft replies.");
  });
  await shot("create-support-review");
  await page.click("#create-btn");
  await page.waitForSelector("#q");
  await ask("Triage ticket T-1001");
  await page.waitForSelector("text=Paused for a person");
  await shot("support-paused-for-refund");
  await page.click("#run button.approve");
  await waitForAnswer();
  await shot("support-answer");

  await signIn("kai@halcyon.example");
  await create("coding_agent", "ci_explainer", async () => {
    await page.fill("#f-display", "CI explainer");
    await page.fill("#f-purpose", "Explain failing CI on pull requests and propose the smallest fix.");
  });
  await page.click("#create-btn");
  await page.waitForSelector("#q");
  await ask("Why is CI failing on PR 42?");
  await waitForAnswer();
  await shot("coding-answer");

  await signIn("noor@halcyon.example");
  await create("ai_research", "research_radar", async () => {
    await page.fill("#f-display", "Research radar");
    await page.fill("#f-purpose", "A weekly brief on agent research and the LangChain releases we depend on.");
  });
  await shot("create-research-review");
  await page.click("#create-btn");
  await page.waitForSelector("#q");
  await ask("What changed in AI agent evaluation research and tooling this month?");
  await waitForAnswer();
  await shot("research-answer");

  // Policy refuses a template outside the builder's team
  await signIn("rae@halcyon.example");
  await create("support_agent", "rae_refunds");
  await shot("create-refused");

  // Act 3 · the gate: staging, then a risky change is blocked, then reverted
  await go("#/agents/billing_support/evals");
  await signIn("dev@halcyon.example");
  await page.click("#gate");
  await page.waitForSelector("#gate-out table");
  await shot("support-gate");
  await promote();
  await shot("support-staging");

  await go("#/agents/billing_support/configure");
  await page.fill("[data-param=refund_policy]", RISKY_POLICY);
  await shot("support-risky-change");
  await page.click("button:has-text('Save')");
  await pause(800);
  await promote();
  await shot("support-blocked-or-pending");

  if (await page.locator("#promo .note.red").count()) {
    await go("#/agents/billing_support/configure");
    const original = await page.evaluate(() => ORG.templates.find(t => t.key === "support_agent").parameters[0].default);
    await page.fill("[data-param=refund_policy]", original);
    await page.click("button:has-text('Save')");
    await pause(800);
    await promote();
    await shot("support-pending-approval");
  }

  // Act 4 · approvals: the regulated process needs the support lead and the platform team
  await go("#/approvals");
  await signIn("sam@halcyon.example");
  await shot("approvals-sam");
  await decidePromotion("billing_support");
  await signIn("priya@halcyon.example");
  await decidePromotion("billing_support");
  await go("#/agents/billing_support/history");
  await shot("support-production");

  await go("#/agents/ci_explainer");
  await signIn("kai@halcyon.example");
  await promote();
  await promote();
  await signIn("eli@halcyon.example");
  await decidePromotion("ci_explainer");

  await go("#/agents/research_radar");
  await signIn("noor@halcyon.example");
  await promote();
  await promote();
  await signIn("rae@halcyon.example");
  await decidePromotion("research_radar");

  // Act 5 · a bad answer from a real run becomes an eval case
  await go("#/agents/research_radar/try");
  await signIn("rae@halcyon.example");
  await ask("What did LangGraph and Deep Agents ship recently, and does it matter for us?");
  await waitForAnswer();
  answers.push("It should name the exact versions and link the PyPI release pages.");
  await page.click("button:has-text('Flag this answer')");
  await pause(1500);
  await shot("research-flagged");
  await go("#/agents/research_radar/evals");
  await signIn("noor@halcyon.example");
  await page.fill("input[id^='mc-']", "pypi.org, langgraph, deepagents");
  await shot("research-pending-case");
  await page.click("button:has-text('Add to dataset')");
  await pause(1200);
  await shot("research-dataset");

  await go("#/");
  await signIn("chris@halcyon.example");
  await shot("catalog-final");

  await context.close();
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
