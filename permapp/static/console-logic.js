/* Pure helpers for the demo console. No DOM, no network: unit-tested with node --test. */
(function (root) {
  "use strict";

  var STATE_LABEL = { none: "Không có quyền", see: "Chỉ nhìn thấy", use: "Dùng được" };
  var ROLE_LABEL = { learner: "Học viên", instructor: "Giảng viên" };

  function roleLabel(role) {
    return ROLE_LABEL[role] || role || "";
  }

  // alwaysVisible: miniapps like the mock LMS are seen by everyone without system access.
  function cellState(user, miniappId, alwaysVisible) {
    var sees = !!alwaysVisible || (user.system_access || []).indexOf(miniappId) !== -1;
    var member = (user.memberships || []).indexOf(miniappId) !== -1;
    if (sees && member) return "use";
    return sees ? "see" : "none";
  }

  // The member's role in a miniapp with roles, or "" (not a member, or the miniapp has no roles).
  function memberRole(user, miniappId) {
    var found = (user.member_roles || []).filter(function (r) { return r.miniapp_id === miniappId; })[0];
    return found ? found.role : "";
  }

  function cellLabel(state, role) {
    return STATE_LABEL[state] + (state === "use" && role ? " · " + roleLabel(role) : "");
  }

  function userSnapshot(miniapps) {
    var snap = {};
    miniapps.forEach(function (m) {
      snap[m.id] = (m.can_use ? "use" : "see") + (m.role ? ":" + m.role : "");
    });
    return snap;
  }

  function diffSnapshots(prev, next) {
    if (!prev) return [];
    var changed = [];
    Object.keys(next).forEach(function (k) {
      if (prev[k] !== next[k]) changed.push(k);
    });
    Object.keys(prev).forEach(function (k) {
      if (!(k in next)) changed.push(k);
    });
    return changed;
  }

  function shouldApplyPoll(pollSeq, lastMutationStartSeq) {
    return pollSeq > lastMutationStartSeq;
  }

  // A load result is applied only if it is the most recently started load, it started after the
  // last click began, and no click is still running (that click's own refetch will repaint).
  function shouldApplyLoad(seq, latestLoadSeq, lastMutationStartSeq, inFlight) {
    return seq === latestLoadSeq && seq > lastMutationStartSeq && inFlight === 0;
  }

  var ROLES = ["admin", "user1", "user2", "user3"];

  // ?as=<role> in the URL wins, then the remembered role, then the admin view.
  function pickRole(search, stored) {
    var m = /[?&]as=([^&]*)/.exec(search || "");
    var fromUrl = m ? decodeURIComponent(m[1]) : null;
    if (ROLES.indexOf(fromUrl) !== -1) return fromUrl;
    if (ROLES.indexOf(stored) !== -1) return stored;
    return "admin";
  }

  // Server errors in the page's own words; ctx carries display names ({user, app}).
  function errorText(data, ctx) {
    if (data && data.code === "SYSTEM_ACCESS_REQUIRED" && ctx && ctx.user && ctx.app) {
      return ctx.user + " chưa có quyền hệ thống với " + ctx.app + ". Bật Quyền hệ thống trước, rồi mới thêm làm thành viên.";
    }
    if (data && data.code === "NOT_ELIGIBLE") {
      return "Không đủ điều kiện: " + (data.detail || "người dùng không được cấp quyền này") + ".";
    }
    return (data && data.detail) || "Có lỗi xảy ra";
  }

  // "Phòng Kinh doanh · Nhân viên kinh doanh"; blank parts are skipped.
  function orgLine(user) {
    return [user.department, user.title].filter(function (x) { return x; }).join(" · ");
  }

  function isResigned(user) {
    return String(user.status || "").toUpperCase() === "RESIGNED";
  }

  function safeStore(storage) {
    var memory = {};
    function attempt(fn, fallback) {
      if (!storage) return fallback();
      try {
        return fn();
      } catch (e) {
        return fallback();
      }
    }
    return {
      get: function (k) {
        return attempt(
          function () { var v = storage.getItem(k); return v === null || v === undefined ? (k in memory ? memory[k] : null) : v; },
          function () { return k in memory ? memory[k] : null; }
        );
      },
      set: function (k, v) {
        memory[k] = String(v);
        attempt(function () { storage.setItem(k, String(v)); }, function () {});
      },
      remove: function (k) {
        delete memory[k];
        attempt(function () { storage.removeItem(k); }, function () {});
      },
    };
  }

  // ---------- operator console ----------

  var SECTIONS = ["permissions", "reviews"];

  // &section=<name> in the URL, else the permissions screen.
  function pickSection(search) {
    var m = /[?&]section=([^&]*)/.exec(search || "");
    var s = m ? decodeURIComponent(m[1]) : null;
    return SECTIONS.indexOf(s) !== -1 ? s : "permissions";
  }

  var LEVEL_LABEL = { none: "Chưa có quyền", see: "Xem", use: "Sử dụng", learner: "Học viên", instructor: "Giảng viên" };

  function levelLabel(level) {
    return LEVEL_LABEL[level] || level || "";
  }

  // none | see | use | <member role>: same meaning as the server's level_of.
  function levelOf(user, app) {
    if ((user.memberships || []).indexOf(app.id) !== -1) return memberRole(user, app.id) || "use";
    if (app.always_visible || (user.system_access || []).indexOf(app.id) !== -1) return "see";
    return "none";
  }

  // Dropdown groups: one per miniapp. Levels the user already has (or Xem under Sử dụng) are disabled.
  function grantOptions(user, miniapps) {
    return miniapps.map(function (app) {
      var current = levelOf(user, app);
      var levels = app.roles && app.roles.length ? app.roles : ["see", "use"];
      return {
        miniapp_id: app.id,
        name: app.name,
        options: levels.map(function (level) {
          var has = level === current || (level === "see" && current === "use");
          return { level: level, label: levelLabel(level), disabled: has, note: has ? "đang có" : "" };
        }),
      };
    });
  }

  // picks = {miniapp_id: level}; one level per miniapp, picking the same level again unpicks it.
  function togglePick(picks, miniappId, level) {
    var next = {};
    Object.keys(picks).forEach(function (k) { next[k] = picks[k]; });
    if (next[miniappId] === level) delete next[miniappId];
    else next[miniappId] = level;
    return next;
  }

  function pickList(picks, miniapps) {
    return miniapps.filter(function (m) { return picks[m.id]; })
      .map(function (m) { return { miniapp_id: m.id, level: picks[m.id] }; });
  }

  // Which log rows are new since the last look. First look and a log that went backwards (reset) only
  // set the baseline, so nothing lights up by accident.
  function newLogIds(entries, lastSeenId) {
    var max = entries.reduce(function (m, e) { return Math.max(m, e.id); }, 0);
    if (lastSeenId === null || lastSeenId === undefined || max < lastSeenId) return { ids: [], lastSeenId: max };
    return {
      ids: entries.filter(function (e) { return e.id > lastSeenId; }).map(function (e) { return e.id; }),
      lastSeenId: max,
    };
  }

  function actorLabel(actor) {
    return actor === "console" ? "Thao tác tay" : "Agent";
  }

  function permLogText(entry) {
    return entry.detail || [entry.action, entry.username, entry.miniapp_id].filter(Boolean).join(" ");
  }

  // HQCV results pasted from a spreadsheet: "email, điểm, xếp loại", comma or tab, one per line.
  function parseResultRows(text) {
    var rows = [];
    var errors = [];
    String(text || "").split(/\r?\n/).forEach(function (line, i) {
      if (!line.trim()) return;
      var parts = line.split(/\t|,/).map(function (p) { return p.trim(); });
      var n = i + 1;
      if (parts.length < 3 || !parts[0] || !parts[1] || !parts[2]) {
        errors.push("dòng " + n + ": cần đủ email, điểm, xếp loại");
      } else if (!/^\d+$/.test(parts[1])) {
        errors.push("dòng " + n + ": điểm phải là số nguyên");
      } else {
        rows.push({ email: parts[0], score: parseInt(parts[1], 10), grade: parts[2].toUpperCase() });
      }
    });
    return { rows: rows, errors: errors };
  }

  var api = {
    STATE_LABEL: STATE_LABEL,
    ROLE_LABEL: ROLE_LABEL,
    roleLabel: roleLabel,
    cellState: cellState,
    memberRole: memberRole,
    cellLabel: cellLabel,
    pickSection: pickSection,
    LEVEL_LABEL: LEVEL_LABEL,
    levelLabel: levelLabel,
    levelOf: levelOf,
    grantOptions: grantOptions,
    togglePick: togglePick,
    pickList: pickList,
    newLogIds: newLogIds,
    actorLabel: actorLabel,
    permLogText: permLogText,
    parseResultRows: parseResultRows,
    userSnapshot: userSnapshot,
    diffSnapshots: diffSnapshots,
    shouldApplyPoll: shouldApplyPoll,
    shouldApplyLoad: shouldApplyLoad,
    pickRole: pickRole,
    errorText: errorText,
    orgLine: orgLine,
    isResigned: isResigned,
    safeStore: safeStore,
  };
  root.ConsoleLogic = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
