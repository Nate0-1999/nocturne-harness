import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

import { LocationFence } from "./location_fence.mjs";

const requireFromPi = createRequire(import.meta.resolve("@earendil-works/pi-coding-agent"));
const { Type } = await import(pathToFileURL(requireFromPi.resolve("typebox")).href);

const STATUS_KEY = "nocturne-presence";
const ACTIVE_TOOLS = ["read", "edit", "write", "grep", "find", "ls", "move"];

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

  async function move(rawPath, ctx) {
    const location = await fence.move(rawPath);
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

  pi.on("session_start", async (_event, ctx) => {
    const location = await fence.initialize();
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
