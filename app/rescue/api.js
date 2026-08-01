(function (global) {
  "use strict";

  var API_BASE = "/help-cat-api";
  var TOKEN_KEY = "help_cat_token";
  var USER_KEY = "help_cat_user";

  function token() {
    return sessionStorage.getItem("help_cat_token") || "";
  }

  function user() {
    try {
      return JSON.parse(sessionStorage.getItem(USER_KEY) || "null");
    } catch (error) {
      return null;
    }
  }

  function saveSession(payload) {
    if (payload && payload.access_token) {
      sessionStorage.setItem(TOKEN_KEY, payload.access_token);
    }
    if (payload && payload.user) {
      sessionStorage.setItem(USER_KEY, JSON.stringify(payload.user));
    }
    return payload && payload.user ? payload.user : null;
  }

  function clearSession() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
  }

  function request(path, options) {
    var config = options || {};
    var headers = Object.assign({}, config.headers || {});
    var body;
    if (config.form) {
      body = config.form;
    } else if (config.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(config.body);
    }
    if (token()) {
      headers.Authorization = "Bearer " + token();
    }
    return fetch(API_BASE + path, {
      method: config.method || "GET",
      headers: headers,
      body: body
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) {
          if (response.status === 401) clearSession();
          throw {
            status: response.status,
            code: payload.code || "request_failed",
            message: payload.message || "请求失败，请稍后重试"
          };
        }
        return payload;
      });
    }).catch(function (error) {
      if (error && error.code) throw error;
      throw { status: 0, code: "network_error", message: "网络连接失败，请检查后重试" };
    });
  }

  function login(username, password) {
    return request("/api/v1/auth/login", {
      method: "POST",
      body: { username: username, password: password }
    }).then(saveSession);
  }

  function register(username, password) {
    return request("/api/v1/auth/register", {
      method: "POST",
      body: { username: username, password: password }
    }).then(saveSession);
  }

  function restoreSession() {
    if (!token()) return Promise.resolve(null);
    return request("/api/v1/auth/me").then(function (profile) {
      sessionStorage.setItem(USER_KEY, JSON.stringify(profile));
      return profile;
    }).catch(function (error) {
      if (error.status === 401 || error.status === 403) {
        clearSession();
        return null;
      }
      throw error;
    });
  }

  function logout() {
    if (!token()) {
      clearSession();
      return Promise.resolve();
    }
    return request("/api/v1/auth/logout", { method: "POST" }).catch(function () {
      return null;
    }).then(clearSession);
  }

  function uploadImage(file) {
    var form = new FormData();
    form.append("file", file);
    return request("/api/v1/media/images", { method: "POST", form: form });
  }

  global.HelpCatApi = {
    API_BASE: API_BASE,
    token: token,
    user: user,
    request: request,
    login: login,
    register: register,
    restoreSession: restoreSession,
    logout: logout,
    uploadImage: uploadImage,
    clearSession: clearSession
  };
}(window));
