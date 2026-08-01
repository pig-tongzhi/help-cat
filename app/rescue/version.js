(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.HelpCatVersion = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function checkForUpdate(fetchPage, path, current, showUpdate) {
    return fetchPage(path, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("version_check_failed");
        return response.text();
      })
      .then(function (html) {
        var match = html.match(/data-app-version="([^"]+)"/);
        if (match && match[1] !== current) showUpdate();
      }).catch(function () {
        return null;
      });
  }

  return { checkForUpdate: checkForUpdate };
}));
