#!/usr/bin/env -S npx tsx
/**
 * Bounded, disposable Stagehand browser-agent runner.
 *
 * Usage:
 *   OPENAI_API_KEY=... npx tsx run-task.ts --url <start-url> --instruction "<task>" [options]
 *
 * Design constraints (do not relax without explicit user approval):
 * - Always launches a fresh, disposable Chrome profile under a tmp dir; never
 *   reuses or points at the user's real Chrome profile/cookies.
 * - Always runs headless, local (no Browserbase), with disableAPI: true.
 * - Always enforces maxSteps and an overall wall-clock deadline that
 *   force-closes the browser on expiry.
 * - Always closes the browser and deletes the profile dir on exit, success or not.
 * - Never logs in, submits payment, or completes a purchase/reservation unless
 *   the caller explicitly passes --allow-write (off by default). The instruction
 *   text always gets a safety suffix appended reinforcing this boundary.
 */

import { Stagehand } from "@browserbasehq/stagehand";
import { randomBytes } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

type EvaluatingPage = {
  evaluate<R = unknown, Arg = unknown>(fn: string | ((arg: Arg) => R | Promise<R>), arg?: Arg): Promise<R>;
  waitForTimeout(ms: number): Promise<void>;
};

interface Args {
  url: string;
  instruction: string;
  maxSteps: number;
  timeoutMs: number;
  model: string;
  allowWrite: boolean;
  headless: boolean;
}

function parseArgs(argv: string[]): Args {
  const args: Record<string, string> = {};
  const flags = new Set(["--allow-write", "--headed"]);
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) continue;
    if (flags.has(key)) {
      args[key.slice(2)] = "true";
      continue;
    }
    args[key.slice(2)] = argv[i + 1];
    i += 1;
  }
  if (!args.url || !args.instruction) {
    throw new Error("Usage: run-task.ts --url <start-url> --instruction \"<task>\" [--max-steps 18] [--timeout-ms 150000] [--model openai/gpt-4.1-mini] [--allow-write] [--headed]");
  }
  return {
    url: args.url,
    instruction: args.instruction,
    maxSteps: args["max-steps"] ? Number(args["max-steps"]) : 18,
    timeoutMs: args["timeout-ms"] ? Number(args["timeout-ms"]) : 150_000,
    model: args.model ?? "openai/gpt-4.1-mini",
    allowWrite: Boolean(args["allow-write"]),
    headless: !args.headed,
  };
}

const SAFETY_SUFFIX_READ_ONLY =
  " Do not sign in, create an account, save payment details, submit a purchase, complete a reservation/booking, " +
  "send a message, accept non-essential cookies, or take any other account-changing or irreversible action. " +
  "If a cookie banner cannot be declined or set to essential-only cookies, stop and report that blocker. Stop as soon " +
  "as the requested information or results are visible, and report what you see instead of proceeding further.";

const SAFETY_SUFFIX_WRITE_ALLOWED =
  " This run is explicitly allowed to complete account-changing actions because the user approved --allow-write. " +
  "Still never accept non-essential cookies or enter real payment card details unless the user explicitly provided them for this exact task.";

/**
 * Dismiss consent banners before the agent starts, preferring a privacy-safe
 * rejection/essential-only action. This has a short poll because many consent
 * frameworks mount after DOMContentLoaded. It never accepts tracking cookies.
 */
