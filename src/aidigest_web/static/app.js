// aiDigest: сортировка таблиц и автообновление страницы запуска. Без библиотек.
(function () {
  "use strict";

  // --- сортировка по клику на заголовок с data-sort ---
  function cellText(row, index) {
    var cell = row.children[index];
    if (!cell) return "";
    // data-sort-value — ключ сортировки, когда текст ячейки сортируется неверно (даты дд.мм.гггг, ранги)
    var key = cell.getAttribute("data-sort-value");
    return key !== null ? key : cell.textContent.trim();
  }

  function sortTable(table, index, th) {
    var tbody = table.tBodies[0];
    var rows = Array.prototype.slice.call(tbody.rows);
    var asc = th.getAttribute("aria-sort") !== "ascending";
    rows.sort(function (a, b) {
      var cmp = cellText(a, index).localeCompare(cellText(b, index), "ru", { numeric: true, sensitivity: "base" });
      return asc ? cmp : -cmp;
    });
    table.querySelectorAll("th[data-sort]").forEach(function (h) { h.removeAttribute("aria-sort"); });
    th.setAttribute("aria-sort", asc ? "ascending" : "descending");
    rows.forEach(function (r) { tbody.appendChild(r); });
  }

  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th[data-sort]").forEach(function (th) {
      th.tabIndex = 0;
      th.title = "Сортировать";
      var index = Array.prototype.indexOf.call(th.parentNode.children, th);
      th.addEventListener("click", function () { sortTable(table, index, th); });
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sortTable(table, index, th); }
      });
    });
  });

  // --- «к списку кейсов»: вернуться назад с сохранёнными фильтрами, если пришли со списка ---
  var back = document.querySelector("[data-back]");
  if (back && document.referrer && new URL(document.referrer).origin === location.origin) {
    back.addEventListener("click", function (e) { e.preventDefault(); history.back(); });
  }

  // --- страница запуска: опрос статуса раз в 5 секунд ---
  var running = document.querySelector("[data-running]");
  if (running) {
    var log = document.querySelector("[data-log]");
    var minutes = document.querySelector("[data-minutes]");
    setInterval(function () {
      fetch("/run/status", { headers: { "Accept": "application/json" }, credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (st) {
          if (!st.running) { location.reload(); return; }
          if (minutes && typeof st.minutes === "number") { minutes.textContent = st.minutes; }
          if (log && st.tail && st.tail.length) {
            log.textContent = st.tail.join("\n");
            log.scrollTop = log.scrollHeight;
          }
        })
        .catch(function () { /* сеть моргнула — попробуем в следующий раз */ });
    }, 5000);
  }
})();
