import { access, mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import { request, type APIRequestContext } from "@playwright/test";

type LoginPayload = { csrf_token: string };

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required by the catalog live runner.`);
  return value;
}

function assertOwned(pathValue: string): string {
  const root = resolve(required("CATALOG_LIVE_RUNTIME_ROOT"));
  const candidate = resolve(pathValue);
  if (candidate === root || !candidate.startsWith(`${root}\\`)) {
    throw new Error("Catalog live state path is outside the runner-owned root.");
  }
  return candidate;
}

async function login(
  baseURL: string,
  username: string,
  password: string,
): Promise<{ context: APIRequestContext; csrfToken: string }> {
  const context = await request.newContext({ baseURL });
  const csrfResponse = await context.get("/api/auth/csrf");
  if (!csrfResponse.ok()) throw new Error("Catalog live login CSRF bootstrap failed.");
  const csrf = await csrfResponse.json() as { csrf_token: string };
  const response = await context.post("/api/auth/login", {
    data: { password, username },
    headers: { "X-CSRF-Token": csrf.csrf_token },
  });
  if (!response.ok()) throw new Error("Catalog live login failed.");
  const payload = await response.json() as LoginPayload;
  return { context, csrfToken: payload.csrf_token };
}

async function createUser(
  admin: APIRequestContext,
  csrfToken: string,
  user: { displayName: string; password: string; role: "data_manager" | "viewer"; username: string },
) {
  const operationToken = crypto.randomUUID();
  const response = await admin.post("/api/admin/users", {
    data: {
      display_name: user.displayName,
      password: user.password,
      roles: [user.role],
      username: user.username,
    },
    headers: {
      "Idempotency-Key": operationToken,
      "X-CSRF-Token": csrfToken,
    },
  });
  if (response.status() !== 201) throw new Error(`Catalog live user creation failed (${response.status()}).`);
  return response.json() as Promise<{ id: number }>;
}

export default async function globalSetup() {
  const baseURL = required("CATALOG_LIVE_FRONTEND_URL");
  const runId = required("CATALOG_LIVE_RUN_ID");
  const adminState = assertOwned(required("CATALOG_LIVE_ADMIN_STATE"));
  const managerState = assertOwned(required("CATALOG_LIVE_MANAGER_STATE"));
  const viewerState = assertOwned(required("CATALOG_LIVE_VIEWER_STATE"));
  await Promise.all([adminState, managerState, viewerState].map((pathValue) => mkdir(dirname(pathValue), { recursive: true })));

  if (process.env.CATALOG_LIVE_REUSE_STATES === "1") {
    await Promise.all([
      adminState,
      managerState,
      viewerState,
      assertOwned(required("CATALOG_LIVE_USERS_PATH")),
    ].map((pathValue) => access(pathValue)));
    return;
  }

  const adminUsername = required("CATALOG_LIVE_ADMIN_USERNAME");
  const adminPassword = required("CATALOG_LIVE_ADMIN_PASSWORD");
  const managerUsername = `catalog-live-manager-${runId}`;
  const viewerUsername = `catalog-live-viewer-${runId}`;
  const managerPassword = required("CATALOG_LIVE_MANAGER_PASSWORD");
  const viewerPassword = required("CATALOG_LIVE_VIEWER_PASSWORD");
  const adminLogin = await login(baseURL, adminUsername, adminPassword);
  try {
    const manager = await createUser(adminLogin.context, adminLogin.csrfToken, {
      displayName: "Catalog Live Manager",
      password: managerPassword,
      role: "data_manager",
      username: managerUsername,
    });
    const viewer = await createUser(adminLogin.context, adminLogin.csrfToken, {
      displayName: "Catalog Live Viewer",
      password: viewerPassword,
      role: "viewer",
      username: viewerUsername,
    });
    await adminLogin.context.storageState({ path: adminState });
    const managerLogin = await login(baseURL, managerUsername, managerPassword);
    const viewerLogin = await login(baseURL, viewerUsername, viewerPassword);
    try {
      await managerLogin.context.storageState({ path: managerState });
      await viewerLogin.context.storageState({ path: viewerState });
      const usersPath = assertOwned(required("CATALOG_LIVE_USERS_PATH"));
      await writeFile(usersPath, JSON.stringify({ manager_id: manager.id, viewer_id: viewer.id }), { encoding: "utf8", mode: 0o600 });
    } finally {
      await managerLogin.context.dispose();
      await viewerLogin.context.dispose();
    }
  } finally {
    await adminLogin.context.dispose();
  }
}
