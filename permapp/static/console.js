/* Demo console: DOM + network. Pure rules live in console-logic.js (window.ConsoleLogic). */
(function () {
  "use strict";

  var L = window.ConsoleLogic;
  var POLL_MS = 3000;
  var USER_KEYS = { user1: "user1-key-123", user2: "user2-key-123" };
  var ROLES = ["admin", "user1", "user2"];
  var K_ROLE = "permconsole.role";
  var K_ADMIN = "permconsole.adminKey";

  var storage = null;
  try { storage = window.localStorage; } catch (e) { storage = null; }
  var store = L.safeStore(storage);

  var app = document.getElementById("app");
  var syncEl = document.getElementById("sync");

  var state = {
    role: ROLES.indexOf(store.get(K_ROLE)) !== -1 ? store.get(K_ROLE) : "user1",
    seq: 0,
    lastMutationStartSeq: 0,
    inFlight: 0,
    loading: false,
    data: null,
    dataSig: null,
    snapshot: null,
    notice: null,
    noticeTimer: null,
    view: null,
  };

  // ---------- small DOM helpers ----------

  function h(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "text") el.textContent = v;
        else if (k === "class") el.className = v;
        else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v === true ? "" : v);
      });
    }
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return el;
  }

  var ICONS = {
    use: "M4 8.5l2.5 2.5L12 5.5",
    see: "M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8s-2.4 4.5-6.5 4.5S1.5 8 1.5 8z M8 6a2 2 0 1 0 0 4a2 2 0 1 0 0-4z",
    none: "M4 4l8 8 M12 4l-8 8",
    error: "M8 2.5l6 11H2z M8 6.5v3 M8 11.5v.5",
    success: "M4 8.5l2.5 2.5L12 5.5",
  };

  function icon(name) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", "16");
    svg.setAttribute("height", "16");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("aria-hidden", "true");
    var path = document.createElementNS(ns, "path");
    path.setAttribute("d", ICONS[name]);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "1.6");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    svg.appendChild(path);
    return svg;
  }

  // ---------- network ----------

  function api(path, opts) {
    opts = opts || {};
    var headers = { "X-API-Key": opts.key || "" };
    var init = { method: opts.method || "GET", headers: headers, cache: "no-store" };
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    return fetch(path, init).then(
      function (r) {
        return r.json().then(
          function (data) { return { ok: r.ok, status: r.status, data: data }; },
          function () { return { ok: r.ok, status: r.status, data: { detail: "Máy chủ trả về dữ liệu không đọc được (HTTP " + r.status + ")" } }; }
        );
      },
      function () { return { ok: false, status: 0, data: { detail: "Không kết nối được máy chủ" } }; }
    );
  }

  function nextSeq() { state.seq += 1; return state.seq; }
  function beginMutation() { state.lastMutationStartSeq = nextSeq(); state.inFlight += 1; }
  function endMutation() { state.inFlight = Math.max(0, state.inFlight - 1); }

  function currentKey() {
    return state.role === "admin" ? store.get(K_ADMIN) : USER_KEYS[state.role];
  }

  // ---------- notices and sync line ----------

  function notify(kind, text) {
    state.notice = { kind: kind, text: text };
    clearTimeout(state.noticeTimer);
    state.noticeTimer = setTimeout(function () { state.notice = null; paintNotice(); }, 6000);
    paintNotice();
  }

  function paintNotice() {
    var el = document.getElementById("notice");
    if (!el) return;
    el.textContent = "";
    el.className = "notice";
    if (!state.notice) return;
    el.className = "notice notice--" + state.notice.kind;
    el.appendChild(icon(state.notice.kind === "error" ? "error" : "success"));
    el.appendChild(h("span", { text: state.notice.text }));
  }

  function setSync(ok) {
    if (ok) {
      var t = new Date();
      var pad = function (n) { return (n < 10 ? "0" : "") + n; };
      syncEl.textContent = "Tự cập nhật mỗi 3 giây, lần cuối " + pad(t.getHours()) + ":" + pad(t.getMinutes()) + ":" + pad(t.getSeconds());
      syncEl.classList.remove("is-failing");
    } else {
      syncEl.textContent = "Không cập nhật được, đang thử lại";
      syncEl.classList.add("is-failing");
    }
  }

  // ---------- rendering ----------

  function keepFocus(renderFn) {
    var active = document.activeElement;
    var focusId = active && active.getAttribute ? active.getAttribute("data-focus") : null;
    renderFn();
    if (focusId) {
      var again = app.querySelector('[data-focus="' + focusId + '"]');
      if (again) again.focus();
    }
  }

  function paintRoles() {
    document.querySelectorAll(".role").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-role") === state.role ? "true" : "false");
    });
  }

  function mount(nodes) {
    app.textContent = "";
    nodes.forEach(function (n) { if (n) app.appendChild(n); });
    paintNotice();
  }

  function noticeEl() {
    return h("div", { id: "notice", class: "notice", role: "status", "aria-live": "polite" });
  }

  function renderLoading() {
    if (state.role === "admin") {
      mount([
        h("div", { class: "head" }, [h("div", null, [h("h1", { text: "Phân quyền miniapp" })])]),
        h("div", { class: "skeleton", "aria-busy": "true", "aria-label": "Đang tải" }, [h("i"), h("i"), h("i")]),
      ]);
    } else {
      mount([
        h("div", { class: "head" }, [h("div", null, [h("h1", { text: "Miniapp của bạn" })])]),
        h("div", { class: "shelf", "aria-busy": "true", "aria-label": "Đang tải" }, [h("div", { class: "skeleton-card" }), h("div", { class: "skeleton-card" })]),
      ]);
    }
  }

  function renderError(detail) {
    mount([
      noticeEl(),
      h("div", { class: "state-block", role: "alert" }, [
        h("h2", { text: "Không tải được dữ liệu" }),
        h("p", { text: detail + ". Kiểm tra kết nối rồi thử lại." }),
        h("button", { type: "button", class: "key", text: "Thử lại", "data-focus": "retry", onclick: function () { load("initial"); } }),
      ]),
    ]);
  }

  function renderUser(highlight) {
    var me = state.data.me;
    var apps = state.data.miniapps;
    var head = h("div", { class: "head" }, [
      h("div", null, [
        h("h1", { text: "Xin chào, " + me.display_name }),
        h("p", { text: "Các miniapp tài khoản " + me.username + " đang nhìn thấy. Miniapp chưa được cấp quyền hệ thống sẽ không hiện ở đây." }),
      ]),
    ]);
    if (!apps.length) {
      mount([head, noticeEl(), h("div", { class: "state-block" }, [
        h("h2", { text: "Bạn chưa nhìn thấy miniapp nào" }),
        h("p", { text: "Admin cần cấp quyền hệ thống cho bạn trước. Khi được cấp, miniapp sẽ tự hiện ở đây." }),
      ])]);
      return;
    }
    var cards = apps.map(function (a) {
      var foot;
      var result = h("p", { class: "app-card__result", "aria-live": "polite", "data-result": a.id });
      if (a.can_use) {
        foot = h("div", { class: "app-card__foot" }, [
          h("p", { class: "state state--use" }, [icon("use"), "Dùng được"]),
          h("button", { type: "button", class: "key", "data-focus": "use-" + a.id, text: "Mở miniapp", onclick: function (ev) { useMiniapp(a, ev.currentTarget, result); } }),
          result,
        ]);
      } else {
        foot = h("div", { class: "app-card__foot" }, [
          h("p", { class: "state state--see" }, [icon("see"), "Chỉ nhìn thấy"]),
          h("p", { class: "app-card__wait", text: "Chờ admin thêm bạn vào miniapp này để dùng được." }),
        ]);
      }
      return h("article", { class: "app-card" + (highlight.indexOf(a.id) !== -1 ? " is-changed" : ""), "data-key": a.id }, [
        h("h2", { text: a.name }),
        h("p", { text: a.description }),
        foot,
      ]);
    });
    mount([head, noticeEl(), h("div", { class: "shelf" }, cards)]);
  }

  function render(highlight) {
    paintRoles();
    if (state.view === "user") renderUser(highlight || []);
    else if (state.view === "admin") renderAdmin(highlight || []);
    else if (state.view === "key") renderKeyForm();
    if (highlight && highlight.length) {
      setTimeout(function () {
        app.querySelectorAll(".is-changed").forEach(function (el) { el.classList.remove("is-changed"); });
      }, 2400);
    }
  }

  // ---------- actions ----------

  function useMiniapp(a, btn, result) {
    beginMutation();
    btn.setAttribute("aria-busy", "true");
    btn.disabled = true;
    api("/miniapps/" + encodeURIComponent(a.id) + "/use", { method: "POST", key: currentKey() }).then(function (r) {
      endMutation();
      btn.removeAttribute("aria-busy");
      btn.disabled = false;
      result.className = "app-card__result " + (r.ok ? "is-ok" : "is-err");
      result.textContent = r.ok ? r.data.message : r.data.detail;
      load("after");
    });
  }

  // ---------- loading data ----------

  function fetchUser(key) {
    return Promise.all([api("/me", { key: key }), api("/me/miniapps", { key: key })]).then(function (rs) {
      var bad = rs.filter(function (r) { return !r.ok; })[0];
      if (bad) return { ok: false, status: bad.status, detail: bad.data.detail };
      return { ok: true, data: { me: rs[0].data, miniapps: rs[1].data.miniapps }, snapshot: L.userSnapshot(rs[1].data.miniapps) };
    });
  }

  function load(kind) {
    var role = state.role;
    if (kind !== "poll") state.loading = true;
    if (kind === "initial") renderLoading();
    var key = currentKey();
    if (role === "admin" && !key) {
      state.loading = false;
      state.view = "key";
      state.data = null;
      render();
      return Promise.resolve();
    }
    var seq = nextSeq();
    var req = role === "admin" ? fetchAdmin(key) : fetchUser(key);
    return req.then(function (res) {
      if (role !== state.role) return;
      if (kind === "poll" && !L.shouldApplyPoll(seq, state.lastMutationStartSeq)) return;
      state.loading = false;
      if (!res.ok) {
        if (role === "admin" && (res.status === 401 || res.status === 403)) {
          store.remove(K_ADMIN);
          state.view = "key";
          state.keyError = "Admin key đã lưu không còn đúng. Nhập lại key.";
          render();
          return;
        }
        if (kind === "poll" && state.data) { setSync(false); return; }
        setSync(false);
        state.data = null;
        renderError(res.detail);
        return;
      }
      setSync(true);
      var highlight = kind === "poll" ? L.diffSnapshots(state.snapshot, res.snapshot) : [];
      var sig = JSON.stringify(res.data);
      var viewName = role === "admin" ? "admin" : "user";
      state.snapshot = res.snapshot;
      if (sig === state.dataSig && state.view === viewName) return;
      state.data = res.data;
      state.dataSig = sig;
      state.view = viewName;
      keepFocus(function () { render(highlight); });
    });
  }

  function switchRole(role) {
    if (role === state.role) return;
    state.role = role;
    store.set(K_ROLE, role);
    state.data = null;
    state.dataSig = null;
    state.snapshot = null;
    state.notice = null;
    state.view = null;
    state.keyError = null;
    paintRoles();
    load("initial");
  }

  function poll() {
    if (document.hidden || state.inFlight > 0 || state.loading || state.view === "key") return;
    state.loading = true;
    load("poll").then(function () { state.loading = false; }, function () { state.loading = false; });
  }

  // ---------- admin (filled in by the admin view) ----------

  function fetchAdmin() { return Promise.resolve({ ok: false, status: 0, detail: "Chưa hỗ trợ" }); }
  function renderAdmin() {}
  function renderKeyForm() {}

  // ---------- boot ----------

  document.getElementById("roles").addEventListener("click", function (ev) {
    var b = ev.target.closest(".role");
    if (b) switchRole(b.getAttribute("data-role"));
  });
  paintRoles();
  load("initial");
  setInterval(poll, POLL_MS);
})();
