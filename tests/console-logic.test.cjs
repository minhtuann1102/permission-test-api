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

// ---------- operator console ----------

const APPS = [
  { id: "expense", name: "Chi phí", always_visible: false, roles: [] },
  { id: "inventory", name: "Kho", always_visible: false, roles: [] },
  { id: "leave", name: "Nghỉ phép", always_visible: false, roles: [] },
  { id: "lms", name: "LMS", always_visible: true, roles: ["learner", "instructor"] },
];
const U2 = {
  username: "user2", role: "user",
  system_access: ["inventory", "leave"], memberships: ["leave", "lms"],
  member_roles: [{ miniapp_id: "lms", role: "learner" }],
};

test("pickSection: section param wins, default permissions", () => {
  assert.equal(L.pickSection("?as=admin&section=reviews"), "reviews");
  assert.equal(L.pickSection("?as=admin"), "permissions");
  assert.equal(L.pickSection("?section=bogus"), "permissions");
});

test("levelOf: none, see, use, role", () => {
  assert.equal(L.levelOf(U2, APPS[0]), "none");
  assert.equal(L.levelOf(U2, APPS[1]), "see");
  assert.equal(L.levelOf(U2, APPS[2]), "use");
  assert.equal(L.levelOf(U2, APPS[3]), "learner");
  assert.equal(L.levelOf({ username: "x" }, APPS[3]), "see");
  assert.equal(L.levelLabel("instructor"), "Giảng viên");
  assert.equal(L.levelLabel("none"), "Chưa có quyền");
});

test("grantOptions: what the user has is disabled, LMS has no Xem", () => {
  const groups = L.grantOptions(U2, APPS);
  const by = Object.fromEntries(groups.map((g) => [g.miniapp_id, g.options.map((o) => [o.level, o.disabled])]));
  assert.deepEqual(by.expense, [["see", false], ["use", false]]);
  assert.deepEqual(by.inventory, [["see", true], ["use", false]]);
  assert.deepEqual(by.leave, [["see", true], ["use", true]]);
  assert.deepEqual(by.lms, [["learner", true], ["instructor", false]]);
  assert.equal(groups[0].name, "Chi phí");
  assert.equal(groups[1].options[0].note, "đang có");
});

test("togglePick: one level per miniapp", () => {
  let p = L.togglePick({}, "inventory", "see");
  assert.deepEqual(p, { inventory: "see" });
  p = L.togglePick(p, "inventory", "use");
  assert.deepEqual(p, { inventory: "use" });
  p = L.togglePick(p, "inventory", "use");
  assert.deepEqual(p, {});
});

test("pickList follows miniapp order", () => {
  assert.deepEqual(L.pickList({ lms: "instructor", expense: "use" }, APPS),
    [{ miniapp_id: "expense", level: "use" }, { miniapp_id: "lms", level: "instructor" }]);
});

test("newLogIds: first load, new rows, reset, empty", () => {
  assert.deepEqual(L.newLogIds([{ id: 5 }, { id: 4 }], null), { ids: [], lastSeenId: 5 });
  assert.deepEqual(L.newLogIds([{ id: 7 }, { id: 6 }, { id: 5 }], 5), { ids: [7, 6], lastSeenId: 7 });
  assert.deepEqual(L.newLogIds([{ id: 2 }, { id: 1 }], 9), { ids: [], lastSeenId: 2 });
  assert.deepEqual(L.newLogIds([], 9), { ids: [], lastSeenId: 0 });
  assert.deepEqual(L.newLogIds([], null), { ids: [], lastSeenId: 0 });
});

test("actorLabel and permLogText", () => {
  assert.equal(L.actorLabel("console"), "Thao tác tay");
  assert.equal(L.actorLabel("agent"), "Agent");
  assert.equal(L.actorLabel(null), "Agent");
  assert.equal(L.permLogText({ detail: "Cấp quyền Sử dụng Kho cho user2" }), "Cấp quyền Sử dụng Kho cho user2");
});

test("parseResultRows: tab or comma, blank lines skipped, raw line numbers", () => {
  const r = L.parseResultRows("a@x.vn, 90, a\n\nb@x.vn\t75\tB\nc@x.vn, x, C");
  assert.deepEqual(r.rows, [{ email: "a@x.vn", score: 90, grade: "A" }, { email: "b@x.vn", score: 75, grade: "B" }]);
  assert.deepEqual(r.errors, ["dòng 4: điểm phải là số nguyên"]);
  assert.deepEqual(L.parseResultRows("d@x.vn").errors, ["dòng 1: cần đủ email, điểm, xếp loại"]);
  assert.deepEqual(L.parseResultRows("  \n").rows, []);
});
