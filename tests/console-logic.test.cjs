const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../permapp/static/console-logic.js");

const MINIAPPS = [{ id: "expense" }, { id: "inventory" }, { id: "leave" }];
const USERS = [
  { username: "admin", role: "admin", system_access: [], memberships: [] },
  { username: "user1", role: "user", system_access: ["leave"], memberships: ["leave"] },
  { username: "user2", role: "user", system_access: ["inventory"], memberships: [] },
];

test("cellState: system + membership is use", () => {
  assert.equal(L.cellState(USERS[1], "leave"), "use");
});

test("cellState: system only is see", () => {
  assert.equal(L.cellState(USERS[2], "inventory"), "see");
});

test("cellState: nothing is none", () => {
  assert.equal(L.cellState(USERS[2], "leave"), "none");
});

test("adminSnapshot lists only role=user accounts", () => {
  const snap = L.adminSnapshot(USERS, MINIAPPS);
  assert.equal(Object.keys(snap).length, 6);
  assert.ok(!Object.keys(snap).some((k) => k.startsWith("admin|")));
  assert.equal(snap["user1|leave"], "use");
  assert.equal(snap["user2|inventory"], "see");
  assert.equal(snap["user2|leave"], "none");
});

test("userSnapshot maps can_use to use/see", () => {
  assert.deepEqual(
    L.userSnapshot([{ id: "leave", can_use: true }, { id: "expense", can_use: false }]),
    { leave: "use", expense: "see" },
  );
});

test("diffSnapshots: no previous snapshot means no highlight", () => {
  assert.deepEqual(L.diffSnapshots(null, { a: "x" }), []);
});

test("diffSnapshots: added, removed and changed keys", () => {
  assert.deepEqual(L.diffSnapshots({ a: "x", b: "y" }, { a: "z", c: "y" }).sort(), ["a", "b", "c"]);
});

test("diffSnapshots: identical snapshots have no diff", () => {
  assert.deepEqual(L.diffSnapshots({ a: "x" }, { a: "x" }), []);
});

test("shouldApplyPoll: poll started after the last mutation applies", () => {
  assert.equal(L.shouldApplyPoll(5, 4), true);
});

test("shouldApplyPoll: poll started before a later mutation is discarded", () => {
  assert.equal(L.shouldApplyPoll(5, 6), false);
  assert.equal(L.shouldApplyPoll(5, 5), false);
});

test("safeStore falls back to memory when storage throws", () => {
  const broken = {
    getItem() { throw new Error("denied"); },
    setItem() { throw new Error("denied"); },
    removeItem() { throw new Error("denied"); },
  };
  const s = L.safeStore(broken);
  s.set("k", "v");
  assert.equal(s.get("k"), "v");
  s.remove("k");
  assert.equal(s.get("k"), null);
});

test("safeStore works with no storage at all", () => {
  const s = L.safeStore(null);
  s.set("k", "v");
  assert.equal(s.get("k"), "v");
});

test("safeStore uses real storage when it works", () => {
  const data = {};
  const ok = {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
    removeItem: (k) => { delete data[k]; },
  };
  L.safeStore(ok).set("k", "v");
  assert.equal(data.k, "v");
});

test("STATE_LABEL has the exact Vietnamese labels", () => {
  assert.deepEqual(L.STATE_LABEL, { none: "Không có quyền", see: "Chỉ nhìn thấy", use: "Dùng được" });
});

test("shouldApplyLoad: the latest load applies when nothing is in flight", () => {
  assert.equal(L.shouldApplyLoad(7, 7, 6, 0), true);
});

test("shouldApplyLoad: an older load is discarded when a newer one started", () => {
  assert.equal(L.shouldApplyLoad(7, 8, 6, 0), false);
});

test("shouldApplyLoad: a refetch landing while another click is in flight is discarded", () => {
  // click A (seq 5), click B (seq 6), A's refetch (seq 7) returns while B is still running
  assert.equal(L.shouldApplyLoad(7, 7, 6, 1), false);
});

