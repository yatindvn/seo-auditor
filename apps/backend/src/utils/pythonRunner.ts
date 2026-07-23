import { exec } from "child_process";
import path from "path";
import util from "util";
import { AuditRequestParams, AuditResponse } from "@seo-auditor/shared";

const execAsync = util.promisify(exec);

export async function runPythonCrawler(params: AuditRequestParams): Promise<AuditResponse> {
  const { url, max_pages = 8, max_depth = 1, ignore_robots = false } = params;
  const packageDir = path.resolve(__dirname, "../../seo_auditor");
  const ignoreFlag = ignore_robots ? "--ignore-robots" : "";
  const command = `python -m seo_auditor.cli "${url}" --max-pages ${max_pages} --max-depth ${max_depth} ${ignoreFlag} --json`;

  try {
    const { stdout } = await execAsync(command, { cwd: packageDir });
    return JSON.parse(stdout) as AuditResponse;
  } catch (error: any) {
    throw new Error(`Crawler execution failed: ${error.message || String(error)}`);
  }
}
