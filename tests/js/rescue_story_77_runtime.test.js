const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const assert = require("node:assert/strict");

function loadStory() {
  const source = fs.readFileSync(path.join(__dirname, "../../app/rescue/story-77.js"), "utf8");
  const sandbox = { window: {} };
  vm.runInNewContext(source, sandbox, { filename: "story-77.js" });
  return sandbox.window.HelpCatStory77;
}

test("77 story module exposes its approved timeline and action hooks", () => {
  const story = loadStory();

  assert.equal(typeof story.render, "function");
  const html = story.renderToString();
  assert.match(html, /2025 年 6 月 2 日/);
  assert.match(html, /农历五月初七/);
  assert.match(html, /从 77 到每一只小猫/);
  assert.match(html, /data-story-action="cats"/);
  assert.match(html, /data-story-action="create-cat"/);
});

test("77 story render connects its injected actions without inline handlers", () => {
  const story = loadStory();
  const listeners = {};
  const buttons = ["cats", "create-cat", "back-home"].map((action) => ({
    dataset: { storyAction: action },
    addEventListener(type, callback) { listeners[action + ":" + type] = callback; }
  }));
  const container = {
    innerHTML: "",
    querySelectorAll() { return buttons; }
  };
  const calls = [];

  story.render(container, {
    openCats() { calls.push("cats"); },
    openCreateCat() { calls.push("create-cat"); },
    backHome() { calls.push("back-home"); }
  });
  buttons.forEach((button) => listeners[button.dataset.storyAction + ":click"]());

  assert.match(container.innerHTML, /data-story-action="back-home"/);
  assert.deepEqual(calls, ["cats", "create-cat", "back-home"]);
});