test("shouldApplyLoad: a load started before the last click is discarded", () => {
  assert.equal(L.shouldApplyLoad(5, 5, 6, 0), false);
});

test("pickRole: ?as= in the URL wins", () => {
  assert.equal(L.pickRole("?as=user2", "user1"), "user2");
});

test("pickRole: falls back to the stored role, then admin", () => {
  assert.equal(L.pickRole("", "user1"), "user1");
  assert.equal(L.pickRole("?as=nobody", null), "admin");
  assert.equal(L.pickRole("", "garbage"), "admin");
});

test("errorText: SYSTEM_ACCESS_REQUIRED uses display names, in Vietnamese only", () => {
  assert.equal(
    L.errorText({ code: "SYSTEM_ACCESS_REQUIRED", detail: "'user1' chưa ... (system access) trước." }, { user: "Người dùng 1", app: "Nghỉ phép" }),
    "Người dùng 1 chưa có quyền hệ thống với Nghỉ phép. Bật Quyền hệ thống trước, rồi mới thêm làm thành viên.",
  );
});

test("errorText: other errors keep the server detail", () => {
  assert.equal(L.errorText({ code: "INTERNAL_ERROR", detail: "Lỗi máy chủ: Boom" }, {}), "Lỗi máy chủ: Boom");
});

test("cellState: an always-visible miniapp is seen without system access", () => {
  assert.equal(L.cellState(USERS[2], "lms", true), "see");
  assert.equal(L.cellState({ system_access: [], memberships: ["lms"] }, "lms", true), "use");
});

test("memberRole and cellLabel show the LMS role in Vietnamese", () => {
  const u = { member_roles: [{ miniapp_id: "lms", role: "instructor" }] };
  assert.equal(L.memberRole(u, "lms"), "instructor");
  assert.equal(L.memberRole(u, "leave"), "");
  assert.equal(L.cellLabel("use", "instructor"), "Dùng được · Giảng viên");
  assert.equal(L.cellLabel("see", ""), "Chỉ nhìn thấy");
});

test("adminSnapshot changes when only the LMS role changes", () => {
  const apps = [{ id: "lms", always_visible: true }];
  const before = L.adminSnapshot([{ username: "u", role: "user", memberships: ["lms"], member_roles: [{ miniapp_id: "lms", role: "learner" }] }], apps);
  const after = L.adminSnapshot([{ username: "u", role: "user", memberships: ["lms"], member_roles: [{ miniapp_id: "lms", role: "instructor" }] }], apps);
  assert.deepEqual(L.diffSnapshots(before, after), ["u|lms"]);
});

test("errorText: NOT_ELIGIBLE shows the server reason", () => {
  assert.equal(
    L.errorText({ code: "NOT_ELIGIBLE", detail: "Nhân viên đã nghỉ việc (RESIGNED), không được cấp quyền mới" }, { user: "Người dùng 3", app: "Nghỉ phép" }),
    "Không đủ điều kiện: Nhân viên đã nghỉ việc (RESIGNED), không được cấp quyền mới.",
  );
});

test("orgLine joins department and title, skipping blanks", () => {
  assert.equal(L.orgLine({ department: "Phòng Kinh doanh", title: "Nhân viên kinh doanh" }), "Phòng Kinh doanh · Nhân viên kinh doanh");
  assert.equal(L.orgLine({ department: "", title: "Quản trị hệ thống" }), "Quản trị hệ thống");
  assert.equal(L.orgLine({}), "");
});

test("isResigned reads status case-insensitively", () => {
  assert.equal(L.isResigned({ status: "RESIGNED" }), true);
  assert.equal(L.isResigned({ status: "resigned" }), true);
  assert.equal(L.isResigned({ status: "ACTIVE" }), false);
  assert.equal(L.isResigned({}), false);
});

test("pickRole accepts user3", () => {
  assert.equal(L.pickRole("?as=user3", null), "user3");
});
