import { pathToFileURL } from "node:url";
import path from "node:path";

const [primeRoot, socketPath] = process.argv.slice(2);
if (!primeRoot || !socketPath) {
  process.stderr.write("PRIME_PARITY_DAEMON_ARGS_REQUIRED\n");
  process.exit(2);
}
const modulePath = path.join(primeRoot, "node_modules", "prime-agent", "dist", "cli", "daemon-launch.js");
const { shutdownDaemonAndWait } = await import(pathToFileURL(modulePath).href);
const stopped = await shutdownDaemonAndWait(socketPath, 10000);
process.stdout.write(`${JSON.stringify({ schema: "xinao.prime_parity.daemon_stop.v1", socket: socketPath, stopped })}\n`);
process.exit(stopped ? 0 : 3);
