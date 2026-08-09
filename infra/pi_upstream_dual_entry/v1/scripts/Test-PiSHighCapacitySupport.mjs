import { createHash } from "node:crypto";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const MOCK_PI_CHILD = path.join(SCRIPT_DIR, "Test-PiSHighCapacityMockPiChild.mjs");
const JITI_ALIAS_MANIFEST = path.join(SCRIPT_DIR, "Test-PiSHighCapacityJitiAlias.manifest.json");
const JITI_ALIAS_MANIFEST_SHA256 = "72dab53502a6d0af9b037cd7b6c53be77a77415ed8affb342492ccaff13936a6";

function sha256File(filePath) {
	return createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function containedRequiredFile(root, relativePath, label) {
	if (typeof relativePath !== "string" || relativePath.trim() === "" || path.isAbsolute(relativePath) || relativePath.includes(":")) {
		throw new Error(`Invalid ${label} relative path: ${relativePath}`);
	}
	const lexical = path.resolve(root, relativePath.replaceAll("/", path.sep));
	const prefix = `${path.resolve(root).toLowerCase()}${path.sep}`;
	if (!lexical.toLowerCase().startsWith(prefix)) throw new Error(`${label} escaped the Pi coding-agent package: ${relativePath}`);
	const resolved = requiredFile(lexical, label);
	if (!resolved.toLowerCase().startsWith(`${fs.realpathSync(root).toLowerCase()}${path.sep}`)) {
		throw new Error(`${label} realpath escaped the Pi coding-agent package: ${resolved}`);
	}
	return resolved;
}

function verifiedJitiAlias(corePackageRoot) {
	const manifestPath = requiredFile(JITI_ALIAS_MANIFEST, "high-capacity Jiti alias manifest");
	const manifestSha256 = sha256File(manifestPath);
	if (manifestSha256 !== JITI_ALIAS_MANIFEST_SHA256) {
		throw new Error(`High-capacity Jiti alias manifest drift: ${manifestSha256}`);
	}
	const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
	if (
		manifest.schema !== "xinao.pi_s_high_capacity_jiti_alias_manifest.v1"
		|| manifest.core_package !== "@earendil-works/pi-coding-agent"
		|| manifest.core_package_version !== "0.84.1"
		|| !Array.isArray(manifest.packages)
		|| manifest.packages.length !== 4
	) {
		throw new Error("High-capacity Jiti alias manifest identity drift.");
	}
	const aliases = {};
	const seen = new Set();
	for (const entry of manifest.packages) {
		if (typeof entry?.name !== "string" || seen.has(entry.name) || entry.version !== "0.84.1") {
			throw new Error(`High-capacity Jiti alias package identity drift: ${entry?.name ?? "<missing>"}`);
		}
		seen.add(entry.name);
		const packageFile = containedRequiredFile(corePackageRoot, entry.package_json, `${entry.name} package manifest`);
		const runtimeEntry = containedRequiredFile(corePackageRoot, entry.entry, `${entry.name} Jiti entry`);
		if (sha256File(packageFile) !== entry.package_sha256 || sha256File(runtimeEntry) !== entry.entry_sha256) {
			throw new Error(`High-capacity Jiti alias member drift: ${entry.name}`);
		}
		const packageJson = JSON.parse(fs.readFileSync(packageFile, "utf8"));
		if (packageJson.name !== entry.name || packageJson.version !== "0.84.1") {
			throw new Error(`High-capacity Jiti alias package JSON drift: ${entry.name}`);
		}
		let declared;
		if (entry.entry_selector === "main") declared = packageJson.main;
		else if (entry.entry_selector === "exports[.].import") declared = packageJson.exports?.["."]?.import;
		else if (entry.entry_selector === "exports[./compat].import") declared = packageJson.exports?.["./compat"]?.import;
		else throw new Error(`Unexpected high-capacity Jiti alias selector: ${entry.entry_selector}`);
		if (declared !== entry.entry_value) throw new Error(`High-capacity Jiti alias declaration drift: ${entry.name}`);
		const declaredEntry = fs.realpathSync(path.resolve(path.dirname(packageFile), declared));
		if (declaredEntry !== runtimeEntry) throw new Error(`High-capacity Jiti alias entry mismatch: ${entry.name}`);
		const aliasName = entry.name === "@earendil-works/pi-ai" ? "@earendil-works/pi-ai/compat" : entry.name;
		aliases[aliasName] = runtimeEntry;
	}
	for (const expected of ["@earendil-works/pi-coding-agent", "@earendil-works/pi-agent-core", "@earendil-works/pi-ai", "@earendil-works/pi-tui"]) {
		if (!seen.has(expected)) throw new Error(`High-capacity Jiti alias package set drift: ${expected}`);
	}
	return Object.freeze(aliases);
}

function requiredDirectory(envName) {
	const raw = process.env[envName];
	if (typeof raw !== "string" || raw.trim() === "") {
		throw new Error(`${envName} is required.`);
	}
	const resolved = fs.realpathSync(path.resolve(raw));
	if (!fs.statSync(resolved).isDirectory()) {
		throw new Error(`${envName} is not a directory: ${resolved}`);
	}
	return resolved;
}

function requiredFile(filePath, label) {
	const resolved = fs.realpathSync(filePath);
	if (!fs.statSync(resolved).isFile()) throw new Error(`${label} is not a file: ${resolved}`);
	return resolved;
}

export function getHighCapacityReplayPaths() {
	const agentDir = requiredDirectory("XINAO_PI_HIGH_CAPACITY_AGENT_DIR");
	const piToolRoot = requiredDirectory("XINAO_PI_HIGH_CAPACITY_PI_TOOL_ROOT");
	const tempRoot = requiredDirectory("XINAO_PI_HIGH_CAPACITY_TEMP_ROOT");
	const subagentsRoot = requiredDirectoryFromPath(path.join(agentDir, "npm", "node_modules", "pi-subagents"), "pi-subagents replay root");
	const corePackageRoot = requiredDirectoryFromPath(
		path.join(piToolRoot, "node_modules", "@earendil-works", "pi-coding-agent"),
		"Pi coding-agent replay package",
	);
	const jitiAlias = verifiedJitiAlias(corePackageRoot);
	return Object.freeze({
		agentDir,
		piToolRoot,
		tempRoot,
		subagentsRoot,
		corePackageRoot,
		jitiAlias,
		peerPath: requiredFile(path.join(agentDir, "agents", "peer.md"), "prime-s peer frontmatter"),
		sessionFile: requiredFile(path.join(corePackageRoot, "dist", "core", "sdk.js"), "Pi core sdk session identity"),
		coreAnchor: requiredFile(path.join(corePackageRoot, "dist", "index.js"), "Pi core package anchor"),
		coreCapacityRuntime: requiredFile(
			path.join(corePackageRoot, "dist", "core", "xinao-pi-subagent-capacity-runtime.js"),
			"Pi core capacity runtime projection",
		),
		npmCapacityRuntime: requiredFile(
			path.join(subagentsRoot, "src", "runs", "shared", "xinao-pi-subagent-capacity-runtime.js"),
			"pi-subagents capacity runtime source",
		),
	});
}

export function createReplayJiti(anchor) {
	if (typeof anchor !== "string" || anchor.trim() === "") throw new Error("createReplayJiti requires a module anchor.");
	const replay = getHighCapacityReplayPaths();
	const jitiRoot = path.join(replay.agentDir, "npm", "node_modules", "jiti");
	const { createJiti } = createRequire(anchor)(jitiRoot);
	return createJiti(anchor, { interopDefault: true, alias: replay.jitiAlias, moduleCache: false });
}

function requiredDirectoryFromPath(directoryPath, label) {
	const resolved = fs.realpathSync(directoryPath);
	if (!fs.statSync(resolved).isDirectory()) throw new Error(`${label} is not a directory: ${resolved}`);
	return resolved;
}

export function createReplayTempDir(prefix) {
	const { tempRoot } = getHighCapacityReplayPaths();
	const root = fs.mkdtempSync(path.join(tempRoot, prefix));
	const canonicalRoot = path.resolve(tempRoot).toLowerCase() + path.sep;
	if (!path.resolve(root).toLowerCase().startsWith(canonicalRoot)) {
		throw new Error(`Replay temp escaped its exact root: ${root}`);
	}
	return root;
}

export function createEventBus() {
	const listeners = new Map();
	return {
		on(channel, handler) {
			const channelListeners = listeners.get(channel) ?? new Set();
			channelListeners.add(handler);
			listeners.set(channel, channelListeners);
			return () => {
				channelListeners.delete(handler);
				if (channelListeners.size === 0) listeners.delete(channel);
			};
		},
		emit(channel, payload) {
			for (const handler of listeners.get(channel) ?? []) handler(payload);
		},
	};
}

export function makeAgent(name, overrides = {}) {
	return {
		name,
		description: `Test agent: ${name}`,
		systemPrompt: "",
		systemPromptMode: "replace",
		inheritProjectContext: false,
		inheritSkills: false,
		...overrides,
	};
}

export function makeMinimalCtx(cwd) {
	return {
		cwd,
		hasUI: false,
		ui: {},
		sessionManager: {
			getSessionId: () => "session-123",
			getSessionFile: () => null,
		},
		modelRegistry: { getAvailable: () => [] },
	};
}

function listQueueFiles(queueDir, prefix) {
	try {
		return fs.readdirSync(queueDir).filter((name) => name.startsWith(prefix)).sort();
	} catch {
		return [];
	}
}

function ensureDirectory(directoryPath) {
	fs.mkdirSync(directoryPath, { recursive: true });
}

function writeExecutable(filePath, content) {
	fs.writeFileSync(filePath, content, "utf8");
	fs.chmodSync(filePath, 0o755);
}

export function createMockPi(baseDir = getHighCapacityReplayPaths().tempRoot) {
	const rootDir = fs.mkdtempSync(path.join(baseDir, "mock-pi-"));
	let queueGeneration = 0;
	let queueDir = path.join(rootDir, `queue-${queueGeneration}`);
	const binDir = path.join(rootDir, "bin");
	const piPackageDir = path.join(rootDir, "pi-package");
	const cliScriptPath = path.join(piPackageDir, "dist", "cli.mjs");
	ensureDirectory(queueDir);
	ensureDirectory(binDir);
	ensureDirectory(path.dirname(cliScriptPath));
	fs.copyFileSync(MOCK_PI_CHILD, cliScriptPath);
	fs.writeFileSync(path.join(piPackageDir, "package.json"), JSON.stringify({ name: "@earendil-works/pi-coding-agent" }), "utf8");

	const shellScriptPath = path.join(binDir, "pi");
	const cmdScriptPath = path.join(binDir, "pi.cmd");
	writeExecutable(shellScriptPath, `#!/bin/sh\nexec "${process.execPath}" "${cliScriptPath}" "$@"\n`);
	writeExecutable(cmdScriptPath, `@echo off\r\n"${process.execPath}" "${cliScriptPath}" %*\r\n`);

	let installed = false;
	let nextSequence = 0;
	let originalPath;
	let originalPiBinary;
	let originalArgv1;
	let originalQueueEnv;
	return {
		get dir() { return queueDir; },
		install() {
			if (installed) return;
			installed = true;
			originalPath = process.env.PATH;
			originalPiBinary = process.env.PI_SUBAGENT_PI_BINARY;
			originalQueueEnv = process.env.MOCK_PI_QUEUE_DIR;
			process.env.PATH = `${binDir}${path.delimiter}${originalPath ?? ""}`;
			if (process.platform === "win32") {
				delete process.env.PI_SUBAGENT_PI_BINARY;
				originalArgv1 = process.argv[1];
				process.argv[1] = cliScriptPath;
			} else {
				process.env.PI_SUBAGENT_PI_BINARY = shellScriptPath;
			}
			process.env.MOCK_PI_QUEUE_DIR = queueDir;
		},
		uninstall() {
			if (!installed) return;
			installed = false;
			if (originalPath === undefined) delete process.env.PATH;
			else process.env.PATH = originalPath;
			if (originalPiBinary === undefined) delete process.env.PI_SUBAGENT_PI_BINARY;
			else process.env.PI_SUBAGENT_PI_BINARY = originalPiBinary;
			if (process.platform === "win32") {
				if (originalArgv1 === undefined) delete process.argv[1];
				else process.argv[1] = originalArgv1;
			}
			if (originalQueueEnv === undefined) delete process.env.MOCK_PI_QUEUE_DIR;
			else process.env.MOCK_PI_QUEUE_DIR = originalQueueEnv;
			try { fs.rmSync(rootDir, { recursive: true, force: true }); } catch {}
		},
		onCall(response) {
			ensureDirectory(queueDir);
			nextSequence += 1;
			const fileName = `pending-${String(nextSequence).padStart(6, "0")}.json`;
			const temporary = path.join(queueDir, `${fileName}.tmp-${process.pid}-${Date.now()}`);
			const target = path.join(queueDir, fileName);
			fs.writeFileSync(temporary, JSON.stringify(response), "utf8");
			fs.renameSync(temporary, target);
			fs.writeFileSync(path.join(queueDir, "default-response.json"), JSON.stringify(response), "utf8");
		},
		reset() {
			nextSequence = 0;
			queueGeneration += 1;
			queueDir = path.join(rootDir, `queue-${queueGeneration}`);
			ensureDirectory(queueDir);
			if (installed) process.env.MOCK_PI_QUEUE_DIR = queueDir;
		},
		callCount() { return listQueueFiles(queueDir, "call-").length; },
	};
}
