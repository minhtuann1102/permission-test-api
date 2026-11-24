/* Phân quyền miniapp screen (admin): pick a user, pick permissions, confirm, see the result.
 * Renders into the shell's work area; UI state lives in shell.ui() so polling repaints keep it. */
(function () {
  "use strict";

  function fetchData(api) {
    return Promise.all([api("/admin/users"), api("/admin/miniapps"), api("/admin/permission-log")]).then(function (rs) {
      var bad = rs.filter(function (r) { return !r.ok; })[0];
      if (bad) return { ok: false, status: bad.status, code: bad.data.code, detail: bad.data.detail };
      return { ok: true, data: { users: rs[0].data.users, miniapps: rs[1].data.miniapps }, log: rs[2].data };
    });
  }

  function appById(data, id) {
    return data.miniapps.filter(function (m) { return m.id === id; })[0] || { id: id, name: id, roles: [] };
  }

  // Current permissions worth showing: an always-visible miniapp's plain "Xem" is not a grant.
  function currentGrants(L, user, data) {
    return data.miniapps
      .map(function (app) { return { app: app, level: L.levelOf(user, app) }; })
      .filter(function (g) { return g.level !== "none" && !(g.app.always_visible && g.level === "see"); });
  }

  function render(container, data, shell) {
    var h = shell.h;
    var L = shell.L;
    var ui = shell.ui();
    if (!ui.picks) ui.picks = {};
    var users = data.users.filter(function (u) { return u.role === "user"; });
    var user = users.filter(function (u) { return u.username === ui.user; })[0] || null;
    if (!user) ui.user = "";

    var select = h("select", { class: "select", id: "perm-user", "data-focus": "perm-user" },
      [h("option", { value: "", text: "Chọn người dùng" })].concat(users.map(function (u) {
        return h("option", { value: u.username, text: u.display_name + " · " + u.username + (u.email ? " · " + u.email : "") });
      })));
    select.value = ui.user || "";
    select.addEventListener("change", function () {
      ui.user = select.value;
      ui.picks = {};
      ui.pickerOpen = false;
      shell.rerender();
    });

    var body = [h("div", { class: "field-row" }, [h("label", { for: "perm-user", text: "Người dùng" }), select])];

    if (!user) {
      body.push(h("p", { class: "hint", text: "Chọn người dùng để xem quyền đang có và cấp thêm." }));
    } else {
      var org = L.orgLine(user);
      body[0].appendChild(h("p", { class: "who-line" }, [
        org ? h("span", { text: org }) : null,
        L.isResigned(user) ? h("span", { class: "badge badge--gone", text: "Đã nghỉ việc" }) : null,
      ]));
      body.push(currentRow(shell, user, data));
      body.push(pickerRow(shell, user, data));
      var count = L.pickList(ui.picks, data.miniapps).length;
      body.push(h("div", { class: "form-actions" }, [
        h("button", {
          type: "button", class: "key key--primary", "data-focus": "grant", disabled: count === 0,
          text: count ? "Cấp " + count + " quyền" : "Chọn quyền cần cấp",
          onclick: function () { confirmGrant(shell, user, data); },
        }),
      ]));
    }

    container.appendChild(h("section", { class: "card", "aria-labelledby": "perm-title" }, [
      h("h2", { id: "perm-title", text: "Cấp quyền miniapp" }),
    ].concat(body)));

    if (user && ui.results && ui.resultsUser === user.username) {
      container.appendChild(resultsCard(shell, data, ui.results));
    }
  }

  function currentRow(shell, user, data) {
    var h = shell.h;
    var L = shell.L;
    var grants = currentGrants(L, user, data);
    return h("div", { class: "field-row" }, [
      h("p", { class: "field-label", text: "Quyền đang có" }),
      grants.length
        ? h("ul", { class: "chips", role: "list" }, grants.map(function (g) {
            var label = g.app.name + " · " + L.levelLabel(g.level);
            return h("li", { class: "chip" }, [
              h("span", { text: label }),
              h("button", {
                type: "button", class: "chip__x", "aria-label": "Thu hồi " + label, title: "Thu hồi",
                "data-focus": "revoke-" + g.app.id,
                onclick: function () { confirmRevoke(shell, user, g.app, g.level); },
              }, [shell.icon("close")]),
            ]);
          }))
        : h("p", { class: "hint", text: "Chưa có quyền nào." }),
    ]);
  }

  function pickerRow(shell, user, data) {
    var h = shell.h;
    var L = shell.L;
    var ui = shell.ui();
    var picked = L.pickList(ui.picks, data.miniapps);
    var button = h("button", {
      type: "button", class: "picker__button", id: "perm-picker-button", "data-focus": "picker",
      "aria-expanded": ui.pickerOpen ? "true" : "false", "aria-controls": "perm-picker",
      onclick: function () { ui.pickerOpen = !ui.pickerOpen; shell.rerender(); },
    }, [
      picked.length
        ? h("span", { class: "chips" }, picked.map(function (p) {
            return h("span", { class: "chip chip--pick chip--plain", text: appById(data, p.miniapp_id).name + " · " + L.levelLabel(p.level) });
          }))
        : h("span", { class: "picker__placeholder", text: "Chọn một hoặc nhiều quyền" }),
      shell.icon("chevron"),
    ]);
    var row = h("div", { class: "field-row" }, [h("label", { for: "perm-picker-button", text: "Quyền cần cấp" }), button]);
    if (!ui.pickerOpen) return row;

    var panel = h("div", { class: "picker__panel", id: "perm-picker" }, L.grantOptions(user, data.miniapps).map(function (group) {
      return h("fieldset", { class: "picker__group" }, [h("legend", { class: "picker__group-name", text: group.name })]
        .concat(group.options.map(function (o) {
          var input = h("input", {
            type: "checkbox", "data-focus": "opt-" + group.miniapp_id + "-" + o.level,
            checked: ui.picks[group.miniapp_id] === o.level, disabled: o.disabled,
          });
          input.addEventListener("change", function () {
            ui.picks = L.togglePick(ui.picks, group.miniapp_id, o.level);
            shell.rerender();
          });
          return h("label", { class: "option" + (o.disabled ? " is-disabled" : "") }, [
            input, h("span", { text: o.label }), o.note ? h("span", { class: "option__note", text: o.note }) : null,
          ]);
        })));
    }));
    panel.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") return;
      ev.preventDefault();
      ui.pickerOpen = false;
      shell.rerender();
      var b = document.getElementById("perm-picker-button");
      if (b) b.focus();
    });
    row.appendChild(panel);
    return row;
  }

  function resultsCard(shell, data, results) {
    var h = shell.h;
    var L = shell.L;
    return h("section", { class: "card", "aria-labelledby": "perm-results" }, [
      h("h2", { id: "perm-results", text: "Kết quả lần cấp vừa rồi" }),
      h("ul", { class: "results" }, results.map(function (r) {
        var name = appById(data, r.miniapp_id).name + " · " + L.levelLabel(r.level);
        if (!r.ok) {
          return h("li", { class: "result result--err" }, [shell.icon("error"),
            h("span", null, [h("b", { text: name }), ": " + L.errorText(r, {})])]);
        }
        return h("li", { class: "result result--ok" }, [shell.icon("success"), h("span", null, [
          h("b", { text: name }),
          r.changed
            ? h("span", { class: "result__delta", text: " " + L.levelLabel(r.from_level) + " → " + L.levelLabel(r.to_level) })
            : h("span", { class: "result__delta", text: ": đã có sẵn, không đổi" }),
        ])]);
      })),
    ]);
  }

  function confirmGrant(shell, user, data) {
    var h = shell.h;
    var L = shell.L;
    var ui = shell.ui();
    var picks = L.pickList(ui.picks, data.miniapps);
    if (!picks.length) return;
    var checks = picks.map(function (p) {
      var app = appById(data, p.miniapp_id);
      var role = app.roles && app.roles.length ? p.level : "";
      return shell.api("/admin/eligibility?username=" + encodeURIComponent(user.username) +
        "&miniapp_id=" + encodeURIComponent(p.miniapp_id) + "&role=" + encodeURIComponent(role));
    });
    Promise.all(checks).then(function (rs) {
      var anyNo = false;
      var items = picks.map(function (p, i) {
        var app = appById(data, p.miniapp_id);
        var e = rs[i].ok ? rs[i].data : { eligible: false, reasons: [rs[i].data.detail || "Không kiểm tra được"] };
        if (!e.eligible) anyNo = true;
        return h("li", null, [
          h("b", { text: app.name + ": " + L.levelLabel(L.levelOf(user, app)) + " → " + L.levelLabel(p.level) }),
          h("span", { class: e.eligible ? "check-ok" : "check-no",
            text: (e.eligible ? "✓ " : "✕ ") + (e.reasons[0] || (e.eligible ? "Đủ điều kiện" : "Không đủ điều kiện")) }),
        ]);
      });
      var body = h("div", null, [
        h("dl", { class: "facts" }, [
          h("dt", { text: "Người dùng" }), h("dd", { text: user.display_name + " (" + user.username + ")" }),
          h("dt", { text: "Email" }), h("dd", { text: user.email || "—" }),
        ]),
        h("ul", { class: "check-list" }, items),
        anyNo ? h("p", { class: "hint", text: "Quyền không đủ điều kiện vẫn được gửi đi. Hệ thống sẽ từ chối và báo lý do." }) : null,
      ]);
      shell.openDialog({
        title: "Xác nhận cấp quyền",
        body: body,
        confirmText: "Xác nhận cấp " + picks.length + " quyền",
        onConfirm: function () {
          return shell.mutate(function () {
            return shell.api("/admin/users/" + encodeURIComponent(user.username) + "/grants", { method: "POST", body: { grants: picks } });
          }).then(function (r) {
            if (!r.ok) return { ok: false, message: r.data.detail || "Có lỗi xảy ra" };
            ui.results = r.data.results;
            ui.resultsUser = user.username;
            r.data.results.forEach(function (res) { if (res.ok) delete ui.picks[res.miniapp_id]; });
            ui.pickerOpen = false;
            shell.rerender();
            var ok = r.data.results.filter(function (res) { return res.ok; }).length;
            var no = r.data.results.length - ok;
            shell.notify(no ? "error" : "success", "Đã xử lý " + r.data.results.length + " quyền cho " + user.display_name +
              ": " + ok + " thành công" + (no ? ", " + no + " bị từ chối." : "."));
            return { ok: true };
          });
        },
      });
    });
  }

  function confirmRevoke(shell, user, app, level) {
    var h = shell.h;
    var L = shell.L;
    var u = encodeURIComponent(user.username);
    var a = encodeURIComponent(app.id);
    var memberUrl = "/admin/miniapps/" + a + "/members/" + u;
    var allUrl = "/admin/system-access/" + u + "/" + a;
    var body;
    var pick;
    if (level === "use") {
      var r1 = h("input", { type: "radio", name: "revoke", value: "use", checked: true });
      var r2 = h("input", { type: "radio", name: "revoke", value: "all" });
      body = h("div", { class: "check-list" }, [
        h("label", { class: "choice" }, [r1, h("span", null, ["Thu hồi quyền dùng", h("small", { text: "Vẫn xem được " + app.name + ", không dùng được nữa." })])]),
        h("label", { class: "choice" }, [r2, h("span", null, ["Thu hồi hết", h("small", { text: "Không còn thấy " + app.name + "." })])]),
      ]);
      pick = function () { return r2.checked ? allUrl : memberUrl; };
    } else if (app.roles && app.roles.length) {
      body = h("p", { text: "Gỡ " + user.display_name + " khỏi " + app.name + " (đang là " + L.levelLabel(level) + "). Người dùng vẫn thấy " + app.name + " nhưng không còn vai trò." });
      pick = function () { return memberUrl; };
    } else {
      body = h("p", { text: "Thu hồi hết quyền " + app.name + " của " + user.display_name + ". Người dùng sẽ không còn thấy " + app.name + "." });
      pick = function () { return allUrl; };
    }
    shell.openDialog({
      title: "Thu hồi quyền " + app.name + " của " + user.display_name + "?",
      body: body,
      confirmText: "Thu hồi",
      danger: true,
      onConfirm: function () {
        var url = pick();
        return shell.mutate(function () { return shell.api(url, { method: "DELETE" }); }).then(function (r) {
          if (!r.ok) return { ok: false, message: r.data.detail || "Có lỗi xảy ra" };
          shell.notify("success", "Đã thu hồi quyền " + app.name + " của " + user.display_name + ".");
          return { ok: true };
        });
      },
    });
  }

  window.PermScreen = { fetch: fetchData, render: render };
})();
