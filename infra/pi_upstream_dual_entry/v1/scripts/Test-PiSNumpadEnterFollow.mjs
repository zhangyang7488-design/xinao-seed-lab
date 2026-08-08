import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [agentDir, piPackageRoot, receiptPath] = process.argv.slice(2);
if (!agentDir || !piPackageRoot) {
	throw new Error("usage: node Test-PiSNumpadEnterFollow.mjs <agent-dir> <pi-package-root>");
}

const resolvedAgentDir = path.resolve(agentDir);
const keybindingsPath = path.join(resolvedAgentDir, "keybindings.json");
const modulePath = path.join(path.resolve(piPackageRoot), "dist", "core", "keybindings.js");
if (!fs.existsSync(keybindingsPath)) throw new Error(`keybindings missing: ${keybindingsPath}`);
if (!fs.existsSync(modulePath)) throw new Error(`Pi keybindings module missing: ${modulePath}`);

const { KeybindingsManager } = await import(pathToFileURL(modulePath).href);
const manager = KeybindingsManager.create(resolvedAgentDir);
const effective = manager.getEffectiveConfig();
const asList = (value) => (Array.isArray(value) ? value : value ? [value] : []);
const f12Claimants = Object.entries(effective)
	.filter(([, value]) => asList(value).includes("f12"))
	.map(([action]) => action)
	.sort();
const bottomKeys = manager.getKeys("tui.altScreen.bottom");
const submitKeys = manager.getKeys("tui.input.submit");
const conflicts = manager.getConflicts();

const report = {
	schema: "xinao.pis.numpad_enter_follow_keybindings_acceptance.v1",
	status: "verified",
	profile: path.basename(resolvedAgentDir),
	keybindings: keybindingsPath,
	bottom_keys: bottomKeys,
	submit_keys: submitKeys,
	f12_claimants: f12Claimants,
	f12_sequence_matches_bottom: manager.matches("\u001b[24~", "tui.altScreen.bottom"),
	enter_sequence_matches_submit: manager.matches("\r", "tui.input.submit"),
	main_enter_not_bound_to_bottom: !bottomKeys.includes("enter"),
	conflicts,
};

const failures = [];
if (!bottomKeys.includes("end")) failures.push("native End binding was not preserved");
if (!bottomKeys.includes("f12")) failures.push("F12 was not added to transcript bottom/follow");
if (!submitKeys.includes("enter")) failures.push("ordinary Enter no longer submits input");
if (bottomKeys.includes("enter")) failures.push("ordinary Enter was added to transcript bottom/follow");
if (f12Claimants.length !== 1 || f12Claimants[0] !== "tui.altScreen.bottom") {
	failures.push(`F12 claimants are ${f12Claimants.join(",") || "none"}`);
}
if (!report.f12_sequence_matches_bottom) failures.push("Windows Terminal F12 sequence is not consumed by bottom/follow");
if (!report.enter_sequence_matches_submit) failures.push("carriage return is not consumed by submit");
if (conflicts.length > 0) failures.push(`user keybinding conflicts: ${JSON.stringify(conflicts)}`);

if (failures.length > 0) {
	report.status = "failed";
	report.failures = failures;
	console.error(JSON.stringify(report, null, 2));
	process.exit(1);
}

if (receiptPath) {
	fs.mkdirSync(path.dirname(receiptPath), { recursive: true });
	fs.writeFileSync(receiptPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
}
console.log(JSON.stringify(report, null, 2));
