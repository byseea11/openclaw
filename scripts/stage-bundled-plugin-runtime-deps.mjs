import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import semverSatisfies from "semver/functions/satisfies.js";
import { resolveNpmRunner } from "./npm-runner.mjs";

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function removePathIfExists(targetPath) {
  fs.rmSync(targetPath, { recursive: true, force: true });
}

function makeTempDir(parentDir, prefix) {
  return fs.mkdtempSync(path.join(parentDir, prefix));
}

function sanitizeTempPrefixSegment(value) {
  const normalized = value.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/-+/g, "-");
  return normalized.length > 0 ? normalized : "plugin";
}

function replaceDir(targetPath, sourcePath) {
  removePathIfExists(targetPath);
  try {
    fs.renameSync(sourcePath, targetPath);
    return;
  } catch (error) {
    if (error?.code !== "EXDEV") {
      throw error;
    }
  }
  fs.cpSync(sourcePath, targetPath, { recursive: true, force: true });
  removePathIfExists(sourcePath);
}

function dependencyNodeModulesPath(nodeModulesDir, depName) {
  return path.join(nodeModulesDir, ...depName.split("/"));
}

function readInstalledDependencyVersion(nodeModulesDir, depName) {
  const packageJsonPath = path.join(
    dependencyNodeModulesPath(nodeModulesDir, depName),
    "package.json",
  );
  if (!fs.existsSync(packageJsonPath)) {
    return null;
  }
  const version = readJson(packageJsonPath).version;
  return typeof version === "string" ? version : null;
}

function dependencyVersionSatisfied(spec, installedVersion, params = {}) {
  if (semverSatisfies(installedVersion, spec, { includePrerelease: false })) {
    return true;
  }
  const viaName = params.viaName;
  if (
    spec === "^2.0.0" &&
    params.depName === "@smithy/util-utf8" &&
    (viaName === "@aws-crypto/sha256-browser" || viaName === "@aws-crypto/util") &&
    semverSatisfies(installedVersion, "^4.2.2", { includePrerelease: false })
  ) {
    // Bedrock's control-plane client currently resolves through the root Smithy
    // 4.x runtime in this workspace. Accept that already-installed closure so
    // bundled runtime staging can use the fast root node_modules copy path
    // instead of falling back to a networked npm install during build.
    return true;
  }
  if (
    params.depName === "fast-xml-parser" &&
    viaName === "@aws-sdk/xml-builder" &&
    spec === "5.5.8" &&
    installedVersion === "5.5.7"
  ) {
    // The root workspace pins fast-xml-parser 5.5.7, while Bedrock's control-plane
    // closure requests 5.5.8 through @aws-sdk/xml-builder. Treat this narrow patch
    // drift as compatible for bundled runtime staging so builds can reuse the
    // already-installed root dependency graph.
    return true;
  }
  if (
    params.depName === "@aws-sdk/token-providers" &&
    viaName === "@aws-sdk/credential-provider-sso" &&
    spec === "3.1026.0" &&
    installedVersion === "3.1028.0"
  ) {
    // The Bedrock discovery closure resolves to the root token-providers package
    // at 3.1028.0. Allow this exact newer AWS SDK patchline during staging instead
    // of forcing a fallback npm install.
    return true;
  }
  return false;
}

const stagedRuntimeDepPruneRules = new Map([
  // Type declarations only; runtime resolves through lib/es entrypoints.
  ["@larksuiteoapi/node-sdk", ["types"]],
]);
const runtimeDepsStagingVersion = 2;
const RUNTIME_DEPS_INSTALL_TIMEOUT_CODE = "RUNTIME_DEPS_INSTALL_TIMEOUT";
const DEFAULT_RUNTIME_DEPS_INSTALL_TIMEOUT_MS = 30_000;

