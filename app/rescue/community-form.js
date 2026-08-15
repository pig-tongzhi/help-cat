(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.HelpCatCommunityForm = api;
}(typeof window !== "undefined" ? window : null, function () {
  "use strict";

  function clean(value) {
    return String(value == null ? "" : value).trim();
  }

  function required(value, code) {
    var result = clean(value);
    if (!result) throw new Error(code);
    return result;
  }

  function buildCatCommunityPayload(mode, values) {
    values = values || {};
    if (mode === "existing") {
      return { community_id: required(values.communityId, "community_id_required") };
    }
    if (mode === "new") {
      return {
        community_candidate: {
          name: required(values.name, "community_name_required"),
          street: required(values.street, "community_street_required"),
          note: clean(values.note)
        }
      };
    }
    throw new Error("community_mode_invalid");
  }

  function buildCommunityEditPayload(values) {
    values = values || {};
    var version = Number(values.version);
    if (!Number.isInteger(version) || version < 1) throw new Error("community_version_invalid");
    return {
      name: required(values.name, "community_name_required"),
      street: required(values.street, "community_street_required"),
      note: clean(values.note),
      version: version
    };
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

  function statusMeta(status) {
    return {
      PENDING_REVIEW: { label: "待审核", tone: "pending" },
      NEEDS_CHANGES: { label: "待补充", tone: "attention" },
      ACTIVE: { label: "已开放", tone: "approved" },
      MERGED: { label: "已合并", tone: "merged" },
      REJECTED: { label: "未通过", tone: "rejected" },
      HIDDEN: { label: "未开放", tone: "rejected" },
      ARCHIVED: { label: "已归档", tone: "muted" }
    }[status] || { label: status || "待审核", tone: "pending" };
  }

  function buildSubmissionQuery(append, cursors, limit) {
    cursors = cursors || {};
    var params = ["limit=" + (Number(limit) || 24)];
    if (append) {
      params.push(cursors.cats ? "cat_cursor=" + encodeURIComponent(cursors.cats) : "cat_done=true");
      params.push(cursors.communities ? "community_cursor=" + encodeURIComponent(cursors.communities) : "community_done=true");
    }
    return params.join("&");
  }

  return {
    buildCatCommunityPayload: buildCatCommunityPayload,
    buildCommunityEditPayload: buildCommunityEditPayload,
    appendUnique: appendUnique,
    statusMeta: statusMeta,
    buildSubmissionQuery: buildSubmissionQuery
  };
}));
