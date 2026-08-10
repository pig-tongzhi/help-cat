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

function loadRouteRuntime() {
  const source = fs.readFileSync(path.join(__dirname, "../../app/rescue/app.js"), "utf8");
  const eventSetup = source.indexOf('  document.addEventListener("error"');
  assert.notEqual(eventSetup, -1, "route test hook must follow the app route functions");
  const views = ["home", "cats", "tasks", "profile", "story-77"].map((view) => ({
    dataset: { view },
    classList: { toggle() {} },
    hidden: false
  }));
  const navItems = ["home", "cats", "tasks", "profile"].map((nav) => ({
    dataset: { nav },
    classList: { toggle() {} }
  }));
  const elements = { "floating-add-cat": {}, "bottom-nav": {} };
  const window = {
    location: { hash: "#home" },
    scrollY: 0,
    pageYOffset: 0,
    matchMedia() { return { matches: true }; },
    scrollTo(options) { this.scrollY = options.top; this.pageYOffset = options.top; },
    history: {
      pushState(_state, _title, hash) { window.location.hash = hash; },
      replaceState(_state, _title, hash) { window.location.hash = hash; }
    }
  };
  const sandbox = {
    window,
    document: {
      getElementById(id) { return elements[id] || {}; },
      querySelectorAll(selector) {
        if (selector === "[data-view]") return views;
        if (selector === ".nav-item") return navItems;
        return [];
      }
    }
  };
  const routeOnlySource = source.slice(0, eventSetup) +
    '\n  window.__routeTest = { state: state, navigate: navigate, syncRouteFromHash: syncRouteFromHash };\n}());\n';
  vm.runInNewContext(routeOnlySource, sandbox, { filename: "app.js" });
  return { window, route: window.__routeTest };
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

test("hash Back traversal keeps the original home scroll after visiting cats from the story", () => {
  const { window, route } = loadRouteRuntime();
  window.scrollY = 247;
  window.pageYOffset = 247;

  route.navigate("story-77");
  route.navigate("cats");
  window.location.hash = "#story-77";
  route.syncRouteFromHash();
  window.location.hash = "#home";
  route.syncRouteFromHash();

  assert.equal(route.state.homeScrollY, 247);
  assert.equal(window.scrollY, 247);
});