function parsePositiveInt(value) {
  if (typeof value !== "string" || value.trim().length === 0) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function resolveInstallTimeoutMs(params = {}) {
  if (typeof params.installTimeoutMs === "number" && Number.isFinite(params.installTimeoutMs)) {
    return Math.max(1, Math.trunc(params.installTimeoutMs));
  }
  const envTimeout = parsePositiveInt(
    params.env?.OPENCLAW_RUNTIME_DEPS_INSTALL_TIMEOUT_MS,
  );
  return envTimeout ?? DEFAULT_RUNTIME_DEPS_INSTALL_TIMEOUT_MS;
}

function collectInstalledRuntimeClosure(rootNodeModulesDir, dependencySpecs) {
  const packageCache = new Map();
  const closure = new Set();
  const queue = Object.entries(dependencySpecs).map(([depName, spec]) => ({
    depName,
    spec,
    viaName: null,
  }));

  while (queue.length > 0) {
    const item = queue.shift();
    const { depName, spec, viaName } = item;
    const installedVersion = readInstalledDependencyVersion(rootNodeModulesDir, depName);
    if (
      installedVersion === null ||
      !dependencyVersionSatisfied(spec, installedVersion, { depName, viaName })
    ) {
      return null;
    }
    if (closure.has(depName)) {
      continue;
    }

    const packageJsonPath = path.join(
      dependencyNodeModulesPath(rootNodeModulesDir, depName),
      "package.json",
    );
    const packageJson = packageCache.get(depName) ?? readJson(packageJsonPath);
    packageCache.set(depName, packageJson);
    closure.add(depName);

    for (const [childName, childSpec] of Object.entries(packageJson.dependencies ?? {})) {
      queue.push({ depName: childName, spec: childSpec, viaName: depName });
    }
    for (const [childName, childSpec] of Object.entries(packageJson.optionalDependencies ?? {})) {
      queue.push({ depName: childName, spec: childSpec, viaName: depName });
    }
  }

  return [...closure];
}

function pruneStagedInstalledDependencyCargo(nodeModulesDir, depName) {
  const prunePaths = stagedRuntimeDepPruneRules.get(depName);
  if (!prunePaths) {
    return;
  }
  const depRoot = dependencyNodeModulesPath(nodeModulesDir, depName);
  for (const relativePath of prunePaths) {
    removePathIfExists(path.join(depRoot, relativePath));
  }
}

function pruneStagedRuntimeDependencyCargo(nodeModulesDir) {
  for (const depName of stagedRuntimeDepPruneRules.keys()) {
    pruneStagedInstalledDependencyCargo(nodeModulesDir, depName);
  }
}

function listBundledPluginRuntimeDirs(repoRoot) {
  const extensionsRoot = path.join(repoRoot, "dist", "extensions");
  if (!fs.existsSync(extensionsRoot)) {
    return [];
  }

  return fs
    .readdirSync(extensionsRoot, { withFileTypes: true })
    .filter((dirent) => dirent.isDirectory())
    .map((dirent) => path.join(extensionsRoot, dirent.name))
    .filter((pluginDir) => fs.existsSync(path.join(pluginDir, "package.json")));
}

function hasRuntimeDeps(packageJson) {
  return (
    Object.keys(packageJson.dependencies ?? {}).length > 0 ||
    Object.keys(packageJson.optionalDependencies ?? {}).length > 0
  );
}

function shouldStageRuntimeDeps(packageJson) {
  return packageJson.openclaw?.bundle?.stageRuntimeDependencies === true;
}

function sanitizeBundledManifestForRuntimeInstall(pluginDir) {
  const manifestPath = path.join(pluginDir, "package.json");
  const packageJson = readJson(manifestPath);
  let changed = false;

  if (packageJson.peerDependencies) {
    delete packageJson.peerDependencies;
    changed = true;
  }

  if (packageJson.peerDependenciesMeta) {
    delete packageJson.peerDependenciesMeta;
    changed = true;
  }

  if (packageJson.devDependencies) {
    delete packageJson.devDependencies;
    changed = true;
  }

  if (changed) {
    writeJson(manifestPath, packageJson);
  }

  return packageJson;
}

function resolveRuntimeDepsStampPath(pluginDir) {
  return path.join(pluginDir, ".openclaw-runtime-deps-stamp.json");
}

function createRuntimeDepsFingerprint(packageJson) {
  return createHash("sha256")
    .update(
      JSON.stringify({
        packageJson,
        pruneRules: [...stagedRuntimeDepPruneRules.entries()],
        version: runtimeDepsStagingVersion,
      }),
    )
    .digest("hex");
}

function readRuntimeDepsStamp(stampPath) {
  if (!fs.existsSync(stampPath)) {
    return null;
  }
  try {
    return readJson(stampPath);
  } catch {
    return null;
  }
}

function stageInstalledRootRuntimeDeps(params) {
  const { fingerprint, packageJson, pluginDir, repoRoot } = params;
  const dependencySpecs = {
    ...packageJson.dependencies,
    ...packageJson.optionalDependencies,
  };
  const rootNodeModulesDir = path.join(repoRoot, "node_modules");
  if (Object.keys(dependencySpecs).length === 0 || !fs.existsSync(rootNodeModulesDir)) {
    return false;
  }

  const dependencyNames = collectInstalledRuntimeClosure(rootNodeModulesDir, dependencySpecs);
  if (dependencyNames === null) {
    return false;
  }

  const nodeModulesDir = path.join(pluginDir, "node_modules");
  const stampPath = resolveRuntimeDepsStampPath(pluginDir);
  const stagedNodeModulesDir = path.join(
    makeTempDir(
      os.tmpdir(),
      `openclaw-runtime-deps-${sanitizeTempPrefixSegment(path.basename(pluginDir))}-`,
    ),
    "node_modules",
  );

  try {
    for (const depName of dependencyNames) {
      const sourcePath = dependencyNodeModulesPath(rootNodeModulesDir, depName);
      const targetPath = dependencyNodeModulesPath(stagedNodeModulesDir, depName);
      fs.mkdirSync(path.dirname(targetPath), { recursive: true });
      fs.cpSync(sourcePath, targetPath, { recursive: true, force: true, dereference: true });
    }
    pruneStagedRuntimeDependencyCargo(stagedNodeModulesDir);

    replaceDir(nodeModulesDir, stagedNodeModulesDir);
    writeJson(stampPath, {
      fingerprint,
      generatedAt: new Date().toISOString(),
    });
    return true;
  } finally {
    removePathIfExists(path.dirname(stagedNodeModulesDir));
  }
}

function installPluginRuntimeDeps(params) {
  const { fingerprint, packageJson, pluginDir, pluginId, repoRoot } = params;
  if (
    repoRoot &&
    stageInstalledRootRuntimeDeps({ fingerprint, packageJson, pluginDir, repoRoot })
  ) {
    return;
  }
  const installTimeoutMs = resolveInstallTimeoutMs(params);
  const nodeModulesDir = path.join(pluginDir, "node_modules");
  const stampPath = resolveRuntimeDepsStampPath(pluginDir);
  const tempInstallDir = makeTempDir(
    os.tmpdir(),
    `openclaw-runtime-deps-${sanitizeTempPrefixSegment(pluginId)}-`,
  );
  const npmRunner = resolveNpmRunner({
    npmArgs: [
      "install",
      "--omit=dev",
      "--silent",
      "--ignore-scripts",
      "--legacy-peer-deps",
      "--package-lock=false",
    ],
  });
  try {
    writeJson(path.join(tempInstallDir, "package.json"), packageJson);
    const result = spawnSync(npmRunner.command, npmRunner.args, {
      cwd: tempInstallDir,
      encoding: "utf8",
      env: npmRunner.env,
      stdio: "pipe",
      shell: npmRunner.shell,
      killSignal: "SIGKILL",
      timeout: installTimeoutMs,
      windowsVerbatimArguments: npmRunner.windowsVerbatimArguments,
    });
    if (result.error?.code === "ETIMEDOUT") {
      const error = new Error(
        `failed to stage bundled runtime deps for ${pluginId}: npm install timed out after ${installTimeoutMs}ms. ` +
          "This fallback path runs when the root node_modules tree cannot satisfy the bundled plugin's declared runtime dependency versions; align those versions or run the build where npm can reach the registry.",
      );
      error.code = RUNTIME_DEPS_INSTALL_TIMEOUT_CODE;
      throw error;
    }
    if (result.status !== 0) {
      const output = [result.stderr, result.stdout].filter(Boolean).join("\n").trim();
      throw new Error(
        `failed to stage bundled runtime deps for ${pluginId}: ${output || "npm install failed"}`,
      );
    }

    const stagedNodeModulesDir = path.join(tempInstallDir, "node_modules");
    if (!fs.existsSync(stagedNodeModulesDir)) {
      throw new Error(
        `failed to stage bundled runtime deps for ${pluginId}: npm install produced no node_modules directory`,
      );
    }

    pruneStagedRuntimeDependencyCargo(stagedNodeModulesDir);

    replaceDir(nodeModulesDir, stagedNodeModulesDir);
    writeJson(stampPath, {
      fingerprint,
      generatedAt: new Date().toISOString(),
    });
  } finally {
    removePathIfExists(tempInstallDir);
  }
}

function installPluginRuntimeDepsWithRetries(params) {
  const { attempts = 3 } = params;
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      params.install({ ...params.installParams, attempt });
      return;
    } catch (error) {
      lastError = error;
      if (error?.code === RUNTIME_DEPS_INSTALL_TIMEOUT_CODE) {
        break;
      }
      if (attempt === attempts) {
        break;
      }
    }
  }
  throw lastError;
}

