/* Đánh giá screen (admin): tab Phiếu đánh giá and tab Kỳ đánh giá. Renders into the shell's work area. */
(function () {
  "use strict";

  function fetchData(api) {
    return Promise.all([
      api("/admin/users"), api("/admin/reviews/forms"), api("/admin/reviews/periods"), api("/admin/reviews/log"),
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

  function render(container, data, shell) {
    container.appendChild(shell.h("p", { text: "Đang dựng màn hình đánh giá." }));
  }

  window.ReviewScreen = { fetch: fetchData, render: render };
})();
