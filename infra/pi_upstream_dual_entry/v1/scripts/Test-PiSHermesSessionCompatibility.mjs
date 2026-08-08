import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) throw new Error(`Expected --name value pairs: ${argv.join(" ")}`);
    result[key.slice(2)] = value;
  }
  return result;
}

function required(args, name) {
  if (!args[name]) throw new Error(`Missing --${name}`);
  return args[name];
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const agentDir = path.resolve(required(args, "agent-dir"));
  const sessionDir = path.resolve(required(args, "session-dir"));
  const receiptPath = args.receipt;
  const packageRoot = path.join(agentDir, "npm", "node_modules", "pi-hermes-memory");
  const jitiModule = path.join(agentDir, "npm", "node_modules", "jiti", "lib", "jiti.mjs");
  const parserModule = path.join(packageRoot, "src", "store", "session-parser.ts");
  const indexerModule = path.join(packageRoot, "src", "store", "session-indexer.ts");
  const dbModule = path.join(packageRoot, "src", "store", "db.ts");
  const memoryDir = path.join(agentDir, "pi-hermes-memory");
  for (const file of [jitiModule, parserModule, indexerModule, dbModule]) {
    if (!fs.statSync(file).isFile()) throw new Error(`Required module missing: ${file}`);
  }

  const artifactDir = path.join(sessionDir, "subagent-artifacts");
  const artifactTranscripts = fs.existsSync(artifactDir)
    ? fs.readdirSync(artifactDir).filter((name) => name.endsWith(".jsonl"))
    : [];
  const { createJiti } = await import(pathToFileURL(jitiModule).href);
  const jiti = createJiti(import.meta.url, { moduleCache: false });
  const parser = await jiti.import(parserModule);
  const indexer = await jiti.import(indexerModule);
  const database = await jiti.import(dbModule);
  const scannedFiles = parser.getSessionFiles(sessionDir);
  if (scannedFiles.some((file) => path.dirname(file).toLowerCase() === artifactDir.toLowerCase())) {
    throw new Error(`Hermes still scans subagent transcript artifacts: ${JSON.stringify(scannedFiles)}`);
  }

  const manager = new database.DatabaseManager(memoryDir);
  let result;
  try {
    result = indexer.indexAllSessions(manager, sessionDir);
  } finally {
    manager.close();
  }
  if (result.errors.length > 0) throw new Error(`Hermes session index errors: ${JSON.stringify(result.errors)}`);

  const receipt = {
    schema: "xinao.pi_s_hermes_session_compatibility_acceptance.v1",
    status: "verified",
    profile: path.basename(agentDir),
    pi_sessions_scanned: scannedFiles.length,
    sessions_processed: result.sessionsProcessed,
    sessions_indexed: result.sessionsIndexed,
    sessions_skipped: result.sessionsSkipped,
    messages_indexed: result.messagesIndexed,
    file_errors: result.errors.length,
    subagent_artifact_transcripts_present: artifactTranscripts.length,
    subagent_artifact_transcripts_parsed_as_sessions: false,
    child_artifacts_deleted: false,
  };
  if (receiptPath) {
    fs.mkdirSync(path.dirname(receiptPath), { recursive: true });
    fs.writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
  }
  process.stdout.write(`${JSON.stringify(receipt)}\n`);
}

main().catch((error) => {
  process.stderr.write(`PI_S_HERMES_SESSION_COMPATIBILITY_TEST_ERROR: ${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