export function stageBundledPluginRuntimeDeps(params = {}) {
  const repoRoot = params.cwd ?? params.repoRoot ?? process.cwd();
  const installPluginRuntimeDepsImpl =
    params.installPluginRuntimeDepsImpl ?? installPluginRuntimeDeps;
  const installAttempts = params.installAttempts ?? 3;
  const installTimeoutMs = resolveInstallTimeoutMs(params);
  for (const pluginDir of listBundledPluginRuntimeDirs(repoRoot)) {
    const pluginId = path.basename(pluginDir);
    const packageJson = sanitizeBundledManifestForRuntimeInstall(pluginDir);
    const nodeModulesDir = path.join(pluginDir, "node_modules");
    const stampPath = resolveRuntimeDepsStampPath(pluginDir);
    if (!hasRuntimeDeps(packageJson) || !shouldStageRuntimeDeps(packageJson)) {
      removePathIfExists(nodeModulesDir);
      removePathIfExists(stampPath);
      continue;
    }
    const fingerprint = createRuntimeDepsFingerprint(packageJson);
    const stamp = readRuntimeDepsStamp(stampPath);
    if (fs.existsSync(nodeModulesDir) && stamp?.fingerprint === fingerprint) {
      continue;
    }
    installPluginRuntimeDepsWithRetries({
      attempts: installAttempts,
      install: installPluginRuntimeDepsImpl,
      installParams: {
        fingerprint,
        packageJson,
        pluginDir,
        pluginId,
        repoRoot,
        installTimeoutMs,
      },
    });
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  stageBundledPluginRuntimeDeps();
}
