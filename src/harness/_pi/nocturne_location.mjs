import { spawn } from "node:child_process";

import {
  createBashToolDefinition,
  createEditToolDefinition,
  createFindToolDefinition,
  createGrepToolDefinition,
  createLsToolDefinition,
  createReadToolDefinition,
  createWriteToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { LocationFence } from "./location_fence.mjs";

const STATUS_KEY = "nocturne-presence";
const TOOL_RESULT_STATUS_KEY = "nocturne-tool-result";
const ACTIVE_TOOLS = ["read", "edit", "write", "grep", "find", "ls", "bash", "move"];
const TOOL_FACTORIES = {
  read: createReadToolDefinition,
  edit: createEditToolDefinition,
  write: createWriteToolDefinition,
  grep: createGrepToolDefinition,
  find: createFindToolDefinition,
  ls: createLsToolDefinition,
};
const BOUNDARY_COMMAND =
  /\b(?:git\s+push|gh\s+(?:pr|release)|gcloud|aws|az|kubectl|terraform\s+(?:apply|destroy)|curl|wget|ssh|scp|rsync)\b/i;
const CREDENTIAL_COMMAND =
  /(?:^|[\s/])(?:\.env(?:\.[^\s/]*)?|\.ssh|\.aws|\.gnupg|\.kube|id_rsa|id_ed25519)(?:[\s/]|$)|^\s*(?:env|printenv|set)\s*$/i;
const MAX_RESULT_CHARS = 200_000;

function requiredEnvironment(name) {
  const value = process.env[name];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${name} must be configured by the Nocturne adapter`);
  }
  return value;
}

function presenceIdentity() {
  return {
    agent_id: requiredEnvironment("NOCTURNE_AGENT_ID"),
    machine_id: requiredEnvironment("NOCTURNE_MACHINE_ID"),
    session_id: requiredEnvironment("NOCTURNE_SESSION_ID"),
  };
}

export default function nocturneLocationExtension(pi) {
  const identity = presenceIdentity();
  const fence = new LocationFence({
    workspaceRoot: requiredEnvironment("NOCTURNE_WORKSPACE_ROOT"),
    initialLocation: requiredEnvironment("NOCTURNE_INITIAL_LOCATION"),
    fenceReads: process.env.NOCTURNE_FENCE_READS === "1",
  });
  const pendingTouches = new Map();

  function emit(ctx, event, path) {
    ctx.ui.setStatus(
      STATUS_KEY,
      JSON.stringify({ ...identity, event, path, ts: new Date().toISOString() }),
    );
  }

  function emitToolResult(ctx, result) {
    ctx.ui.setStatus(TOOL_RESULT_STATUS_KEY, JSON.stringify(result));
  }

  function resultText(content) {
    const pieces = [];
    for (const item of content ?? []) {
      if (item?.type === "text" && typeof item.text === "string") pieces.push(item.text);
      else if (item?.type === "image") pieces.push("[Image content returned by PI read]");
    }
    const joined = pieces.join("\n");
    return joined.length <= MAX_RESULT_CHARS
      ? joined
      : `${joined.slice(0, MAX_RESULT_CHARS - 1)}…`;
  }

  function boundedError(error) {
    const raw = error instanceof Error ? error.message : String(error);
    const normalized = raw.replace(/\s+/g, " ").trim() || "PI tool execution failed";
    return normalized.length <= 4_000 ? normalized : `${normalized.slice(0, 3_999)}…`;
  }

  function sandboxProfile(location) {
    const quoted = JSON.stringify(location);
    return `(version 1) (deny default) (allow process*) (allow file-read*) ` +
      `(allow sysctl-read) (allow mach-lookup) ` +
      `(allow file-write* (literal ${quoted}) (subpath ${quoted}) ` +
      `(literal "/dev/null"))`;
  }

  function sandboxedBashOperations(location) {
    return {
      async exec(command, cwd, { onData, signal, timeout, env }) {
        if (process.platform !== "darwin") {
          throw new Error(
            "Secure shell is unavailable on this host; use read, edit, and write instead.",
          );
        }
        if (BOUNDARY_COMMAND.test(command)) {
          throw new Error(
            "That command may leave this project or change remote state. Ask the owner to run it explicitly outside Nocturne.",
          );
        }
        if (CREDENTIAL_COMMAND.test(command)) {
          throw new Error(
            "That command may expose credentials. Ask the owner before reading them.",
          );
        }
        const safeEnvironment = {
          PATH: env?.PATH ?? "/usr/bin:/bin:/usr/sbin:/sbin",
          LANG: env?.LANG ?? "en_US.UTF-8",
          LC_ALL: env?.LC_ALL,
          TERM: env?.TERM,
          TMPDIR: location,
          NO_COLOR: env?.NO_COLOR,
        };
        for (const [key, value] of Object.entries(safeEnvironment)) {
          if (value === undefined) delete safeEnvironment[key];
        }
        return await new Promise((resolve, reject) => {
          const child = spawn(
            "/usr/bin/sandbox-exec",
            ["-p", sandboxProfile(location), "/bin/zsh", "-lc", command],
            { cwd, env: safeEnvironment, stdio: ["ignore", "pipe", "pipe"] },
          );
          let settled = false;
          let timer;
          const finish = (callback) => {
            if (settled) return;
            settled = true;
            if (timer !== undefined) clearTimeout(timer);
            signal?.removeEventListener("abort", abort);
            callback();
          };
          const abort = () => {
            child.kill("SIGTERM");
            finish(() => reject(new Error("aborted")));
          };
          child.stdout.on("data", onData);
          child.stderr.on("data", onData);
          child.on("error", (error) => finish(() => reject(error)));
          child.on("close", (code) => finish(() => resolve({ exitCode: code })));
          signal?.addEventListener("abort", abort, { once: true });
          if (timeout !== undefined) {
            timer = setTimeout(() => {
              child.kill("SIGTERM");
              finish(() => reject(new Error(`timeout:${timeout}`)));
            }, timeout * 1_000);
          }
        });
      },
    };
  }

  async function move(rawPath, ctx) {
    const location = await fence.move(rawPath);
    process.env.TMPDIR = location;
    emit(ctx, "cwd_change", location);
    return location;
  }

  pi.registerTool({
    name: "move",
    label: "move",
    description: "Move this agent to a directory before acting on files there.",
    promptSnippet: "Move to a directory; location controls which files this agent may change",
    promptGuidelines: [
      "Use move in its own tool step before editing or writing outside the current location.",
    ],
    parameters: Type.Object(
      { path: Type.String({ description: "Directory path, relative to the current location" }) },
      { additionalProperties: false },
    ),
    async execute(_toolCallId, { path }, _signal, _onUpdate, ctx) {
      const location = await move(path, ctx);
      return {
        content: [{ type: "text", text: `Moved to ${location}.` }],
        details: { location },
      };
    },
  });

  pi.registerCommand("nocturne-move", {
    description: "Internal RPC movement command used by the Nocturne adapter",
    handler: async (args, ctx) => {
      let path;
      try {
        path = JSON.parse(args);
      } catch {
        throw new Error("Nocturne move command requires one JSON string path");
      }
      await move(path, ctx);
    },
  });

  pi.registerCommand("nocturne-tool", {
    description: "Internal tool command used only by the Nocturne RPC adapter",
    handler: async (args, ctx) => {
      let request;
      try {
        request = JSON.parse(args);
      } catch {
        throw new Error("Nocturne tool command requires one JSON object");
      }
      const invocationId = request?.invocation_id;
      const toolName = request?.tool_name;
      const input = request?.arguments;
      if (
        typeof invocationId !== "string" || invocationId.trim() === "" ||
        !ACTIVE_TOOLS.includes(toolName) ||
        input === null || typeof input !== "object" || Array.isArray(input)
      ) {
        throw new Error("Nocturne tool command has invalid fields");
      }
      try {
        if (toolName === "move") {
          const location = await move(input.path, ctx);
          emitToolResult(ctx, {
            invocation_id: invocationId,
            tool_name: toolName,
            success: true,
            content: `Moved to ${location}.`,
          });
          return;
        }
        let outcome;
        if (toolName !== "bash") {
          outcome = await fence.preflight(toolName, input);
          if (outcome?.block) {
            emitToolResult(ctx, {
              invocation_id: invocationId,
              tool_name: toolName,
              success: false,
              content: outcome.reason,
            });
            return;
          }
        }
        const location = await fence.initialize();
        const definition = toolName === "bash"
          ? createBashToolDefinition(location, {
              operations: sandboxedBashOperations(location),
              exposeSessionEnvironment: false,
            })
          : TOOL_FACTORIES[toolName](location);
        const prepared = definition.prepareArguments
          ? definition.prepareArguments(input)
          : input;
        const result = await definition.execute(invocationId, prepared, undefined, undefined, ctx);
        const event = toolName === "bash" || toolName === "edit" || toolName === "write"
          ? "write"
          : "read";
        emit(ctx, event, outcome?.target ?? location);
        emitToolResult(ctx, {
          invocation_id: invocationId,
          tool_name: toolName,
          success: true,
          content: resultText(result.content),
        });
      } catch (error) {
        emitToolResult(ctx, {
          invocation_id: invocationId,
          tool_name: toolName,
          success: false,
          content: boundedError(error),
        });
      }
    },
  });

  pi.on("session_start", async (_event, ctx) => {
    const location = await fence.initialize();
    process.env.TMPDIR = location;
    pi.setActiveTools(ACTIVE_TOOLS);
    emit(ctx, "spawn", location);
  });

  pi.on("tool_call", async (event) => {
    let outcome;
    try {
      outcome = await fence.preflight(event.toolName, event.input);
    } catch (error) {
      return {
        block: true,
        reason: `Path refused: ${error instanceof Error ? error.message : String(error)}`,
      };
    }
    if (outcome?.block) return { block: true, reason: outcome.reason };
    if (outcome?.target) {
      pendingTouches.set(event.toolCallId, { event: outcome.event, path: outcome.target });
    }
    return undefined;
  });

  pi.on("tool_result", async (event, ctx) => {
    const touch = pendingTouches.get(event.toolCallId);
    pendingTouches.delete(event.toolCallId);
    if (touch && !event.isError) emit(ctx, touch.event, touch.path);
  });

  pi.on("turn_end", async (_event, ctx) => {
    const location = await fence.initialize();
    emit(ctx, "idle", location);
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    const location = await fence.initialize();
    emit(ctx, "exit", location);
  });
}
