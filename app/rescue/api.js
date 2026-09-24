(function (global) {
  "use strict";

  var API_BASE = "/help-cat-api";
  var TOKEN_KEY = "help_cat_token";
  var USER_KEY = "help_cat_user";

  function token() {
    try { return localStorage.getItem("help_cat_token") || sessionStorage.getItem("help_cat_token") || ""; }
    catch (error) { return sessionStorage.getItem("help_cat_token") || ""; }
  }

  function user() {
    try {
      try { return JSON.parse(localStorage.getItem(USER_KEY) || sessionStorage.getItem(USER_KEY) || "null"); }
      catch (error) { return null; }
    } catch (error) {
      return null;
    }
  }

  // 勾了"记住这台设备"就写 localStorage（关掉浏览器也还在），
  // 否则写 sessionStorage（关标签页即失效）—— 共用设备时默认是后者。
  function store(remember) {
    try { return remember ? localStorage : sessionStorage; } catch (error) { return sessionStorage; }
  }

  function setToken(value, remember) {
    clearStore();
    store(remember).setItem(TOKEN_KEY, value);
  }

  function setUser(value, remember) {
    store(remember).setItem(USER_KEY, JSON.stringify(value));
  }

  function clearStore() {
    try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); } catch (error) {}
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
  }

  function saveSession(payload) {
    if (payload && payload.access_token) {
      setToken(payload.access_token, payload.remember);
    }
    if (payload && payload.user) {
      setUser(payload.user, payload.remember);
    }
    return payload && payload.user ? payload.user : null;
  }

  function clearSession() {
    clearStore();
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

  function login(username, password, remember) {
    return request("/api/v1/auth/login", {
      method: "POST",
      body: { username: username, password: password, remember: !!remember }
    }).then(saveSession);
  }

  function register(username, password) {
    return request("/api/v1/auth/register", {
      method: "POST",
      body: { username: username, password: password }
    }).then(saveSession);
  }

  function restoreSession() {
    // 刻意**不**判断"本地有没有令牌"：会话也可能来自服务端下发的 HttpOnly Cookie
    // （微信内置浏览器会清 JS 存储，免登录就是靠它活下来的）。有没有会话由服务端说了算，
    // 这里是"问一句"，不是"自己下结论" —— 之前就是在这里提前 return 导致 Cookie 形同虚设。
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

  // 上传前先在浏览器里缩到长边 1600 并转成 JPEG：手机原图动辄 5–15MB，直接传又慢、
  // 又可能撞上 nginx/后端的体积上限。压不动（HEIC、老浏览器、canvas 出错）就退回原图，
  // 由后端按内容判断——后端也会自己缩放，所以这条只是为了更快更稳。
  var COMPRESS_MAX_SIDE = 1600;
  var COMPRESS_QUALITY = 0.86;

  function compressImage(file) {
    var canUseCanvas = typeof document !== "undefined" && document.createElement &&
      typeof window !== "undefined" && window.URL && window.URL.createObjectURL && typeof Image === "function";
    if (!file || !canUseCanvas) return Promise.resolve(file);
    return new Promise(function (resolve) {
      var url = window.URL.createObjectURL(file);
      var image = new Image();
      var finish = function (result) {
        try { window.URL.revokeObjectURL(url); } catch (error) { /* 忽略 */ }
        resolve(result && result.size && result.size < file.size ? result : file);
      };
      image.onerror = function () { finish(file); };
      image.onload = function () {
        try {
          var width = image.naturalWidth || image.width;
          var height = image.naturalHeight || image.height;
          if (!width || !height) { finish(file); return; }
          var scale = Math.min(1, COMPRESS_MAX_SIDE / Math.max(width, height));
          var canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(width * scale));
          canvas.height = Math.max(1, Math.round(height * scale));
          // 现代浏览器画图时已经套用 EXIF 方向，所以这里不会把竖拍照片转歪。
          canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
          if (typeof canvas.toBlob !== "function") { finish(file); return; }
          canvas.toBlob(function (blob) { finish(blob); }, "image/jpeg", COMPRESS_QUALITY);
        } catch (error) {
          finish(file);
        }
      };
      image.src = url;
    });
  }

  function uploadImage(file) {
    return compressImage(file).then(function (prepared) {
      var form = new FormData();
      form.append("file", prepared, prepared.name || "photo.jpg");
      return request("/api/v1/media/images", { method: "POST", form: form });
    });
  }

  global.HelpCatApi = {
    API_BASE: API_BASE,
    compressImage: compressImage,
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
