import { pathToFileURL } from "node:url";

const ipythonPath = process.argv[2];
const pythonPath = process.argv[3];
if (!ipythonPath || !pythonPath) {
  throw new Error("usage: node Test-PrimeKernelTerminalRecovery.mjs <ipython.js> <python.exe>");
}

const { IpythonKernelProvisioner, createIpythonToolDefinition } = await import(pathToFileURL(ipythonPath).href);
const provisioner = new IpythonKernelProvisioner(process.cwd(), {
  python: pythonPath,
  env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
});
const tool = createIpythonToolDefinition(process.cwd(), { provisioner });
const ctx = { hasUI: false };

try {
  const firstManager = await provisioner.ensure();
  await firstManager.kill();

  let recoveredError;
  try {
    await tool.execute("terminal-recovery-1", { code: "print('must-not-replay')" }, undefined, undefined, ctx);
  } catch (error) {
    recoveredError = error;
  }
  if (!recoveredError || recoveredError.name !== "IpythonKernelRecoveredAfterShutdownError") {
    throw new Error(`expected one recovered terminal error, observed ${recoveredError?.name}: ${recoveredError?.message}`);
  }
  if (!provisioner.hasRunningKernel) {
    throw new Error("host recovery did not leave a running kernel");
  }

  const health = await tool.execute("terminal-recovery-health", { code: "print('PRIME_KERNEL_RECOVERY_HEALTH_OK')" }, undefined, undefined, ctx);
  const text = health.content.map((item) => item.type === "text" ? item.text : "").join("\n");
  if (health.isError || !text.includes("PRIME_KERNEL_RECOVERY_HEALTH_OK")) {
    throw new Error(`fresh kernel health probe failed: ${text}`);
  }

  const circuitError = Object.assign(new Error("synthetic recovery failed; circuit is open"), {
    name: "IpythonKernelRecoveryCircuitOpenError",
  });
  const synthetic = {
    open: false,
    recoveries: 0,
    async ensure() {
      if (this.open) throw circuitError;
      return { async execute() { throw new Error("Kernel has been shut down"); } };
    },
    async recoverTerminalShutdown() {
      this.recoveries += 1;
      this.open = true;
      throw circuitError;
    },
  };
  const syntheticTool = createIpythonToolDefinition(process.cwd(), { provisioner: synthetic });
  for (const id of ["circuit-open-1", "circuit-open-2"]) {
    try {
      await syntheticTool.execute(id, { code: "1 + 1" }, undefined, undefined, ctx);
    } catch (error) {
      if (error !== circuitError) throw error;
    }
  }
  if (synthetic.recoveries !== 1) {
    throw new Error(`terminal recovery retried after circuit opened: ${synthetic.recoveries}`);
  }
  process.stdout.write(JSON.stringify({
    status: "verified",
    terminal_error_count: 1,
    original_cell_replayed: false,
    host_recovery: true,
    health_probe: true,
    failed_recovery_attempts_before_fail_fast: synthetic.recoveries,
  }));
} finally {
  await provisioner.dispose();
}
