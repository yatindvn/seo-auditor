const { spawn, spawnSync } = require("child_process");
const net = require("net");
const path = require("path");

const isWindows = process.platform === "win32";

// `useShell` is required for npm on Windows, where npm resolves to npm.cmd and
// Node refuses to spawn .cmd/.bat directly. The command is passed as one string
// so no argument array is combined with the shell (which would warn, DEP0190).
function runCommand(command, args, cwd, prefix, useShell) {
  const child = useShell
    ? spawn([command, ...args].join(" "), { cwd, stdio: "pipe", shell: true })
    : spawn(command, args, { cwd, stdio: "pipe" });

  child.stdout.on("data", (data) => {
    process.stdout.write(`[${prefix}] ${data}`);
  });

  child.stderr.on("data", (data) => {
    process.stderr.write(`[${prefix}] ${data}`);
  });

  child.on("error", (err) => {
    console.error(`[${prefix}] failed to start: ${err.message}`);
    shutdown(1);
  });

  child.on("exit", (code, signal) => {
    if (shuttingDown) return;
    console.error(`[${prefix}] exited unexpectedly (code=${code} signal=${signal}). Stopping the other server.`);
    shutdown(code === 0 ? 1 : code || 1);
  });

  return child;
}

// Resolves the Python launcher: `python` on PATH, else the Windows `py` launcher.
function resolvePython() {
  for (const candidate of isWindows ? ["python", "py"] : ["python3", "python"]) {
    const probe = spawnSync(candidate, ["--version"], { stdio: "ignore" });
    if (!probe.error && probe.status === 0) return candidate;
  }
  console.error("Could not find Python on PATH. Install Python 3 and make sure `python --version` works in this shell.");
  process.exit(1);
}

// Resolves whether a TCP port can actually be bound, so a busy port is reported
// as a clear message instead of a bare WinError 10013 / EADDRINUSE from a child.
// Both the dual-stack wildcard (how Next binds) and loopback (how uvicorn binds)
// are probed, since holding one does not always block binding the other.
function bindable(port, host) {
  return new Promise((resolve) => {
    const tester = net
      .createServer()
      .once("error", () => resolve(false))
      .once("listening", () => tester.close(() => resolve(true)))
      .listen(host ? { port, host } : { port });
  });
}

async function checkPortFree(port) {
  const results = await Promise.all([bindable(port), bindable(port, "127.0.0.1")]);
  return results.every(Boolean);
}

function portBusyHelp(port, label) {
  const findCmd = isWindows
    ? `  netstat -ano | findstr :${port}\n  taskkill /PID <pid> /F`
    : `  lsof -i :${port}\n  kill -9 <pid>`;
  return (
    `Port ${port} is already in use, so the ${label} cannot start.\n` +
    `A previous dev server is probably still running in the background.\n` +
    `Find and stop it with:\n${findCmd}`
  );
}

const rootDir = path.resolve(__dirname, "..");
const backendPort = process.env.PORT || "5000";
const frontendPort = process.env.FRONTEND_PORT || "3000";

let backend = null;
let frontend = null;
let shuttingDown = false;

// `child.kill()` on Windows only kills the direct child. Both servers spawn
// their own workers (uvicorn --reload forks a reload worker, npm forks next),
// and those workers survive as orphans still holding ports 5000/3000 — which
// makes the *next* `npm run dev` fail with WinError 10013. Kill the whole tree.
function killTree(child) {
  if (!child || child.killed || child.exitCode !== null) return;
  if (isWindows) {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
  } else {
    child.kill();
  }
}

function shutdown(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  killTree(backend);
  killTree(frontend);
  process.exit(code);
}

async function main() {
  console.log("Starting SEO Auditor Monorepo Development Servers (100% Native Python Backend + Next.js Frontend)...");

  const [backendFree, frontendFree] = await Promise.all([
    checkPortFree(Number(backendPort)),
    checkPortFree(Number(frontendPort)),
  ]);

  if (!backendFree) {
    console.error(portBusyHelp(backendPort, "Python backend"));
    process.exit(1);
  }
  if (!frontendFree) {
    console.error(portBusyHelp(frontendPort, "Next.js frontend"));
    process.exit(1);
  }

  const python = resolvePython();

  backend = runCommand(
    python,
    ["-m", "uvicorn", "app.main:app", "--reload", "--port", backendPort],
    path.join(rootDir, "apps/backend"),
    "PYTHON-BACKEND"
  );
  frontend = runCommand(
    "npm",
    ["run", "dev", "--", "--port", frontendPort],
    path.join(rootDir, "apps/frontend"),
    "NEXT-FRONTEND",
    true
  );
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

main();
