const { spawn } = require("child_process");
const path = require("path");

function runCommand(command, args, cwd, prefix) {
  const child = spawn(command, args, {
    cwd,
    shell: true,
    stdio: "pipe",
  });

  child.stdout.on("data", (data) => {
    process.stdout.write(`[${prefix}] ${data}`);
  });

  child.stderr.on("data", (data) => {
    process.stderr.write(`[${prefix}] ${data}`);
  });

  return child;
}

const rootDir = path.resolve(__dirname, "..");
console.log("Starting SEO Auditor Monorepo Development Servers (100% Native Python Backend + Next.js Frontend)...");

const backend = runCommand("python", ["-m", "uvicorn", "app.main:app", "--reload", "--port", "5000"], path.join(rootDir, "apps/backend"), "PYTHON-BACKEND");
const frontend = runCommand("npm", ["run", "dev"], path.join(rootDir, "apps/frontend"), "NEXT-FRONTEND");

process.on("SIGINT", () => {
  backend.kill();
  frontend.kill();
  process.exit();
});
