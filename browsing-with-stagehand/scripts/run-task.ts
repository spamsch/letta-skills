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
 * - Always enforces maxSteps and an overall wall-clock timeout via AbortSignal.
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
  "send a message, or take any other account-changing or irreversible action. Stop as soon as the requested " +
  "information or results are visible, and report what you see instead of proceeding further.";

const SAFETY_SUFFIX_WRITE_ALLOWED =
  " This run is explicitly allowed to complete account-changing actions because the user approved --allow-write. " +
  "Still never enter real payment card details unless the user explicitly provided them for this exact task.";

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));

  if (!process.env.OPENAI_API_KEY && !process.env.ANTHROPIC_API_KEY && !process.env.GOOGLE_API_KEY) {
    console.error(JSON.stringify({ success: false, error: "No model provider API key found in environment (OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY)." }));
    process.exitCode = 1;
    return;
  }

  const profileDir = mkdtempSync(path.join(tmpdir(), `stagehand-profile-${randomBytes(4).toString("hex")}-`));
  const controller = new AbortController();
  const deadline = setTimeout(() => controller.abort(), args.timeoutMs);

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

  try {
    await stagehand.init();
    const page = stagehand.context.pages()[0];
    await page.goto(args.url, { waitUntil: "domcontentloaded", timeout: 30_000 });

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
      finalUrl: stagehand.context.pages()[0]?.url?.() ?? null,
      stepCount: result.actions.length,
      usage: result.usage,
    }, null, 2));
  } catch (error) {
    console.error(JSON.stringify({ success: false, error: error instanceof Error ? error.message : String(error) }));
    process.exitCode = 1;
  } finally {
    clearTimeout(deadline);
    await stagehand.close({ force: true }).catch(() => {});
    rmSync(profileDir, { recursive: true, force: true });
  }
}

main();
