import { createHash, randomBytes } from "node:crypto";

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

function encodeTime(ms: number, length: number): string {
  let value = Math.max(0, Math.floor(ms));
  let out = "";
  for (let index = 0; index < length; index += 1) {
    out = CROCKFORD[value % 32] + out;
    value = Math.floor(value / 32);
  }
  return out;
}

function encodeRandom(length: number): string {
  const bytes = randomBytes(length);
  let out = "";
  for (const byte of bytes) {
    out += CROCKFORD[byte % 32];
    if (out.length >= length) {
      break;
    }
  }
  return out.padEnd(length, "0");
}

export function generateUlid(nowMs = Date.now()): string {
  return `${encodeTime(nowMs, 10)}${encodeRandom(16)}`;
}

export function sha1(value: string): string {
  return createHash("sha1").update(value).digest("hex");
}

export function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

export function normalizeWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function normalizeName(value: string): string {
  return normalizeWhitespace(value).toLowerCase();
}

export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((entry) => canonicalJson(entry)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .toSorted(([left], [right]) => left.localeCompare(right))
      .map(([key, entry]) => `${JSON.stringify(key)}:${canonicalJson(entry)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function textFingerprint(value: string | null | undefined): string {
  return sha1(normalizeWhitespace(value ?? "").toLowerCase());
}
