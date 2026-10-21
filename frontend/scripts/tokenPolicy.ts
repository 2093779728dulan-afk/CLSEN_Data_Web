export type TokenPolicyRule = "raw-color" | "raw-motion-duration";

export type TokenPolicyException = {
  file: string;
  rule: TokenPolicyRule;
  value: string;
  reason: string;
  approved_by: string;
};

export type TokenPolicyAllowlist = {
  schema_version: 1;
  exceptions: TokenPolicyException[];
};

export type TokenPolicySource = {
  path: string;
  content: string;
};

export type TokenPolicyViolation = {
  file: string;
  line: number;
  rule: TokenPolicyRule;
  value: string;
};

type IndexedViolation = TokenPolicyViolation & { index: number };

const colorPattern = /#[0-9a-f]{3,8}\b|(?:rgb|rgba|hsl|hsla)\([^)]*\)/gi;
const motionDeclarationPattern = /\b(?:animation(?:-duration)?|transition(?:-duration)?)\s*:\s*([^;{}]+);/gi;
const durationPattern = /\b(?:\d+(?:\.\d+)?|\.\d+)(?:ms|s)\b/gi;

function normalizePath(path: string) {
  return path.replaceAll("\\", "/").replace(/^\.\//, "");
}

function lineAt(content: string, index: number) {
  return content.slice(0, index).split("\n").length;
}

function stripComments(content: string) {
  return content.replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, " "));
}

function validateAllowlist(allowlist: TokenPolicyAllowlist) {
  if (allowlist.schema_version !== 1 || !Array.isArray(allowlist.exceptions)) {
    throw new Error("Token policy allowlist must use schema_version 1 with an exceptions array.");
  }

  for (const exception of allowlist.exceptions) {
    if (!exception.reason?.trim() || !exception.approved_by?.trim()) {
      throw new Error("Every token policy exception requires reason and approved_by.");
    }
  }
}

function isAllowed(violation: TokenPolicyViolation, allowlist: TokenPolicyAllowlist) {
  return allowlist.exceptions.some((exception) => (
    normalizePath(exception.file) === violation.file
    && exception.rule === violation.rule
    && exception.value.toLowerCase() === violation.value.toLowerCase()
  ));
}

export function checkTokenPolicy(
  sources: TokenPolicySource[],
  allowlist: TokenPolicyAllowlist,
): TokenPolicyViolation[] {
  validateAllowlist(allowlist);
  const violations: IndexedViolation[] = [];

  for (const source of sources) {
    const file = normalizePath(source.path);
    const content = stripComments(source.content);

    for (const match of content.matchAll(colorPattern)) {
      const index = match.index ?? 0;
      violations.push({ file, line: lineAt(content, index), rule: "raw-color", value: match[0], index });
    }

    for (const declaration of content.matchAll(motionDeclarationPattern)) {
      const value = declaration[1];
      if (value === undefined) continue;
      const valueOffset = (declaration.index ?? 0) + declaration[0].indexOf(value);
      for (const match of value.matchAll(durationPattern)) {
        const index = valueOffset + (match.index ?? 0);
        violations.push({
          file,
          line: lineAt(content, index),
          rule: "raw-motion-duration",
          value: match[0],
          index,
        });
      }
    }
  }

  return violations
    .sort((left, right) => left.file.localeCompare(right.file) || left.index - right.index)
    .filter((violation) => !isAllowed(violation, allowlist))
    .map((violation) => ({
      file: violation.file,
      line: violation.line,
      rule: violation.rule,
      value: violation.value,
    }));
}
