import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { cleanupTrackedTempDirs, makeTrackedTempDir } from "./test-helpers/fs-fixtures.js";

type StageRuntimeDepsInstallParams = {
  packageJson: Record<string, unknown>;
  installTimeoutMs?: number;
};

type StageBundledPluginRuntimeDeps = (params?: {
  cwd?: string;
  repoRoot?: string;
  installAttempts?: number;
  installTimeoutMs?: number;
  installPluginRuntimeDepsImpl?: (params: StageRuntimeDepsInstallParams) => void;
}) => void;

async function loadStageBundledPluginRuntimeDeps(): Promise<StageBundledPluginRuntimeDeps> {
  const moduleUrl = new URL("../../scripts/stage-bundled-plugin-runtime-deps.mjs", import.meta.url);
  const loaded = (await import(moduleUrl.href)) as {
    stageBundledPluginRuntimeDeps: StageBundledPluginRuntimeDeps;
  };
  return loaded.stageBundledPluginRuntimeDeps;
}

const tempDirs: string[] = [];

function makeRepoRoot(prefix: string): string {
  return makeTrackedTempDir(prefix, tempDirs);
}

function writeRepoFile(repoRoot: string, relativePath: string, value: string) {
  const fullPath = path.join(repoRoot, relativePath);
  fs.mkdirSync(path.dirname(fullPath), { recursive: true });
  fs.writeFileSync(fullPath, value, "utf8");
}

afterEach(() => {
  cleanupTrackedTempDirs(tempDirs);
});

