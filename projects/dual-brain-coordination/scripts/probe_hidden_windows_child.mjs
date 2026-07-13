import { spawn } from "node:child_process";

const command = [
  "powershell.exe",
  "-NoLogo",
  "-NoProfile",
  "-NonInteractive",
  "-Command",
  'Start-Sleep -Milliseconds 750; Write-Output XINAO_HIDDEN_CHILD_OK',
].join(" ");

const child = spawn("cmd.exe", ["/d", "/s", "/c", command], {
  detached: process.argv.includes("--detached"),
  stdio: ["ignore", "pipe", "pipe"],
  windowsHide: true,
});

let stdout = "";
let stderr = "";
child.stdout.setEncoding("utf8");
child.stderr.setEncoding("utf8");
child.stdout.on("data", (chunk) => {
  stdout += chunk;
});
child.stderr.on("data", (chunk) => {
  stderr += chunk;
});
child.once("error", (error) => {
  process.stdout.write(JSON.stringify({ ok: false, error: error.message }) + "\n");
  process.exitCode = 1;
});
child.once("close", (code, signal) => {
  const ok = code === 0 && stdout.trim() === "XINAO_HIDDEN_CHILD_OK";
  process.stdout.write(
    JSON.stringify({ ok, code, signal, stdout, stderrLength: stderr.length }) + "\n",
  );
  process.exitCode = ok ? 0 : 1;
});
