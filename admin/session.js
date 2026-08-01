(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.HelpCatAdminSession = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function logout(request, clearSession, showLogin, state) {
    if (state.busy) return Promise.resolve(false);
    state.busy = true;
    return request("/api/v1/auth/logout", { method: "POST" }).catch(function () {
      return null;
    }).then(function () {
      clearSession(true);
      showLogin("已安全退出");
      return true;
    }).finally(function () {
      state.busy = false;
    });
  }

  return { logout: logout };
}));
