import fs from "node:fs";
import path from "node:path";

const readyPath = process.argv[2];
const exitPath = process.argv[3];

if (!readyPath || !exitPath) {
	process.stderr.write("PI_OWNER_STOP_FIXTURE_PATHS_REQUIRED\n");
	process.exit(64);
}

function writeJson(filePath, value) {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const temporary = `${filePath}.${process.pid}.${Date.now()}.tmp`;
	fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
	fs.renameSync(temporary, filePath);
}

writeJson(readyPath, {
	schema: "xinao.pi_owner_stop_child_ready.v1",
	pid: process.pid,
	parent_pid: process.ppid,
	started_at: new Date().toISOString(),
});

let settled = false;
function settle(reason) {
	if (settled) return;
	settled = true;
	try {
		writeJson(exitPath, {
			schema: "xinao.pi_owner_stop_child_exit.v1",
			pid: process.pid,
			reason,
			exited_at: new Date().toISOString(),
		});
	} finally {
		process.exit(0);
	}
}

process.on("SIGTERM", () => settle("SIGTERM"));
process.on("SIGINT", () => settle("SIGINT"));
process.stdin.resume();
setInterval(() => {}, 1_000);
