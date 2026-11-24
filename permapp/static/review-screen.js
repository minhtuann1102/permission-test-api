/* Đánh giá screen (admin): tab Phiếu đánh giá (pick an employee, act on their forms) and tab Kỳ đánh giá
 * (periods: extend, reopen, create, upload HQCV results). Renders into the shell's work area; UI state
 * lives in shell.ui() so polling repaints keep it. Every change goes through the same API as the agent. */
(function () {
  "use strict";

  var R = "/admin/reviews";

  function fetchData(api) {
    return Promise.all([
      api("/admin/users"), api(R + "/forms"), api(R + "/periods"), api(R + "/log"),
    ]).then(function (rs) {
      var bad = rs.filter(function (r) { return !r.ok; })[0];
      if (bad) return { ok: false, status: bad.status, code: bad.data.code, detail: bad.data.detail };
      return {
        ok: true,
        data: { users: rs[0].data.users, forms: rs[1].data.forms, periods: rs[2].data.periods },
        log: rs[3].data,
      };
    });
  }

  // ---------- small helpers ----------

  function vn(iso) {
    if (!iso) return "—";
    var p = String(iso).split("-");
    return p.length === 3 ? p[2] + "/" + p[1] + "/" + p[0] : iso;
  }

  function addDays(iso, n) {
    var d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }

  function pill(shell, status, label) {
    return shell.h("span", { class: "pill pill--" + String(status || "").toLowerCase(), text: label });
  }

  // Why no change at all is possible on this form (the API would refuse), or "".
  function blockedWhy(f) {
    if (f.employee_status === "RESIGNED") return "Nhân viên đã nghỉ việc";
    if (f.period_status === "LOCKED") return "Kỳ đã chốt kết quả";
    if (f.status === "LOCKED") return "Phiếu đã chốt";
    return "";
  }

  function field(shell, id, label, control, help) {
    var h = shell.h;
    control.id = id;
    return h("div", { class: "field-row" }, [h("label", { for: id, text: label }), control, help ? h("p", { class: "hint", text: help }) : null]);
  }

  function dateInput(shell, opts) {
    return shell.h("input", { class: "input", type: "date", min: opts.min || null, max: opts.max || null, value: opts.value || null, required: !!opts.required });
  }

  // Runs one write (or a reopen first, then the write) as one change, and reports in the dialog.
  function write(shell, steps) {
    return shell.mutate(function () {
      var done = [];
      return steps.reduce(function (p, step) {
        return p.then(function (prev) {
          if (prev && !prev.ok) return prev;
          return shell.api(step.path, { method: step.method, body: step.body }).then(function (r) {
            if (r.ok) done.push(r.data.message);
            return r;
          });
        });
      }, Promise.resolve(null)).then(function (last) { return { last: last, done: done }; });
    }).then(function (res) {
      if (!res.last || !res.last.ok) {
        var why = (res.last && res.last.data && res.last.data.detail) || res.message || "Có lỗi xảy ra";
        return { ok: false, message: res.done.length ? res.done.join(" ") + " Nhưng bước tiếp theo không làm được: " + why : why };
      }
      shell.notify("success", res.done.join(" "));
      return { ok: true };
    });
  }

  // ---------- render ----------

  function render(container, data, shell) {
    var h = shell.h;
    var ui = shell.ui();
    if (!ui.tab) ui.tab = "forms";
    var tabs = [["forms", "Phiếu đánh giá"], ["periods", "Kỳ đánh giá"]];
    var tablist = h("div", { class: "tabs", role: "tablist", "aria-label": "Đánh giá" }, tabs.map(function (t) {
      var on = ui.tab === t[0];
      return h("button", {
        type: "button", class: "tab", role: "tab", id: "tab-" + t[0], "aria-selected": on ? "true" : "false",
        "aria-controls": "panel-" + t[0], tabindex: on ? "0" : "-1", "data-focus": "tab-" + t[0], text: t[1],
        onclick: function () { ui.tab = t[0]; shell.rerender(); },
      });
    }));
    tablist.addEventListener("keydown", function (ev) {
      if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
      ui.tab = ui.tab === "forms" ? "periods" : "forms";
      shell.rerender();
      var t = document.getElementById("tab-" + ui.tab);
      if (t) t.focus();
    });
    var panel = h("div", { role: "tabpanel", id: "panel-" + ui.tab, "aria-labelledby": "tab-" + ui.tab, class: "work" });
    if (ui.tab === "forms") renderForms(panel, data, shell);
    else renderPeriods(panel, data, shell);
    container.appendChild(tablist);
    container.appendChild(panel);
  }

  // ---------- tab: Phiếu đánh giá ----------

  function renderForms(panel, data, shell) {
    var h = shell.h;
    var L = shell.L;
    var ui = shell.ui();
    var people = data.users.filter(function (u) { return u.role === "user"; });
    var person = people.filter(function (u) { return u.username === ui.employee; })[0] || null;
    var select = h("select", { class: "select", "data-focus": "employee" },
      [h("option", { value: "", text: "Chọn nhân viên" })].concat(people.map(function (u) {
        return h("option", { value: u.username, text: u.display_name + " · " + u.username + (u.email ? " · " + u.email : "") });
      })));
    select.value = person ? person.username : "";
    select.addEventListener("change", function () { ui.employee = select.value; shell.rerender(); });
    var pick = field(shell, "employee", "Nhân viên", select);
    if (person) {
      pick.appendChild(h("p", { class: "who-line" }, [
        L.orgLine(person) ? h("span", { text: L.orgLine(person) }) : null,
        L.isResigned(person) ? h("span", { class: "badge badge--gone", text: "Đã nghỉ việc" }) : null,
      ]));
    }
    panel.appendChild(h("section", { class: "card", "aria-label": "Chọn nhân viên" }, [pick]));
    if (!person) {
      panel.appendChild(h("p", { class: "hint", text: "Chọn nhân viên để xem và xử lý các phiếu đánh giá của họ." }));
      return;
    }
    var forms = data.forms.filter(function (f) { return f.username === person.username; });
    if (!forms.length) {
      panel.appendChild(h("div", { class: "state-block" }, [h("h2", { text: "Nhân viên này chưa có phiếu nào" })]));
      return;
    }
    forms.forEach(function (f) { panel.appendChild(formCard(shell, f)); });
  }

  function actionButton(shell, id, text, why, onclick) {
    var h = shell.h;
    return h("button", {
      type: "button", class: "key key--small", "data-focus": id, text: text,
      disabled: !!why, title: why || null, "aria-describedby": why ? id + "-why" : null, onclick: onclick,
    });
  }

  function formCard(shell, f) {
    var h = shell.h;
    var blocked = blockedWhy(f);
    var extendWhy = blocked ||
      (f.status === "APPROVED" ? "Phiếu đã phê duyệt: dùng Mở lại phiếu" : "") ||
      (f.period_status === "CLOSED" && !f.personal_deadline ? "Kỳ đã đóng: dùng Mở lại phiếu kèm hạn riêng" : "");
    var actions = h("div", { class: "actions" }, [
      actionButton(shell, "reopen-" + f.id, "Mở lại phiếu", blocked, function () { reopenForm(shell, f); }),
      actionButton(shell, "extend-" + f.id, "Gia hạn", extendWhy, function () { extendForm(shell, f); }),
      actionButton(shell, "evaluator-" + f.id, "Đổi người đánh giá", blocked, function () { changeEvaluator(shell, f); }),
      blocked || extendWhy ? h("span", { class: "disabled-why", id: (blocked ? "reopen-" : "extend-") + f.id + "-why", text: blocked || extendWhy }) : null,
    ]);
    var goals = f.goals.length
      ? h("div", { class: "table-wrap" }, [h("table", { class: "table" }, [
          h("thead", null, [h("tr", null, ["Mã", "Mục tiêu / tiêu chí", "Trọng số", "Chỉ tiêu", ""].map(function (t) { return h("th", { scope: "col", text: t }); }))]),
          h("tbody", null, f.goals.map(function (g) {
            return h("tr", null, [
              h("td", { class: "num", text: g.id }),
              h("td", { text: g.title }),
              h("td", { class: "num", text: g.weight + "%" }),
              h("td", { text: g.target || "—" }),
              h("td", null, [h("div", { class: "actions" }, [
                actionButton(shell, "goal-edit-" + g.id, "Sửa", blocked, function () { editGoal(shell, f, g); }),
                actionButton(shell, "goal-del-" + g.id, "Xoá", blocked, function () { deleteGoal(shell, f, g); }),
              ])]),
            ]);
          })),
        ])])
      : h("p", { class: "hint", text: "Phiếu chưa có mục tiêu nào." });
    return h("article", { class: "card form-card", "aria-labelledby": "form-" + f.id }, [
      h("div", { class: "form-card__head" }, [
        h("h3", { id: "form-" + f.id, text: f.id + " · " + f.kind_label }),
        pill(shell, f.status, f.status_label),
      ]),
      h("p", { class: "form-card__meta" }, [
        h("span", { text: f.period_name ? "Kỳ: " + f.period_name : "Không theo kỳ" }),
        h("span", { text: "Hạn: " + vn(f.deadline) + (f.personal_deadline ? " (hạn riêng)" : "") }),
        h("span", { text: "Gia hạn tối đa: " + vn(f.max_deadline) }),
      ]),
      h("div", null, [
        h("p", { class: "field-label", text: "Người đánh giá" }),
        f.evaluators.length
          ? h("ul", { class: "evaluators" }, f.evaluators.map(function (e) { return h("li", null, [e.email + " ", h("small", { text: "(" + e.relation_label + ")" })]); }))
          : h("p", { class: "hint", text: "Chưa có người đánh giá." }),
      ]),
      goals,
      f.goals.length && !f.weight_ok ? h("p", { class: "hint hint--warn", text: "Tổng trọng số đang là " + f.total_weight + "%, cần đủ 100%." }) : null,
      actions,
    ]);
  }

  // Steps that need an approved form reopened first ("Mở lại phiếu rồi …", one confirm for both).
  function withReopen(f, step) {
    return f.status === "APPROVED"
      ? [{ path: R + "/forms/" + encodeURIComponent(f.id) + "/reopen", method: "POST", body: {} }, step]
      : [step];
  }

  function approvedNote(shell, f) {
    return f.status === "APPROVED"
      ? shell.h("p", { class: "hint hint--warn", text: "Phiếu đã phê duyệt: hệ thống sẽ mở lại phiếu (về Đang nhập) trước, rồi mới thực hiện." })
      : null;
  }

  function reopenForm(shell, f) {
    var h = shell.h;
    var closed = f.period_status === "CLOSED" && !f.personal_deadline;
    var date = dateInput(shell, { min: addDays(f.deadline, 1), required: closed });
    var body = h("div", null, [
      h("p", { text: f.id + " của " + f.employee_name + " sẽ về trạng thái Đang nhập để nhân viên sửa lại." }),
      field(shell, "reopen-date", closed ? "Hạn riêng (bắt buộc)" : "Hạn riêng (không bắt buộc)", date,
        closed ? "Kỳ " + f.period_name + " đã đóng: hạn riêng mở lại cho riêng nhân viên này." : "Bỏ trống để giữ hạn hiện tại " + vn(f.deadline) + "."),
    ]);
    shell.openDialog({
      title: "Mở lại phiếu " + f.id + "?", body: body, confirmText: "Mở lại phiếu",
      onConfirm: function () {
        if (closed && !date.value) return { ok: false, message: "Nhập hạn riêng cho phiếu này." };
        return write(shell, [{ path: R + "/forms/" + encodeURIComponent(f.id) + "/reopen", method: "POST", body: { deadline: date.value || "" } }]);
      },
    });
  }

  function extendForm(shell, f) {
    var h = shell.h;
    var date = dateInput(shell, { min: addDays(f.deadline, 1), max: f.max_deadline, required: true });
    shell.openDialog({
      title: "Gia hạn phiếu " + f.id,
      body: h("div", null, [
        h("p", { text: "Hạn hiện tại " + vn(f.deadline) + ". Gia hạn tối đa đến " + vn(f.max_deadline) + "." }),
        field(shell, "extend-date", "Hạn mới", date),
      ]),
      confirmText: "Gia hạn",
      onConfirm: function () {
        if (!date.value) return { ok: false, message: "Chọn hạn mới." };
        return write(shell, [{ path: R + "/forms/" + encodeURIComponent(f.id) + "/extend", method: "POST", body: { deadline: date.value } }]);
      },
    });
  }

  function changeEvaluator(shell, f) {
    var h = shell.h;
    var many = f.evaluators.length > 1;
    var old = h("select", { class: "select" }, f.evaluators.map(function (e) { return h("option", { value: e.email, text: e.email + " (" + e.relation_label + ")" }); }));
    var email = h("input", { class: "input", type: "email", autocomplete: "off", placeholder: "ten@demo.local", required: true });
    var body = h("div", null, [
      approvedNote(shell, f),
      many ? field(shell, "ev-old", "Người cần thay", old)
        : h("p", { text: "Người đánh giá hiện tại: " + (f.evaluators[0] ? f.evaluators[0].email : "(trống)") + "." }),
      field(shell, "ev-new", "Email người đánh giá mới", email),
    ]);
    shell.openDialog({
      title: "Đổi người đánh giá phiếu " + f.id, body: body,
      confirmText: f.status === "APPROVED" ? "Mở lại phiếu rồi đổi" : "Đổi người đánh giá",
      onConfirm: function () {
        if (!email.value.trim()) return { ok: false, message: "Nhập email người đánh giá mới." };
        return write(shell, withReopen(f, {
          path: R + "/forms/" + encodeURIComponent(f.id) + "/evaluator", method: "PUT",
          body: { new_email: email.value.trim(), old_email: many ? old.value : "" },
        }));
      },
    });
  }

  function editGoal(shell, f, g) {
    var h = shell.h;
    var title = h("input", { class: "input", type: "text", value: g.title });
    var weight = h("input", { class: "input", type: "number", min: "1", max: "100", step: "1", value: String(g.weight) });
    var target = h("input", { class: "input", type: "text", value: g.target || "" });
    shell.openDialog({
      title: "Sửa mục tiêu " + g.id,
      body: h("div", null, [approvedNote(shell, f), field(shell, "goal-title", "Nội dung", title),
        field(shell, "goal-weight", "Trọng số (%)", weight), field(shell, "goal-target", "Chỉ tiêu", target)]),
      confirmText: f.status === "APPROVED" ? "Mở lại phiếu rồi sửa" : "Lưu thay đổi",
      onConfirm: function () {
        var w = parseInt(weight.value, 10);
        if (!(w >= 1 && w <= 100)) return { ok: false, message: "Trọng số phải từ 1 đến 100." };
        return write(shell, withReopen(f, {
          path: R + "/goals/" + encodeURIComponent(g.id), method: "PUT",
          body: { title: title.value.trim(), weight: w, target: target.value.trim() },
        }));
      },
    });
  }

  function deleteGoal(shell, f, g) {
    var h = shell.h;
    shell.openDialog({
      title: "Xoá mục tiêu " + g.id + "?",
      body: h("div", null, [approvedNote(shell, f),
        h("p", { text: "“" + g.title + "” (" + g.weight + "%) sẽ bị xoá khỏi phiếu " + f.id + " của " + f.employee_name + "." })]),
      confirmText: f.status === "APPROVED" ? "Mở lại phiếu rồi xoá" : "Xoá mục tiêu",
      danger: true,
      onConfirm: function () {
        return write(shell, withReopen(f, { path: R + "/goals/" + encodeURIComponent(g.id), method: "DELETE" }));
      },
    });
  }

  // ---------- tab: Kỳ đánh giá ----------

  function renderPeriods(panel, data, shell) {
    var h = shell.h;
    var head = h("div", { class: "card__head" }, [
      h("h2", { text: "Kỳ đánh giá" }),
      h("button", { type: "button", class: "key key--primary key--small", "data-focus": "create-period", text: "+ Tạo kỳ", onclick: function () { createPeriod(shell); } }),
    ]);
    var rows = data.periods.map(function (p) {
      var acts;
      if (p.status === "OPEN") {
        acts = [actionButton(shell, "p-extend-" + p.id, "Gia hạn", "", function () { extendPeriod(shell, p); })];
      } else if (p.status === "CLOSED") {
        acts = [
          actionButton(shell, "p-reopen-" + p.id, "Mở lại", "", function () { reopenPeriod(shell, p); }),
          actionButton(shell, "p-results-" + p.id, "Tải kết quả HQCV", "", function () { importResults(shell, p); }),
        ];
      } else {
        acts = [h("span", { class: "disabled-why", text: "Đã chốt, không thao tác được" })];
      }
      return h("tr", null, [
        h("td", null, [h("b", { text: p.id }), h("small", { text: p.name })]),
        h("td", null, [pill(shell, p.status, p.status_label)]),
        h("td", { class: "num", text: vn(p.start_date) }),
        h("td", { class: "num" }, [vn(p.deadline), p.deadline !== p.original_deadline ? h("small", { text: "gốc " + vn(p.original_deadline) }) : null]),
        h("td", { class: "num", text: p.status === "OPEN" ? vn(p.max_deadline) : "—" }),
        h("td", { class: "num", text: p.form_count + " phiếu · " + p.result_count + " KQ" }),
        h("td", null, [h("div", { class: "actions" }, acts)]),
      ]);
    });
    panel.appendChild(h("section", { class: "card", "aria-label": "Kỳ đánh giá" }, [
      head,
      h("div", { class: "table-wrap" }, [h("table", { class: "table" }, [
        h("thead", null, [h("tr", null, ["Kỳ", "Trạng thái", "Bắt đầu", "Hạn", "Gia hạn tối đa", "Số liệu", ""].map(function (t) { return h("th", { scope: "col", text: t }); }))]),
        h("tbody", null, rows),
      ])]),
    ]));
  }

  function extendPeriod(shell, p) {
    var h = shell.h;
    var date = dateInput(shell, { min: addDays(p.deadline, 1), max: p.max_deadline, required: true });
    shell.openDialog({
      title: "Gia hạn kỳ " + p.id,
      body: h("div", null, [
        h("p", { text: p.name + ". Hạn hiện tại " + vn(p.deadline) + ", gia hạn tối đa đến " + vn(p.max_deadline) + " (30 ngày so với hạn gốc)." }),
        field(shell, "p-extend-date", "Hạn mới", date),
      ]),
      confirmText: "Gia hạn kỳ",
      onConfirm: function () {
        if (!date.value) return { ok: false, message: "Chọn hạn mới." };
        return write(shell, [{ path: R + "/periods/" + encodeURIComponent(p.id) + "/extend", method: "POST", body: { deadline: date.value } }]);
      },
    });
  }

  function reopenPeriod(shell, p) {
    var h = shell.h;
    var date = dateInput(shell, { min: addDays(p.deadline, 1), required: true });
    shell.openDialog({
      title: "Mở lại kỳ " + p.id + "?",
      body: h("div", null, [
        h("p", { text: p.name + " đã đóng từ " + vn(p.deadline) + ". Mở lại cho mọi nhân viên với hạn mới. Muốn mở cho một người thì dùng Mở lại phiếu kèm hạn riêng." }),
        field(shell, "p-reopen-date", "Hạn mới", date),
      ]),
      confirmText: "Mở lại kỳ",
      onConfirm: function () {
        if (!date.value) return { ok: false, message: "Chọn hạn mới." };
        return write(shell, [{ path: R + "/periods/" + encodeURIComponent(p.id) + "/reopen", method: "POST", body: { deadline: date.value } }]);
      },
    });
  }

  function createPeriod(shell) {
    var h = shell.h;
    var year = new Date().getFullYear();
    var company = h("input", { class: "input", type: "text", placeholder: "Ví dụ: Vinhomes", required: true });
    var kind = h("select", { class: "select" }, [
      ["KPI_MONTH", "KPI tháng"], ["KPI_QUARTER", "KPI quý"], ["KPI_YEAR", "KPI năm"], ["REVIEW_360", "Đánh giá 360"],
    ].map(function (k) { return h("option", { value: k[0], text: k[1] }); }));
    var yearIn = h("input", { class: "input", type: "number", min: "2020", max: "2100", value: String(year) });
    var number = h("select", { class: "select" });
    var numberRow = field(shell, "p-number", "Tháng", number);
    function fillNumbers() {
      var n = kind.value === "KPI_MONTH" ? 12 : 4;
      number.textContent = "";
      for (var i = 1; i <= n; i++) number.appendChild(h("option", { value: String(i), text: (kind.value === "KPI_MONTH" ? "Tháng " : "Quý ") + i }));
      numberRow.hidden = kind.value !== "KPI_MONTH" && kind.value !== "KPI_QUARTER";
      numberRow.querySelector("label").textContent = kind.value === "KPI_MONTH" ? "Tháng" : "Quý";
    }
    kind.addEventListener("change", fillNumbers);
    var start = dateInput(shell, { required: true });
    var deadline = dateInput(shell, { required: true });
    var body = h("div", null, [
      field(shell, "p-company", "Công ty / đơn vị", company),
      field(shell, "p-kind", "Loại kỳ", kind),
      field(shell, "p-year", "Năm", yearIn),
      numberRow,
      field(shell, "p-start", "Ngày bắt đầu", start),
      field(shell, "p-deadline", "Hạn", deadline),
    ]);
    fillNumbers();
    shell.openDialog({
      title: "Tạo kỳ đánh giá", body: body, confirmText: "Tạo kỳ",
      onConfirm: function () {
        if (!company.value.trim() || !start.value || !deadline.value) return { ok: false, message: "Nhập đủ công ty, ngày bắt đầu và hạn." };
        return write(shell, [{ path: R + "/periods", method: "POST", body: {
          company: company.value.trim(), kind: kind.value, year: parseInt(yearIn.value, 10) || year,
          number: numberRow.hidden ? 0 : parseInt(number.value, 10), start_date: start.value, deadline: deadline.value,
        } }]);
      },
    });
  }

  function importResults(shell, p) {
    var h = shell.h;
    var L = shell.L;
    var text = h("textarea", { class: "input", placeholder: "user1@demo.local, 85, B\nuser2@demo.local, 92, A", spellcheck: "false" });
    var preview = h("div");
    var body = h("div", null, [
      h("p", { text: "Dán bảng kết quả (mỗi dòng: email, điểm, xếp loại; cách nhau bằng dấu phẩy hoặc Tab). Có 1 dòng sai thì không dòng nào được ghi." }),
      field(shell, "p-results", "Kết quả HQCV", text),
      preview,
    ]);
    var handle;
    function update() {
      var parsed = L.parseResultRows(text.value);
      preview.textContent = "";
      if (parsed.rows.length) {
        preview.appendChild(h("table", { class: "preview" }, [
          h("thead", null, [h("tr", null, ["Email", "Điểm", "Xếp loại"].map(function (t) { return h("th", { scope: "col", text: t }); }))]),
          h("tbody", null, parsed.rows.map(function (r) { return h("tr", null, [h("td", { text: r.email }), h("td", { text: String(r.score) }), h("td", { text: r.grade })]); })),
        ]));
      }
      parsed.errors.forEach(function (e) { preview.appendChild(h("p", { class: "check-no", text: e })); });
      if (handle) {
        handle.setConfirmEnabled(parsed.rows.length > 0 && !parsed.errors.length);
        handle.setConfirmText(parsed.rows.length ? "Tải " + parsed.rows.length + " kết quả" : "Tải kết quả");
      }
      return parsed;
    }
    text.addEventListener("input", update);
    handle = shell.openDialog({
      title: "Tải kết quả HQCV · " + p.id, body: body, confirmText: "Tải kết quả",
      onConfirm: function () {
        var parsed = update();
        return write(shell, [{ path: R + "/periods/" + encodeURIComponent(p.id) + "/results", method: "POST", body: { rows: parsed.rows } }]);
      },
    });
    update();
  }

  window.ReviewScreen = { fetch: fetchData, render: render };
})();
