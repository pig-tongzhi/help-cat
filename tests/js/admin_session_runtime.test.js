const test = require("node:test");
const assert = require("node:assert/strict");

const session = require("../../admin/session.js");

test("logout revokes the server session and clears both local session keys", async () => {
  const calls = [];
  const state = { busy: false };

  const result = await session.logout(
    (path, options) => { calls.push([path, options]); return Promise.resolve({}); },
    (shared) => { calls.push(["clear", shared]); },
    (message) => { calls.push(["login", message]); },
    state
  );

  assert.equal(result, true);
  assert.deepEqual(calls, [
    ["/api/v1/auth/logout", { method: "POST" }],
    ["clear", true],
    ["login", "已安全退出"]
  ]);
  assert.equal(state.busy, false);
});

test("logout still clears local tokens when the network request fails", async () => {
  const calls = [];
  const state = { busy: false };

  await session.logout(
    () => Promise.reject(new Error("offline")),
    (shared) => { calls.push(["clear", shared]); },
    (message) => { calls.push(["login", message]); },
    state
  );

  assert.deepEqual(calls, [["clear", true], ["login", "已安全退出"]]);
  assert.equal(state.busy, false);
});

test("logout ignores duplicate clicks while a request is active", async () => {
  const state = { busy: true };
  const result = await session.logout(
    () => { throw new Error("must not request"); },
    () => { throw new Error("must not clear"); },
    () => { throw new Error("must not render"); },
    state
  );

  assert.equal(result, false);
  assert.equal(state.busy, true);
});
