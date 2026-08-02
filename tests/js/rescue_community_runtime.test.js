const test = require("node:test");
const assert = require("node:assert/strict");

const form = require("../../app/rescue/community-form.js");

test("cat community payload supports approved selection and inline candidate", () => {
  assert.deepEqual(
    form.buildCatCommunityPayload("existing", { communityId: "c1" }),
    { community_id: "c1" }
  );
  assert.deepEqual(
    form.buildCatCommunityPayload("new", { name: " 新湖家园 ", street: " 银湖街道 ", note: " 北门 " }),
    { community_candidate: { name: "新湖家园", street: "银湖街道", note: "北门" } }
  );
});

test("invalid community mode values return a field-specific error", () => {
  assert.throws(
    () => form.buildCatCommunityPayload("existing", { communityId: "" }),
    /community_id_required/
  );
  assert.throws(
    () => form.buildCatCommunityPayload("new", { name: "", street: "银湖街道" }),
    /community_name_required/
  );
});

test("community correction includes optimistic version", () => {
  assert.deepEqual(
    form.buildCommunityEditPayload({ name: "新湖家园", street: "银湖街道", note: "补充北门", version: "3" }),
    { name: "新湖家园", street: "银湖街道", note: "补充北门", version: 3 }
  );
});

test("appendUnique preserves order while replacing duplicate ids", () => {
  assert.deepEqual(
    form.appendUnique([{ id: "1", name: "旧" }], [{ id: "1", name: "新" }, { id: "2", name: "二" }]),
    [{ id: "1", name: "新" }, { id: "2", name: "二" }]
  );
});

test("candidate status metadata covers the complete correction lifecycle", () => {
  assert.equal(form.statusMeta("PENDING_REVIEW").label, "待审核");
  assert.equal(form.statusMeta("NEEDS_CHANGES").label, "待补充");
  assert.equal(form.statusMeta("MERGED").label, "已合并");
  assert.equal(form.statusMeta("REJECTED").label, "未通过");
  assert.equal(form.statusMeta("ACTIVE").label, "已开放");
});
