const test = require("node:test");
const assert = require("node:assert/strict");

const review = require("../../admin/community-review.js");

test("approve and merge actions map to versioned endpoints", () => {
  assert.deepEqual(review.buildActionRequest("approve", "c 1", { version: "2" }), {
    path: "/api/v1/communities/c%201/review",
    options: { method: "POST", body: { action: "approve", note: "", version: 2 } }
  });
  assert.deepEqual(review.buildActionRequest("merge", "c1", { version: 3, targetCommunityId: "target" }), {
    path: "/api/v1/communities/c1/merge",
    options: { method: "POST", body: { target_community_id: "target", version: 3 } }
  });
});

test("request changes and reject require a reason before network", () => {
  assert.throws(() => review.buildActionRequest("request_changes", "c1", { version: 1, note: "" }), /review_note_required/);
  assert.throws(() => review.buildActionRequest("reject", "c1", { version: 1, note: "  " }), /review_note_required/);
  assert.equal(
    review.buildActionRequest("request_changes", "c1", { version: 1, note: " 请补充街道 " }).options.body.note,
    "请补充街道"
  );
});

test("merge requires an active target and every action requires a valid version", () => {
  assert.throws(() => review.buildActionRequest("merge", "c1", { version: 1, targetCommunityId: "" }), /merge_target_required/);
  assert.throws(() => review.buildActionRequest("approve", "c1", { version: 0 }), /community_version_invalid/);
});

test("appendUnique de-duplicates paged admin results", () => {
  assert.deepEqual(review.appendUnique([{ id: "1", status: "old" }], [{ id: "1", status: "new" }, { id: "2" }]), [
    { id: "1", status: "new" }, { id: "2" }
  ]);
});
