/**
 * 프런트엔드 단독 개발 환경은 Node만으로 테스트할 수 있도록 유지한다.
 * Python이 설치된 플랫폼/CI 환경은 동일한 공통 검증 계약으로 결과를 남긴다.
 */
import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cli = resolve(root, "../../scripts/validation/run_suite.py");
const configuredPython = process.env.PYTHON_BIN?.trim();
const python = configuredPython || "python3";
const result = spawnSync(python, [cli, "node"], { cwd: root, stdio: "inherit" });

if (!result.error) {
  process.exit(result.status ?? 1);
}
if (result.error.code !== "ENOENT" || configuredPython) {
  console.error("[validation] Python runner could not start: " + result.error.code);
  process.exit(127);
}

// 독립적인 Node 개발에서는 기존 테스트 실행 경로를 유지하되, 결과 생성을 주장하지 않는다.
console.warn("[validation] Python unavailable; running native Node tests without manifest/summary");
const files = readdirSync(join(root, "tests"))
  .filter((name) => name.endsWith(".test.mjs"))
  .sort()
  .map((name) => join("tests", name));
if (files.length === 0) {
  console.error("[validation] no Node test files found");
  process.exit(2);
}
const native = spawnSync(
  process.execPath,
  ["--experimental-strip-types", "--test", ...files],
  { cwd: root, stdio: "inherit" },
);
if (native.error) {
  console.error("[validation] Node tests could not start: " + native.error.code);
  process.exit(127);
}
process.exit(native.status ?? 1);
