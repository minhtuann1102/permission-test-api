/* Pure helpers for the demo console. No DOM, no network: unit-tested with node --test. */
(function (root) {
  "use strict";

  var STATE_LABEL = { none: "Không có quyền", see: "Chỉ nhìn thấy", use: "Dùng được" };

  function cellState(user, miniappId) {
    var sees = (user.system_access || []).indexOf(miniappId) !== -1;
    var member = (user.memberships || []).indexOf(miniappId) !== -1;
    if (sees && member) return "use";
    return sees ? "see" : "none";
  }

  function adminSnapshot(users, miniapps) {
    var snap = {};
    users.forEach(function (u) {
      if (u.role !== "user") return;
      miniapps.forEach(function (m) {
        snap[u.username + "|" + m.id] = cellState(u, m.id);
      });
    });
    return snap;
  }

  function userSnapshot(miniapps) {
    var snap = {};
    miniapps.forEach(function (m) {
      snap[m.id] = m.can_use ? "use" : "see";
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

  var ROLES = ["admin", "user1", "user2"];

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
    return (data && data.detail) || "Có lỗi xảy ra";
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

  var api = {
    STATE_LABEL: STATE_LABEL,
    cellState: cellState,
    adminSnapshot: adminSnapshot,
    userSnapshot: userSnapshot,
    diffSnapshots: diffSnapshots,
    shouldApplyPoll: shouldApplyPoll,
    shouldApplyLoad: shouldApplyLoad,
    pickRole: pickRole,
    errorText: errorText,
    safeStore: safeStore,
  };
  root.ConsoleLogic = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
