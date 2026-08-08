#!/usr/bin/env node

import { existsSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";

function fail(message, code = 2) {
  process.stderr.write(`${message}\n`);
  process.exit(code);
}
const argv = process.argv.slice(2);
const commandName = argv.shift();
const args = {};
while (argv.length) {
  const key = argv.shift();
  const value = argv.shift();
  if (!key?.startsWith("--") || value === undefined) fail(`Invalid argument sequence near ${key || "<end>"}`);
  args[key.slice(2)] = value;
}

const allowed = new Set(["list", "get_state", "get_resource_snapshot", "get_system_prompt", "reload", "kill"]);
if (!allowed.has(commandName)) fail(`Unsupported command: ${commandName}`);
const socket = args.socket || "\\\\.\\pipe\\prime-agent-local-cognition-account-b";
const session = args.session;
if (commandName !== "list" && !session) fail(`${commandName} requires --session`);
const primeRoot = args["prime-root"] || "D:/XINAO_RESEARCH_RUNTIME/tools/prime-agent/0.7.0";
const clientPath = path.join(primeRoot, "node_modules/prime-agent/dist/modes/daemon/daemon-client.js");
if (!existsSync(clientPath)) fail(`Prime DaemonClient missing: ${clientPath}`);
const { DaemonClient } = await import(pathToFileURL(clientPath).href);
const client = new DaemonClient(socket);
try {
  await client.connect();
  const command = { type: commandName };
  if (session) command.activeSessionId = session;
  const response = await client.request(command, Number(args.timeout || 15000));
  process.stdout.write(`${JSON.stringify(response, null, 2)}\n`);
  process.exit(response?.success === true ? 0 : 1);
} catch (error) {
  fail(`Prime daemon command failed: ${error instanceof Error ? error.message : String(error)}`, 1);
}
