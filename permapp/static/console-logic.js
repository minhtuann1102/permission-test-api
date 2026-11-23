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
    safeStore: safeStore,
  };
  root.ConsoleLogic = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
