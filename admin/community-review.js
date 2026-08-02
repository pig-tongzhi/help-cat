(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.HelpCatCommunityReview = api;
}(typeof window !== "undefined" ? window : null, function () {
  "use strict";

  function clean(value) { return String(value == null ? "" : value).trim(); }
  function versionOf(value) {
    var version = Number(value);
    if (!Number.isInteger(version) || version < 1) throw new Error("community_version_invalid");
    return version;
  }

  function buildActionRequest(action, communityId, values) {
    values = values || {};
    var id = encodeURIComponent(clean(communityId));
    var version = versionOf(values.version);
    if (["approve", "request_changes", "reject"].indexOf(action) >= 0) {
      var note = clean(values.note);
      if (["request_changes", "reject"].indexOf(action) >= 0 && !note) throw new Error("review_note_required");
      return {
        path: "/api/v1/communities/" + id + "/review",
        options: { method: "POST", body: { action: action, note: note, version: version } }
      };
    }
    if (action === "merge") {
      var target = clean(values.targetCommunityId);
      if (!target) throw new Error("merge_target_required");
      return {
        path: "/api/v1/communities/" + id + "/merge",
        options: { method: "POST", body: { target_community_id: target, version: version } }
      };
    }
    throw new Error("community_action_invalid");
  }

  function appendUnique(current, incoming) {
    var positions = Object.create(null);
    var result = [];
    (current || []).concat(incoming || []).forEach(function (item) {
      if (!item || !item.id) return;
      if (positions[item.id] === undefined) {
        positions[item.id] = result.length;
        result.push(item);
      } else {
        result[positions[item.id]] = item;
      }
    });
    return result;
  }

  return { buildActionRequest: buildActionRequest, appendUnique: appendUnique };
}));
