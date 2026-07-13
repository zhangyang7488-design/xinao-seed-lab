import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const root = process.argv[2];
if (!root) {
  throw new Error("ACPX generation root is required");
}

const dist = path.join(root, "node_modules", "acpx", "dist");
const candidates = fs
  .readdirSync(dist)
  .filter((name) => /^live-checkpoint-.*\.js$/u.test(name));
if (candidates.length !== 1) {
  throw new Error(`Expected one ACPX live checkpoint bundle, found ${candidates.length}`);
}

const target = path.join(dist, candidates[0]);
const original = "if (spawnCommand.killProcessGroup) spawnOptions.detached = true;";
const replacement =
  'if (spawnCommand.killProcessGroup && process.platform !== "win32") spawnOptions.detached = true;';
const source = fs.readFileSync(target, "utf8");
const originalCount = source.split(original).length - 1;
const replacementCount = source.split(replacement).length - 1;

if (replacementCount === 1 && originalCount === 0) {
  process.stdout.write(JSON.stringify({ ok: true, status: "already_patched" }) + "\n");
  process.exit(0);
}
if (originalCount !== 1 || replacementCount !== 0) {
  throw new Error(
    `ACPX Windows terminal patch precondition failed: original=${originalCount} replacement=${replacementCount}`,
  );
}

const temporary = `${target}.${process.pid}.tmp`;
fs.writeFileSync(temporary, source.replace(original, replacement), "utf8");
fs.renameSync(temporary, target);
process.stdout.write(
  JSON.stringify({
    ok: true,
    status: "patched",
    patch_id: "acpx-0.12.0-windows-shell-no-detached-v1",
  }) + "\n",
);
