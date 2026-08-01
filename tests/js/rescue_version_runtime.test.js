const test = require("node:test");
const assert = require("node:assert/strict");

const version = require("../../app/rescue/version.js");

function response(ok, html) {
  return { ok, text: () => Promise.resolve(html) };
}

test("same version does not show the update banner", async () => {
  let shown = 0;
  await version.checkForUpdate(
    () => Promise.resolve(response(true, '<html data-app-version="v1">')),
    "/help-cat/rescue/index.html",
    "v1",
    () => { shown += 1; }
  );
  assert.equal(shown, 0);
});

test("new version shows the update banner", async () => {
  let shown = 0;
  await version.checkForUpdate(
    (path, options) => {
      assert.equal(path, "/help-cat/rescue/index.html");
      assert.deepEqual(options, { cache: "no-store" });
      return Promise.resolve(response(true, '<html data-app-version="v2">'));
    },
    "/help-cat/rescue/index.html",
    "v1",
    () => { shown += 1; }
  );
  assert.equal(shown, 1);
});

test("non-2xx and malformed responses never hide or re-trigger an existing banner", async () => {
  let shown = 0;
  const show = () => { shown += 1; };
  await version.checkForUpdate(() => Promise.resolve(response(true, '<html data-app-version="v2">')), "/", "v1", show);
  await version.checkForUpdate(() => Promise.resolve(response(false, "server error")), "/", "v1", show);
  await version.checkForUpdate(() => Promise.resolve(response(true, "missing version")), "/", "v1", show);
  await version.checkForUpdate(() => Promise.reject(new Error("offline")), "/", "v1", show);
  assert.equal(shown, 1);
});
