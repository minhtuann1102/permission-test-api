/* Demo console: DOM + network. Pure rules live in console-logic.js (window.ConsoleLogic). */
(function () {
  "use strict";

  var L = window.ConsoleLogic;
  var POLL_MS = 3000;
  var USER_KEYS = { user1: "user1-key-123", user2: "user2-key-123" };
  var K_ROLE = "permconsole.role";
  var K_ADMIN = "permconsole.adminKey";

  var storage = null;
  try { storage = window.localStorage; } catch (e) { storage = null; }
  var store = L.safeStore(storage);

  var app = document.getElementById("app");
  var syncEl = document.getElementById("sync");
  var syncLive = document.getElementById("sync-live");

  var state = {
    role: L.pickRole(window.location.search, store.get(K_ROLE)),
    seq: 0,
    lastMutationStartSeq: 0,
    inFlight: 0,
    polling: false,
    latestLoadSeq: 0,
    data: null,
    dataSig: null,
    snapshot: null,
    notice: null,
    noticeTimer: null,
    view: null,
    syncOk: null,
    cellError: null,
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
    if (ok !== state.syncOk) {
      state.syncOk = ok;
      syncLive.textContent = ok ? "Đã cập nhật lại dữ liệu." : "Không cập nhật được dữ liệu, đang thử lại.";
    }
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
        h("div", { class: "skeleton skeleton--grid", "aria-busy": "true", "aria-label": "Đang tải" },
          [0, 1, 2].map(function (r) { return h("div", { class: r === 0 ? "skeleton__head" : "skeleton__row" }, [h("i"), h("i"), h("i"), h("i")]); })),
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
        h("p", { text: "Bạn đang xem với tài khoản " + me.display_name + " (" + (me.email || me.username) + "). Miniapp chưa được cấp quyền hệ thống sẽ không hiện ở đây." }),
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
    if (btn.getAttribute("aria-busy") === "true") return;
    beginMutation();
    btn.setAttribute("aria-busy", "true");
    btn.setAttribute("aria-disabled", "true");
    api("/miniapps/" + encodeURIComponent(a.id) + "/use", { method: "POST", key: currentKey() }).then(function (r) {
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
    var req = role === "admin" ? fetchAdmin(key) : fetchUser(key);
    return req.then(function (res) {
      if (role !== state.role) return;
      if (!L.shouldApplyLoad(seq, state.latestLoadSeq, state.lastMutationStartSeq, state.inFlight)) return;
      if (!res.ok) {
        if (role === "admin" && (res.status === 401 || res.status === 403)) {
          store.remove(K_ADMIN);
          state.view = "key";
          state.keyError = "Admin key đã lưu không còn đúng. Nhập lại key.";
          render();
          return;
        }
        if (kind !== "initial" && state.data) { setSync(false); return; }
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

  function writeUrl(role, push) {
    try {
      var url = window.location.pathname + "?as=" + role;
      if (push) window.history.pushState({ as: role }, "", url);
      else window.history.replaceState({ as: role }, "", url);
    } catch (e) { /* history unavailable: the view still works */ }
  }

  function switchRole(role, fromHistory) {
    if (role === state.role) return;
    state.role = role;
    store.set(K_ROLE, role);
    if (!fromHistory) writeUrl(role, true);
    state.cellError = null;
    state.data = null;
    state.dataSig = null;
    state.snapshot = null;
    state.notice = null;
    state.view = null;
    invalidateLoads();
    state.keyError = null;
    state.changingKey = false;
    state.confirmReset = false;
    clearTimeout(state.resetTimer);
    paintRoles();
    load("initial");
  }

  function poll() {
    if (document.hidden || state.inFlight > 0 || state.polling || state.view === "key") return;
    state.polling = true;
    var done = function () { state.polling = false; };
    load("poll").then(done, done);
  }

  // ---------- admin ----------

  function fetchAdmin(key) {
    return Promise.all([api("/admin/users", { key: key }), api("/admin/miniapps", { key: key })]).then(function (rs) {
      var bad = rs.filter(function (r) { return !r.ok; })[0];
      if (bad) return { ok: false, status: bad.status, detail: bad.data.detail };
      var users = rs[0].data.users;
      var miniapps = rs[1].data.miniapps;
      return { ok: true, data: { users: users, miniapps: miniapps }, snapshot: L.adminSnapshot(users, miniapps) };
    });
  }

  function switchButton(kind, user, app, on, label, step, waiting) {
    var id = kind + "|" + user.username + "|" + app.id;
    return h("button", {
      type: "button",
      class: "switch" + (waiting ? " switch--waiting" : ""),
      role: "switch",
      "aria-checked": on ? "true" : "false",
      "data-focus": id,
      onclick: function (ev) { toggle(kind, user, app, on, ev.currentTarget); },
    }, [
      h("span", { class: "switch__track", "aria-hidden": "true" }, [h("span", { class: "switch__thumb" })]),
      h("span", { class: "switch__label" }, [
        h("span", { class: "switch__step", "aria-hidden": "true", text: step + "." }),
        h("span", { text: label }),
        waiting ? h("span", { class: "switch__hint", text: "cần bước 1" }) : null,
      ]),
    ]);
  }

  function renderAdmin(highlight) {
    var users = state.data.users.filter(function (u) { return u.role === "user"; });
    var miniapps = state.data.miniapps;

    var resetArea = state.confirmReset
      ? [
          h("button", { type: "button", class: "key key--danger", "data-focus": "reset-confirm", text: "Xác nhận reset", onclick: doReset }),
          h("button", { type: "button", class: "key key--quiet", "data-focus": "reset-cancel", text: "Huỷ", onclick: cancelReset }),
        ]
      : [h("button", { type: "button", class: "key key--quiet key--danger", "data-focus": "reset", text: "Reset dữ liệu", onclick: askReset })];

    var head = h("div", { class: "head" }, [
      h("div", null, [
        h("h1", { text: "Phân quyền miniapp" }),
        h("p", { text: "Bước 1: bật Quyền hệ thống để người dùng nhìn thấy miniapp. Bước 2: bật Thành viên để họ dùng được. Phải có bước 1 trước bước 2." }),
      ]),
      h("div", { class: "head__actions" }, [
        h("button", { type: "button", class: "key key--quiet", "data-focus": "change-key", text: "Đổi admin key", onclick: changeKey }),
      ].concat(resetArea)),
    ]);

    if (!users.length || !miniapps.length) {
      mount([head, noticeEl(), h("div", { class: "state-block" }, [
        h("h2", { text: "Chưa có người dùng hoặc miniapp nào" }),
        h("p", { text: "Dữ liệu mẫu được tạo khi reset. Bấm Reset dữ liệu để tạo lại." }),
      ])]);
      return;
    }

    var thead = h("thead", null, [h("tr", null, [h("th", { scope: "col", text: "Người dùng" })].concat(
      miniapps.map(function (m) { return h("th", { scope: "col" }, [m.name, h("small", { text: m.id })]); })
    ))]);

    var rows = users.map(function (u) {
      var cells = miniapps.map(function (m) {
        var st = L.cellState(u, m.id);
        var sees = st !== "none";
        var member = st === "use";
        var key = u.username + "|" + m.id;
        return h("td", { "data-label": m.name }, [
          h("div", { class: "cell" + (highlight.indexOf(key) !== -1 ? " is-changed" : "") }, [
            h("p", { class: "state state--" + st }, [icon(st), L.STATE_LABEL[st]]),
            switchButton("system", u, m, sees, "Quyền hệ thống", 1, false),
            switchButton("member", u, m, member, "Thành viên", 2, !sees),
            state.cellError && state.cellError.key === key
              ? h("p", { class: "cell__error", role: "alert" }, [icon("error"), h("span", { text: state.cellError.text })])
              : null,
          ]),
        ]);
      });
      return h("tr", null, [h("th", { scope: "row", class: "who" }, [h("b", { text: u.display_name }), h("span", { text: u.username }), u.email ? h("span", { class: "who__email", text: u.email }) : null])].concat(cells));
    });

    mount([
      head,
      noticeEl(),
      h("div", { class: "grid-wrap" }, [h("table", { class: "grid" }, [
        h("caption", { class: "visually-hidden", text: "Quyền của từng người dùng với từng miniapp" }),
        thead,
        h("tbody", null, rows),
      ])]),
    ]);
  }

  function toggle(kind, user, app, isOn, btn) {
    var username = user.username;
    var appId = app.id;
    if (btn.getAttribute("aria-busy") === "true") return Promise.resolve();
    var focusId = btn.getAttribute("data-focus");
    var key = currentKey();
    var req;
    if (kind === "system") {
      req = isOn
        ? api("/admin/system-access/" + encodeURIComponent(username) + "/" + encodeURIComponent(appId), { method: "DELETE", key: key })
        : api("/admin/system-access", { method: "POST", key: key, body: { username: username, miniapp_id: appId } });
    } else {
      req = isOn
        ? api("/admin/miniapps/" + encodeURIComponent(appId) + "/members/" + encodeURIComponent(username), { method: "DELETE", key: key })
        : api("/admin/miniapps/" + encodeURIComponent(appId) + "/members", { method: "POST", key: key, body: { username: username } });
    }
    beginMutation();
    btn.setAttribute("aria-disabled", "true");
    btn.setAttribute("aria-busy", "true");
    return req.then(function (r) {
      endMutation();
      var cellKey = username + "|" + appId;
      if (!r.ok) {
        if (r.status === 401 || r.status === 403) return load("after");
        state.cellError = { key: cellKey, text: L.errorText(r.data, { user: user.display_name, app: app.name }) };
      } else {
        if (state.cellError && state.cellError.key === cellKey) state.cellError = null;
        if (state.role === "admin") {
          var what = kind === "system" ? "quyền hệ thống" : "thành viên";
          notify("success", (isOn ? "Đã gỡ " : "Đã cấp ") + what + " " + app.name + " cho " + user.display_name + ".");
        }
      }
      state.dataSig = null; // force a repaint so the switch shows the server's truth
      return load("after").then(function () {
        // Only restore focus if the repaint dropped it; never pull it off another control.
        if (document.activeElement && document.activeElement !== document.body) return;
        var again = app.querySelector('[data-focus="' + focusId + '"]');
        if (again) again.focus();
      });
    });
  }

  function askReset() {
    state.confirmReset = true;
    clearTimeout(state.resetTimer);
    state.resetTimer = setTimeout(cancelReset, 5000);
    keepFocusOn("reset-confirm", function () { render(); });
  }

  function cancelReset() {
    clearTimeout(state.resetTimer);
    if (!state.confirmReset) return;
    state.confirmReset = false;
    if (state.view === "admin") keepFocusOn("reset", function () { render(); });
  }

  function doReset(ev) {
    clearTimeout(state.resetTimer);
    var btn = ev.currentTarget;
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    beginMutation();
    api("/admin/reset", { method: "POST", key: currentKey() }).then(function (r) {
      endMutation();
      state.confirmReset = false;
      if (r.ok) notify("success", "Đã đưa dữ liệu về trạng thái ban đầu.");
      else if (r.status !== 401 && r.status !== 403) notify("error", r.data.detail);
      state.dataSig = null;
      load("after").then(function () {
        var again = app.querySelector('[data-focus="reset"]');
        if (again) again.focus();
      });
    });
  }

  function keepFocusOn(id, fn) {
    fn();
    var el = app.querySelector('[data-focus="' + id + '"]');
    if (el) el.focus();
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
      h("p", { text: "Key được lưu trong trình duyệt này để lần sau không phải nhập lại. Key của user1 và user2 đã có sẵn." }),
      h("div", { class: "field" }, [h("label", { for: "admin-key", text: "Admin key" }), input, help]),
      h("div", { class: "head__actions" }, [
        submit,
        state.changingKey && store.get(K_ADMIN)
          ? h("button", { type: "button", class: "key key--quiet", text: "Huỷ", onclick: function () { state.changingKey = false; load("initial"); } })
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
    if (b) switchRole(b.getAttribute("data-role"));
  });
  window.addEventListener("popstate", function () {
    switchRole(L.pickRole(window.location.search, store.get(K_ROLE)), true);
  });
  store.set(K_ROLE, state.role);
  writeUrl(state.role, false);
  paintRoles();
  load("initial");
  setInterval(poll, POLL_MS);
})();
