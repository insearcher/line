import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

function loadAuth() {
  const source = fs.readFileSync(new URL("./dashboard_auth.js", import.meta.url), "utf8");
  const context = { URLSearchParams };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return context.LineDashboardAuth;
}

test("reads dashboard token from URL hash", () => {
  const auth = loadAuth();

  assert.equal(auth.tokenFromHash("#dashboardToken=dev-token"), "dev-token");
  assert.equal(auth.tokenFromHash("#other=value"), "");
});

test("adds Authorization header when token is present", () => {
  const auth = loadAuth();

  assert.equal(auth.authHeaders("dev-token").Authorization, "Bearer dev-token");
  assert.equal(Object.keys(auth.authHeaders("")).length, 0);
});
