import { realpath, stat } from "node:fs/promises";
import { basename, dirname, isAbsolute, relative, resolve, sep } from "node:path";

const READ_TOOLS = new Set(["read", "grep", "find", "ls"]);
const WRITE_TOOLS = new Set(["edit", "write"]);
const CREDENTIAL_SEGMENTS = new Set([".ssh", ".aws", ".gnupg", ".kube"]);

function isCredentialPath(target) {
  const segments = resolve(target).split(sep).filter(Boolean);
  const name = segments.at(-1)?.toLowerCase() ?? "";
  if (segments.some((segment) => CREDENTIAL_SEGMENTS.has(segment.toLowerCase()))) return true;
  if (name === ".env" || name.startsWith(".env.")) return true;
  if (/^(?:id_rsa|id_ed25519|credentials|service-account.*\.json)$/.test(name)) return true;
  return segments.some((segment, index) =>
    segment.toLowerCase() === ".config" && segments[index + 1]?.toLowerCase() === "gcloud"
  );
}

function cleanPath(rawPath) {
  if (typeof rawPath !== "string" || rawPath.trim() === "") {
    throw new Error("path must be a nonblank string");
  }
  const trimmed = rawPath.trim();
  return trimmed.startsWith("@") ? trimmed.slice(1) : trimmed;
}

function isInside(root, target) {
  const remainder = relative(root, target);
  return (
    remainder === "" ||
    (remainder !== ".." && !remainder.startsWith(`..${sep}`) && !isAbsolute(remainder))
  );
}

async function canonicalize(candidate) {
  let cursor = resolve(candidate);
  const missing = [];
  while (true) {
    try {
      const existing = await realpath(cursor);
      return resolve(existing, ...missing.reverse());
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      const parent = dirname(cursor);
      if (parent === cursor) throw error;
      missing.push(basename(cursor));
      cursor = parent;
    }
  }
}

export class LocationFence {
  constructor({ workspaceRoot, initialLocation, fenceReads = false }) {
    this._workspaceInput = resolve(cleanPath(workspaceRoot));
    this._locationInput = resolve(cleanPath(initialLocation));
    this.fenceReads = fenceReads === true;
    this.workspaceRoot = undefined;
    this.location = undefined;
  }

  async initialize() {
    if (this.workspaceRoot !== undefined) return this.location;
    const workspaceRoot = await realpath(this._workspaceInput);
    const location = await realpath(this._locationInput);
    const locationStat = await stat(location);
    if (!locationStat.isDirectory()) throw new Error("initial location must be a directory");
    if (!isInside(workspaceRoot, location)) {
      throw new Error("initial location must be inside the workspace root");
    }
    this.workspaceRoot = workspaceRoot;
    this.location = location;
    return location;
  }

  async move(rawPath) {
    await this.initialize();
    const target = await realpath(resolve(this.location, cleanPath(rawPath)));
    const targetStat = await stat(target);
    if (!targetStat.isDirectory()) throw new Error(`Cannot move to ${target}: not a directory.`);
    if (!isInside(this.workspaceRoot, target)) {
      throw new Error(`Cannot move outside the workspace ${this.workspaceRoot}.`);
    }
    this.location = target;
    return target;
  }

  async preflight(toolName, input) {
    await this.initialize();
    if (!READ_TOOLS.has(toolName) && !WRITE_TOOLS.has(toolName)) return undefined;

    const supplied = input?.path;
    const rawPath = supplied === undefined && toolName !== "read" ? "." : supplied;
    const target = await canonicalize(resolve(this.location, cleanPath(rawPath)));
    if (READ_TOOLS.has(toolName) && isCredentialPath(target)) {
      return {
        block: true,
        reason: "That path may contain credentials. Ask the owner before reading it.",
      };
    }
    const fenced = WRITE_TOOLS.has(toolName) || this.fenceReads;
    if (fenced && !isInside(this.location, target)) {
      const remedy = WRITE_TOOLS.has(toolName) ? dirname(target) : target;
      return {
        block: true,
        reason: `That path is outside this agent's location. Move to ${remedy} first.`,
      };
    }

    input.path = target;
    return {
      block: false,
      target,
      event: WRITE_TOOLS.has(toolName) ? "write" : "read",
    };
  }
}