describe("stageBundledPluginRuntimeDeps", () => {
  it("drops Lark SDK type cargo while keeping runtime entrypoints", () => {
    const repoRoot = makeRepoRoot("openclaw-stage-bundled-runtime-deps-");

    writeRepoFile(
      repoRoot,
      "dist/extensions/feishu/package.json",
      JSON.stringify(
        {
          name: "@openclaw/feishu",
          version: "2026.4.10",
          dependencies: {
            "@larksuiteoapi/node-sdk": "^1.60.0",
          },
          openclaw: {
            bundle: {
              stageRuntimeDependencies: true,
            },
          },
        },
        null,
        2,
      ),
    );

    writeRepoFile(
      repoRoot,
      "node_modules/@larksuiteoapi/node-sdk/package.json",
      JSON.stringify(
        {
          name: "@larksuiteoapi/node-sdk",
          version: "1.60.0",
          main: "./lib/index.js",
          module: "./es/index.js",
          types: "./types",
        },
        null,
        2,
      ),
    );
    writeRepoFile(
      repoRoot,
      "node_modules/@larksuiteoapi/node-sdk/lib/index.js",
      "export const runtime = true;\n",
    );
    writeRepoFile(
      repoRoot,
      "node_modules/@larksuiteoapi/node-sdk/es/index.js",
      "export const moduleRuntime = true;\n",
    );
    writeRepoFile(
      repoRoot,
      "node_modules/@larksuiteoapi/node-sdk/types/index.d.ts",
      "export interface HugeTypeSurface {}\n",
    );

    return loadStageBundledPluginRuntimeDeps().then((stageBundledPluginRuntimeDeps) => {
      stageBundledPluginRuntimeDeps({ repoRoot });

      const stagedRoot = path.join(
        repoRoot,
        "dist",
        "extensions",
        "feishu",
        "node_modules",
        "@larksuiteoapi",
        "node-sdk",
      );
      expect(fs.existsSync(path.join(stagedRoot, "lib", "index.js"))).toBe(true);
      expect(fs.existsSync(path.join(stagedRoot, "es", "index.js"))).toBe(true);
      expect(fs.existsSync(path.join(stagedRoot, "types"))).toBe(false);
    });
  });

  it("strips non-runtime dependency sections before temp npm staging", async () => {
    const repoRoot = makeRepoRoot("openclaw-stage-bundled-runtime-manifest-");
    writeRepoFile(
      repoRoot,
      "dist/extensions/amazon-bedrock/package.json",
      JSON.stringify(
        {
          name: "@openclaw/amazon-bedrock-provider",
          version: "2026.4.10",
          dependencies: {
            "@aws-sdk/client-bedrock": "3.1024.0",
          },
          devDependencies: {
            "@openclaw/plugin-sdk": "workspace:*",
          },
          peerDependencies: {
            openclaw: "^0.0.0",
          },
          peerDependenciesMeta: {
            openclaw: {
              optional: true,
            },
          },
          openclaw: {
            bundle: {
              stageRuntimeDependencies: true,
            },
          },
        },
        null,
        2,
      ),
    );

    const stageBundledPluginRuntimeDeps = await loadStageBundledPluginRuntimeDeps();
    const installs: Array<Record<string, unknown>> = [];
    stageBundledPluginRuntimeDeps({
      repoRoot,
      installAttempts: 1,
      installPluginRuntimeDepsImpl(params: { packageJson: Record<string, unknown> }) {
        installs.push(params.packageJson);
      },
    });

    expect(installs).toHaveLength(1);
    expect(installs[0]?.dependencies).toEqual({
      "@aws-sdk/client-bedrock": "3.1024.0",
    });
    expect(installs[0]?.devDependencies).toBeUndefined();
    expect(installs[0]?.peerDependencies).toBeUndefined();
    expect(installs[0]?.peerDependenciesMeta).toBeUndefined();
  });

  it("passes a bounded install timeout into fallback npm staging", async () => {
    const repoRoot = makeRepoRoot("openclaw-stage-bundled-runtime-timeout-");
    writeRepoFile(
      repoRoot,
      "dist/extensions/amazon-bedrock/package.json",
      JSON.stringify(
        {
          name: "@openclaw/amazon-bedrock-provider",
          version: "2026.4.10",
          dependencies: {
            "@aws-sdk/client-bedrock": "3.1024.0",
          },
          openclaw: {
            bundle: {
              stageRuntimeDependencies: true,
            },
          },
        },
        null,
        2,
      ),
    );

    const stageBundledPluginRuntimeDeps = await loadStageBundledPluginRuntimeDeps();
    const installs: StageRuntimeDepsInstallParams[] = [];
    stageBundledPluginRuntimeDeps({
      repoRoot,
      installAttempts: 1,
      installTimeoutMs: 4321,
      installPluginRuntimeDepsImpl(params) {
        installs.push(params);
      },
    });

    expect(installs).toHaveLength(1);
    expect(installs[0]?.installTimeoutMs).toBe(4321);
  });

  it("stages amazon-bedrock from root node_modules when the installed Smithy 4.x closure is accepted", async () => {
    const repoRoot = makeRepoRoot("openclaw-stage-bundled-runtime-bedrock-fast-path-");
    writeRepoFile(
      repoRoot,
      "dist/extensions/amazon-bedrock/package.json",
      JSON.stringify(
        {
          name: "@openclaw/amazon-bedrock-provider",
          version: "2026.4.12",
          dependencies: {
            "@aws-sdk/client-bedrock": "3.1028.0",
          },
          openclaw: {
            bundle: {
              stageRuntimeDependencies: true,
            },
          },
        },
        null,
        2,
      ),
    );
    writeRepoFile(
      repoRoot,
      "node_modules/@aws-sdk/client-bedrock/package.json",
      JSON.stringify(
        {
          name: "@aws-sdk/client-bedrock",
          version: "3.1028.0",
          dependencies: {
            "@aws-crypto/sha256-browser": "5.2.0",
            "@aws-crypto/util": "5.2.0",
          },
        },
        null,
        2,
      ),
    );
    writeRepoFile(
      repoRoot,
      "node_modules/@aws-sdk/client-bedrock/index.js",
      "export const bedrock = true;\n",
    );
    writeRepoFile(
      repoRoot,
      "node_modules/@aws-crypto/sha256-browser/package.json",
      JSON.stringify(
        {
          name: "@aws-crypto/sha256-browser",
          version: "5.2.0",
          dependencies: {
            "@smithy/util-utf8": "^2.0.0",
          },
        },
        null,
        2,
      ),
    );
    writeRepoFile(
      repoRoot,
      "node_modules/@aws-crypto/sha256-browser/index.js",
      "export const browserHash = true;\n",
    );
    writeRepoFile(
      repoRoot,
      "node_modules/@aws-crypto/util/package.json",
      JSON.stringify(
        {
          name: "@aws-crypto/util",
          version: "5.2.0",
          dependencies: {
            "@smithy/util-utf8": "^2.0.0",
          },
        },
        null,
        2,
      ),
    );
    writeRepoFile(repoRoot, "node_modules/@aws-crypto/util/index.js", "export const util = true;\n");
    writeRepoFile(
      repoRoot,
      "node_modules/@smithy/util-utf8/package.json",
      JSON.stringify(
        {
          name: "@smithy/util-utf8",
          version: "4.2.2",
        },
        null,
        2,
      ),
    );
    writeRepoFile(
      repoRoot,
      "node_modules/@smithy/util-utf8/index.js",
      "export const utf8 = true;\n",
    );

    const stageBundledPluginRuntimeDeps = await loadStageBundledPluginRuntimeDeps();
    stageBundledPluginRuntimeDeps({
      repoRoot,
      installAttempts: 1,
    });

    expect(
      fs.existsSync(
        path.join(
          repoRoot,
          "dist/extensions/amazon-bedrock/node_modules/@aws-sdk/client-bedrock/package.json",
        ),
      ),
    ).toBe(true);
    expect(
      fs.existsSync(
        path.join(
          repoRoot,
          "dist/extensions/amazon-bedrock/node_modules/@smithy/util-utf8/package.json",
        ),
      ),
    ).toBe(true);
  });

  it("does not retry install timeouts that already identify a blocked fallback path", async () => {
    const repoRoot = makeRepoRoot("openclaw-stage-bundled-runtime-timeout-no-retry-");
    writeRepoFile(
      repoRoot,
      "dist/extensions/amazon-bedrock/package.json",
      JSON.stringify(
        {
          name: "@openclaw/amazon-bedrock-provider",
          version: "2026.4.10",
          dependencies: {
            "@aws-sdk/client-bedrock": "3.1024.0",
          },
          openclaw: {
            bundle: {
              stageRuntimeDependencies: true,
            },
          },
        },
        null,
        2,
      ),
    );

    const stageBundledPluginRuntimeDeps = await loadStageBundledPluginRuntimeDeps();
    let attempts = 0;
    expect(() =>
      stageBundledPluginRuntimeDeps({
        repoRoot,
        installAttempts: 3,
        installPluginRuntimeDepsImpl() {
          attempts += 1;
          const error = new Error("timed out");
          error.code = "RUNTIME_DEPS_INSTALL_TIMEOUT";
          throw error;
        },
      }),
    ).toThrow("timed out");
    expect(attempts).toBe(1);
  });
});
