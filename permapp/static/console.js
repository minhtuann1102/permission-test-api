/* Operator console shell: accounts, admin sections, polling, live change log, dialogs.
 * Pure rules live in console-logic.js (window.ConsoleLogic). Admin screens are separate modules
 * (perm-screen.js -> window.PermScreen, review-screen.js -> window.ReviewScreen) that render into the
 * work area with the helpers in window.ConsoleShell. */
(function () {
  "use strict";

  var L = window.ConsoleLogic;
  var POLL_MS = 3000;
  var USER_KEYS = { user1: "user1-key-123", user2: "user2-key-123", user3: "user3-key-123" };
  var K_ROLE = "permconsole.role";
  var K_ADMIN = "permconsole.adminKey";
  var SECTION_HEAD = {
    permissions: {
      title: "Phân quyền miniapp",
      lead: "Chọn người dùng, chọn các quyền cần cấp rồi xác nhận. Mọi thay đổi, kể cả do agent làm, hiện ngay ở nhật ký bên phải.",
    },
    reviews: {
      title: "Đánh giá",
      lead: "Hệ thống đánh giá giả lập: phiếu của từng nhân viên và các kỳ đánh giá. Mọi thay đổi, kể cả do agent làm, hiện ngay ở nhật ký bên phải.",
    },
  };

  var storage = null;
  try { storage = window.localStorage; } catch (e) { storage = null; }
  var store = L.safeStore(storage);

  var app = document.getElementById("app");
  var syncEl = document.getElementById("sync");
  var syncLive = document.getElementById("sync-live");
  var sectionsNav = document.getElementById("sections");

  var state = {
    role: L.pickRole(window.location.search, store.get(K_ROLE)),
    section: L.pickSection(window.location.search),
    seq: 0,
    lastMutationStartSeq: 0,
    inFlight: 0,
    polling: false,
    latestLoadSeq: 0,
    data: null,
    dataSig: null,
    logSig: null,
    log: null,
    logSeen: { permissions: null, reviews: null },
    snapshot: null,
    notice: null,
    noticeTimer: null,
    view: null,
    syncOk: null,
    ui: { permissions: {}, reviews: {} },
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
    close: "M4.5 4.5l7 7 M11.5 4.5l-7 7",
    chevron: "M4.5 6.5L8 10l3.5-3.5",
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

  // Every console request says it comes from the console, so the change logs can tell "by hand" from the agent.
  function api(path, opts) {
    opts = opts || {};
    var key = opts.key !== undefined ? opts.key : currentKey();
    var headers = { "X-API-Key": key || "", "X-Client": "console" };
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

  function screen() {
    return state.section === "reviews" ? window.ReviewScreen : window.PermScreen;
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
    if (ok !== state.syncOk) {
      state.syncOk = ok;
      syncLive.textContent = ok ? "Đã cập nhật lại dữ liệu." : "Không cập nhật được dữ liệu, đang thử lại.";
    }
    if (ok) {
      syncEl.textContent = "Tự cập nhật mỗi 3 giây, lần cuối " + clock(new Date());
      syncEl.classList.remove("is-failing");
    } else {
      syncEl.textContent = "Không cập nhật được, đang thử lại";
      syncEl.classList.add("is-failing");
    }
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function clock(t) { return pad(t.getHours()) + ":" + pad(t.getMinutes()) + ":" + pad(t.getSeconds()); }

  // ---------- rendering ----------

  function keepFocus(root, renderFn) {
    var active = document.activeElement;
    var focusId = active && root.contains(active) && active.getAttribute ? active.getAttribute("data-focus") : null;
    renderFn();
    if (focusId) {
      var again = root.querySelector('[data-focus="' + focusId + '"]');
      if (again) again.focus();
    }
  }

  function paintRoles() {
    document.querySelectorAll(".role").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-role") === state.role ? "true" : "false");
    });
    sectionsNav.hidden = state.role !== "admin";
    sectionsNav.querySelectorAll(".section-tab").forEach(function (b) {
      var on = b.getAttribute("data-section") === state.section;
      if (on) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
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
      var head = SECTION_HEAD[state.section];
      mount([
        h("div", { class: "head" }, [h("div", null, [h("h1", { text: head.title })])]),
        h("div", { class: "workspace" }, [
          h("div", { class: "skeleton", "aria-busy": "true", "aria-label": "Đang tải" }, [h("i"), h("i"), h("i")]),
          h("div", { class: "skeleton" }, [h("i"), h("i")]),
        ]),
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
        h("h1", { text: "Miniapp của bạn" }),
        h("p", { text: "Bạn đang xem với tài khoản " + me.display_name + " (" + (me.email || me.username) + ")" + (L.orgLine(me) ? ", " + L.orgLine(me) : "") + ". Miniapp chưa được cấp quyền hệ thống sẽ không hiện ở đây." }),
        L.isResigned(me) ? h("p", null, [h("span", { class: "badge badge--gone", text: "Đã nghỉ việc" }), " Tài khoản này không được cấp quyền mới."]) : null,
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
          h("p", { class: "state state--use" }, [icon("use"), L.cellLabel("use", a.role)]),
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
    clearHighlights(highlight);
  }

  function clearHighlights(highlight) {
    if (!highlight || !highlight.length) return;
    setTimeout(function () {
      document.querySelectorAll(".is-changed").forEach(function (el) { el.classList.remove("is-changed"); });
    }, 2400);
  }

  // ---------- admin layout: head, work area (screen module), change log (shell) ----------

  function adminViewName() { return "admin:" + state.section; }

  function renderAdminFrame() {
    var head = SECTION_HEAD[state.section];
    mount([
      h("div", { class: "head" }, [
        h("div", null, [h("h1", { text: head.title }), h("p", { text: head.lead })]),
        h("div", { class: "head__actions", id: "head-actions" }),
      ]),
      noticeEl(),
      h("div", { class: "workspace" }, [
        h("div", { class: "work", id: "work" }),
        h("aside", { class: "logpanel", id: "logpanel", "aria-labelledby": "log-title" }),
      ]),
    ]);
    paintHeadActions();
  }

  function paintHeadActions() {
    var el = document.getElementById("head-actions");
    if (!el) return;
    el.textContent = "";
    el.appendChild(h("button", { type: "button", class: "key key--quiet", "data-focus": "change-key", text: "Đổi admin key", onclick: changeKey }));
    if (state.confirmReset) {
      el.appendChild(h("button", { type: "button", class: "key key--danger", "data-focus": "reset-confirm", text: "Xác nhận reset", onclick: doReset }));
      el.appendChild(h("button", { type: "button", class: "key key--quiet", "data-focus": "reset-cancel", text: "Huỷ", onclick: cancelReset }));
    } else {
      el.appendChild(h("button", { type: "button", class: "key key--quiet key--danger", "data-focus": "reset", text: "Reset dữ liệu", onclick: askReset }));
    }
  }

  function renderWork() {
    var work = document.getElementById("work");
    if (!work || !state.data) return;
    keepFocus(work, function () {
      work.textContent = "";
      screen().render(work, state.data, shell);
    });
  }

  function logLine(entry) {
    if (state.section === "permissions") {
      return [
        h("p", { class: "log__text", text: L.permLogText(entry) }),
        h("p", { class: "log__delta", text: L.levelLabel(entry.from_level) + " → " + L.levelLabel(entry.to_level) }),
      ];
    }
    return [
      h("p", { class: "log__text" }, [h("b", { text: entry.target }), " · " + entry.detail]),
    ];
  }

  function renderLog(highlightIds) {
    var panel = document.getElementById("logpanel");
    if (!panel || !state.log) return;
    var entries = state.log.entries || [];
    panel.textContent = "";
    panel.appendChild(h("h2", { id: "log-title", class: "logpanel__title", text: "Nhật ký thay đổi" }));
    if (!entries.length) {
      panel.appendChild(h("p", { class: "logpanel__empty", text: "Chưa có thay đổi nào." }));
      return;
    }
    panel.appendChild(h("ol", { class: "log", "aria-live": "polite" }, entries.slice(0, 50).map(function (e) {
      var at = new Date(e.at);
      return h("li", { class: "log__row" + (highlightIds.indexOf(e.id) !== -1 ? " is-changed" : "") }, [
        h("p", { class: "log__meta" }, [
          h("time", { datetime: e.at, text: isNaN(at.getTime()) ? e.at : clock(at) }),
          h("span", { class: "actor actor--" + (e.actor === "console" ? "console" : "agent"), text: L.actorLabel(e.actor) }),
          e.ticket ? h("span", { class: "log__ticket", text: "Ticket " + e.ticket }) : null,
        ]),
      ].concat(logLine(e)));
    })));
    clearHighlights(highlightIds);
  }

  function render(highlight) {
    paintRoles();
    if (state.view === "user") renderUser(highlight || []);
    else if (state.view === "key") renderKeyForm();
  }

  // ---------- user actions ----------

  function useMiniapp(a, btn, result) {
    if (btn.getAttribute("aria-busy") === "true") return;
    beginMutation();
    btn.setAttribute("aria-busy", "true");
    btn.setAttribute("aria-disabled", "true");
    api("/miniapps/" + encodeURIComponent(a.id) + "/use", { method: "POST" }).then(function (r) {
      endMutation();
      btn.removeAttribute("aria-busy");
      btn.removeAttribute("aria-disabled");
      result.className = "app-card__result " + (r.ok ? "is-ok" : "is-err");
      result.textContent = r.ok ? "Bạn đã mở " + a.name + " thành công." : L.errorText(r.data, {});
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

  function invalidateLoads() { state.latestLoadSeq = nextSeq(); }

  function load(kind) {
    var role = state.role;
    var section = state.section;
    if (kind === "initial") renderLoading();
    var key = currentKey();
    if (role === "admin" && !key) {
      invalidateLoads();
      state.view = "key";
      state.data = null;
      render();
      return Promise.resolve();
    }
    var seq = nextSeq();
    state.latestLoadSeq = seq;
    var req = role === "admin" ? screen().fetch(api) : fetchUser(key);
    return req.then(function (res) {
      if (role !== state.role || section !== state.section) return;
      if (!L.shouldApplyLoad(seq, state.latestLoadSeq, state.lastMutationStartSeq, state.inFlight)) return;
      if (!res.ok) {
        if (role === "admin" && (res.status === 401 || (res.status === 403 && res.code !== "NOT_ELIGIBLE"))) {
          store.remove(K_ADMIN);
          state.view = "key";
          state.keyError = "Admin key đã lưu không còn đúng. Nhập lại key.";
          render();
          return;
        }
        setSync(false);
        if (kind !== "initial" && state.data) return;
        state.data = null;
        renderError(res.detail);
        return;
      }
      setSync(true);
      if (role === "admin") applyAdmin(res);
      else applyUser(res, kind);
    });
  }

  function applyUser(res, kind) {
    var highlight = kind === "poll" ? L.diffSnapshots(state.snapshot, res.snapshot) : [];
    var sig = JSON.stringify(res.data);
    state.snapshot = res.snapshot;
    if (sig === state.dataSig && state.view === "user") return;
    state.data = res.data;
    state.dataSig = sig;
    state.view = "user";
    keepFocus(app, function () { render(highlight); });
  }

  // The work area and the log repaint independently: a new log row never wipes what the operator is
  // doing, and open dialogs live outside #app so no repaint touches them.
  function applyAdmin(res) {
    var fresh = state.view !== adminViewName();
    if (fresh) {
      state.view = adminViewName();
      state.dataSig = null;
      state.logSig = null;
      renderAdminFrame();
    }
    var sig = JSON.stringify(res.data);
    if (sig !== state.dataSig) {
      state.data = res.data;
      state.dataSig = sig;
      renderWork();
    }
    var logSig = JSON.stringify(res.log);
    if (logSig !== state.logSig) {
      var seen = L.newLogIds(res.log.entries || [], state.logSeen[state.section]);
      state.logSeen[state.section] = seen.lastSeenId;
      state.log = res.log;
      state.logSig = logSig;
      renderLog(seen.ids);
    }
  }

  function sectionUrl(role, section) {
    return window.location.pathname + "?as=" + role + (role === "admin" ? "&section=" + section : "");
  }

  function writeUrl(push) {
    try {
      var url = sectionUrl(state.role, state.section);
      var st = { as: state.role, section: state.section };
      if (push) window.history.pushState(st, "", url);
      else window.history.replaceState(st, "", url);
    } catch (e) { /* history unavailable: the view still works */ }
  }

  function resetView() {
    state.data = null;
    state.dataSig = null;
    state.log = null;
    state.logSig = null;
    state.snapshot = null;
    state.notice = null;
    state.view = null;
    state.logSeen = { permissions: null, reviews: null };
    invalidateLoads();
    state.keyError = null;
    state.changingKey = false;
    state.confirmReset = false;
    clearTimeout(state.resetTimer);
    closeDialog();
  }

  function switchTo(role, section, fromHistory) {
    if (role === state.role && section === state.section) return;
    state.role = role;
    state.section = section;
    store.set(K_ROLE, role);
    if (!fromHistory) writeUrl(true);
    resetView();
    paintRoles();
    load("initial");
  }

  function poll() {
    if (document.hidden || state.inFlight > 0 || state.polling || state.view === "key") return;
    state.polling = true;
    var done = function () { state.polling = false; };
    load("poll").then(done, done);
  }

  // ---------- shared helpers for the screens ----------

  // Runs a change (one or several API calls) as one mutation: no poll repaints in between.
  function mutate(fn) {
    beginMutation();
    var settle = function (value) {
      endMutation();
      state.dataSig = null;
      return load("after").then(function () { return value; });
    };
    return Promise.resolve().then(fn).then(settle, function (err) {
      return settle({ ok: false, message: String(err && err.message || err) });
    });
  }

  function reload() { return load("after"); }

  var dialogEl = null;

  function closeDialog() {
    if (!dialogEl) return;
    var d = dialogEl;
    dialogEl = null;
    if (d.open) d.close();
    d.remove();
    if (d._returnFocus && document.contains(d._returnFocus)) d._returnFocus.focus();
  }

  // A modal dialog outside #app. onConfirm returns a promise; {ok:false, message} keeps it open
  // with the message, anything else closes it.
  function openDialog(opts) {
    closeDialog();
    var error = h("p", { class: "dialog__error", role: "alert" });
    var confirm = h("button", {
      type: "submit",
      class: "key " + (opts.danger ? "key--danger" : "key--primary"),
      text: opts.confirmText || "Xác nhận",
    });
    var cancel = h("button", { type: "button", class: "key key--quiet", text: "Huỷ", onclick: closeDialog });
    var form = h("form", { class: "dialog__form", method: "dialog", novalidate: true }, [
      h("h2", { class: "dialog__title", id: "dialog-title", text: opts.title }),
      h("div", { class: "dialog__body" }, [opts.body]),
      error,
      h("div", { class: "dialog__actions" }, [cancel, confirm]),
    ]);
    var d = h("dialog", { class: "dialog", "aria-labelledby": "dialog-title" }, [form]);
    d._returnFocus = document.activeElement;
    var handle = {
      el: d,
      setError: function (text) { error.textContent = text || ""; },
      setConfirmEnabled: function (on) { confirm.disabled = !on; },
      setConfirmText: function (text) { confirm.textContent = text; },
      close: closeDialog,
    };
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (confirm.disabled || confirm.getAttribute("aria-busy") === "true") return;
      error.textContent = "";
      confirm.setAttribute("aria-busy", "true");
      cancel.disabled = true;
      Promise.resolve(opts.onConfirm(handle)).then(function (res) {
        confirm.removeAttribute("aria-busy");
        cancel.disabled = false;
        if (res && res.ok === false) {
          error.textContent = res.message || "Có lỗi xảy ra";
          return;
        }
        closeDialog();
      });
    });
    d.addEventListener("cancel", function (ev) { ev.preventDefault(); if (!cancel.disabled) closeDialog(); });
    document.body.appendChild(d);
    dialogEl = d;
    d.showModal();
    var first = d.querySelector("[autofocus], input, select, textarea");
    (first || confirm).focus();
    return handle;
  }

  var shell = {
    h: h,
    icon: icon,
    api: api,
    notify: notify,
    mutate: mutate,
    reload: reload,
    rerender: function () { renderWork(); },
    openDialog: openDialog,
    closeDialog: closeDialog,
    ui: function () { return state.ui[state.section]; },
    L: L,
  };
  window.ConsoleShell = shell;

  // ---------- reset and admin key ----------

  function askReset() {
    state.confirmReset = true;
    clearTimeout(state.resetTimer);
    state.resetTimer = setTimeout(cancelReset, 5000);
    paintHeadActions();
    var el = app.querySelector('[data-focus="reset-confirm"]');
    if (el) el.focus();
  }

  function cancelReset() {
    clearTimeout(state.resetTimer);
    if (!state.confirmReset) return;
    state.confirmReset = false;
    paintHeadActions();
    var el = app.querySelector('[data-focus="reset"]');
    if (el) el.focus();
  }

  function doReset(ev) {
    clearTimeout(state.resetTimer);
    var btn = ev.currentTarget;
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    mutate(function () { return api("/admin/reset", { method: "POST" }); }).then(function (r) {
      state.confirmReset = false;
      paintHeadActions();
      if (r.ok) {
        state.ui = { permissions: {}, reviews: {} };
        renderWork();
        notify("success", "Đã đưa dữ liệu về trạng thái ban đầu.");
      } else if (r.status !== 401 && r.status !== 403) notify("error", r.data.detail);
      var again = app.querySelector('[data-focus="reset"]');
      if (again) again.focus();
    });
  }

  function changeKey() {
    invalidateLoads();
    state.view = "key";
    state.keyError = null;
    state.changingKey = true;
    render();
  }

  function renderKeyForm() {
    var help = h("p", { class: "field__help" + (state.keyError ? " is-err" : ""), id: "key-help", "aria-live": "polite", text: state.keyError || "" });
    var input = h("input", {
      class: "input",
      id: "admin-key",
      name: "admin-key",
      type: "password",
      autocomplete: "current-password",
      required: true,
      "aria-invalid": state.keyError ? "true" : null,
      "aria-describedby": "key-help",
    });
    var submit = h("button", { type: "submit", class: "key key--primary", text: "Lưu và tiếp tục" });
    var form = h("form", { class: "panel", novalidate: true }, [
      h("h1", { text: "Nhập admin key" }),
      h("p", { text: "Key được lưu trong trình duyệt này để lần sau không phải nhập lại. Key của user1, user2 và user3 đã có sẵn." }),
      h("div", { class: "field" }, [h("label", { for: "admin-key", text: "Admin key" }), input, help]),
      h("div", { class: "head__actions" }, [
        submit,
        state.changingKey && store.get(K_ADMIN)
          ? h("button", { type: "button", class: "key key--quiet", text: "Huỷ", onclick: function () { state.changingKey = false; state.view = null; load("initial"); } })
          : null,
      ]),
    ]);
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var value = input.value.trim();
      if (!value) {
        showKeyError(input, help, "Nhập admin key để tiếp tục.");
        return;
      }
      submit.disabled = true;
      submit.setAttribute("aria-busy", "true");
      api("/admin/users", { key: value }).then(function (r) {
        submit.disabled = false;
        submit.removeAttribute("aria-busy");
        if (r.ok) {
          store.set(K_ADMIN, value);
          state.keyError = null;
          state.changingKey = false;
          state.view = null;
          if (state.role === "admin") load("initial");
        } else if (r.status === 401 || r.status === 403) {
          showKeyError(input, help, "Admin key không đúng. Kiểm tra lại key rồi thử lại.");
        } else {
          showKeyError(input, help, r.data.detail + ". Thử lại sau giây lát.");
        }
      });
    });
    mount([form]);
    input.focus();
  }

  function showKeyError(input, help, text) {
    input.setAttribute("aria-invalid", "true");
    help.className = "field__help is-err";
    help.textContent = text;
    input.focus();
  }

  // ---------- boot ----------

  document.getElementById("roles").addEventListener("click", function (ev) {
    var b = ev.target.closest(".role");
    if (b) switchTo(b.getAttribute("data-role"), state.section);
  });
  sectionsNav.addEventListener("click", function (ev) {
    var b = ev.target.closest(".section-tab");
    if (b) switchTo(state.role, b.getAttribute("data-section"));
  });
  window.addEventListener("popstate", function () {
    switchTo(L.pickRole(window.location.search, store.get(K_ROLE)), L.pickSection(window.location.search), true);
  });
  store.set(K_ROLE, state.role);
  writeUrl(false);
  paintRoles();
  load("initial");
  setInterval(poll, POLL_MS);
})();