async function rejectCookieBanner(page: EvaluatingPage): Promise<string | null> {
  for (let attempt = 0; attempt < 6; attempt += 1) {
    try {
      const choice = await page.evaluate<string | null>(() => {
        const patterns = [
          /^decline all$/i,
          /^decline$/i,
          /^reject all$/i,
          /^reject$/i,
          /^reject optional cookies$/i,
          /^necessary only$/i,
          /^essential cookies only$/i,
          /^continue without accepting$/i,
        ];
        const knownCmpSelector = [
          "#onetrust-banner-sdk",
          "#CybotCookiebotDialog",
          "#usercentrics-root",
          "#didomi-host",
          "#sp-cc",
          "[data-testid='cookie-banner']",
          "[data-testid='consent-banner']",
        ].join(",");
        const knownContainers = Array.from(document.querySelectorAll<HTMLElement>(knownCmpSelector));
        const semanticDialogs = Array.from(document.querySelectorAll<HTMLElement>("[role='dialog'], [role='alertdialog']"))
          .filter((dialog) => {
            const label = `${dialog.getAttribute("aria-label") ?? ""} ${dialog.textContent ?? ""}`;
            return /\b(cookie|consent|privacy preferences)\b/i.test(label);
          });
        const containers = [...new Set([...knownContainers, ...semanticDialogs])];
        if (containers.length === 0) return null;
        const elements = containers.flatMap((container) =>
          Array.from(container.querySelectorAll<HTMLElement>("button, a[role='button'], [role='button']")),
        );
        for (const pattern of patterns) {
          const match = elements.find((element) => {
            const text = (element.textContent ?? "").trim();
            const rect = element.getBoundingClientRect();
            return Boolean(text) && pattern.test(text) && rect.width > 0 && rect.height > 0;
          });
          if (match) {
            const text = (match.textContent ?? "").trim();
            match.click();
            return text;
          }
        }
        return null;
      });
      if (choice) return choice;
    } catch {
      // A page context can disappear during navigation; retry briefly.
    }
    await page.waitForTimeout(500);
  }
  return null;
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));

  if (!process.env.OPENAI_API_KEY && !process.env.ANTHROPIC_API_KEY && !process.env.GOOGLE_API_KEY) {
    console.error(JSON.stringify({ success: false, error: "No model provider API key found in environment (OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY)." }));
    process.exitCode = 1;
    return;
  }

  const profileDir = mkdtempSync(path.join(tmpdir(), `stagehand-profile-${randomBytes(4).toString("hex")}-`));
  const stagehand = new Stagehand({
    env: "LOCAL",
    disableAPI: true,
    verbose: 1,
    model: { modelName: args.model, apiKey: process.env.OPENAI_API_KEY },
    localBrowserLaunchOptions: {
      userDataDir: profileDir,
      preserveUserDataDir: false,
      headless: args.headless,
      acceptDownloads: false,
      viewport: { width: 1280, height: 900 },
    },
  });

  const run = async (): Promise<void> => {
    await stagehand.init();
    const page = stagehand.context.pages()[0];
    await page.goto(args.url, { waitUntil: "domcontentloaded", timeoutMs: 30_000 });
    const cookieChoice = await rejectCookieBanner(page);
    if (cookieChoice) await page.waitForTimeout(800);

    const instruction = args.instruction + (args.allowWrite ? SAFETY_SUFFIX_WRITE_ALLOWED : SAFETY_SUFFIX_READ_ONLY);

    const agent = stagehand.agent({ model: args.model, mode: "dom" });
    const result = await agent.execute({
      instruction,
      maxSteps: args.maxSteps,
      toolTimeout: 20_000,
    });

    console.log(JSON.stringify({
      success: result.success,
      completed: result.completed,
      message: result.message,
      finalUrl: stagehand.context.pages()[0]?.url() ?? null,
      stepCount: result.actions.length,
      cookieChoice,
      usage: result.usage,
    }, null, 2));
  };

  let deadline: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      run(),
      new Promise<never>((_, reject) => {
        deadline = setTimeout(() => {
          void stagehand.close({ force: true });
          reject(new Error(`Stagehand task exceeded ${args.timeoutMs}ms and was stopped.`));
        }, args.timeoutMs);
      }),
    ]);
  } catch (error) {
    console.error(JSON.stringify({ success: false, error: error instanceof Error ? error.message : String(error) }));
    process.exitCode = 1;
  } finally {
    if (deadline) clearTimeout(deadline);
    await stagehand.close({ force: true }).catch(() => {});
    rmSync(profileDir, { recursive: true, force: true });
  }
}

main();
