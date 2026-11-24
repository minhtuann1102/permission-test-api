/* Phân quyền miniapp screen (admin). Renders into the shell's work area. */
(function () {
  "use strict";

  function fetchData(api) {
    return Promise.all([api("/admin/users"), api("/admin/miniapps"), api("/admin/permission-log")]).then(function (rs) {
      var bad = rs.filter(function (r) { return !r.ok; })[0];
      if (bad) return { ok: false, status: bad.status, code: bad.data.code, detail: bad.data.detail };
      return { ok: true, data: { users: rs[0].data.users, miniapps: rs[1].data.miniapps }, log: rs[2].data };
    });
  }

  function render(container, data, shell) {
    container.appendChild(shell.h("p", { text: "Đang dựng màn hình phân quyền." }));
  }

  window.PermScreen = { fetch: fetchData, render: render };
})();
