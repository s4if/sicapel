/* Shared SICAPEL front-end helpers. */
(function () {
  "use strict";

  /* ---------- Sidebar drawer (mobile) ---------- */
  function openSidebar() {
    var sb = document.getElementById("appSidebar");
    var bd = document.getElementById("sidebarBackdrop");
    if (sb) sb.classList.add("open");
    if (bd) bd.classList.add("show");
  }

  function closeSidebar() {
    var sb = document.getElementById("appSidebar");
    var bd = document.getElementById("sidebarBackdrop");
    if (sb) sb.classList.remove("open");
    if (bd) bd.classList.remove("show");
  }

  /* ---------- Active-link sync ---------- *
   * The sidebar lives outside #hx_content, so HTMX content swaps do not
   * re-render it. Keep the .active state (and the Administrasi accordion)
   * in sync with the current URL after every navigation. */
  function syncSidebarActive() {
    var sidebar = document.getElementById("appSidebar");
    if (!sidebar) return;
    var seg = location.pathname.replace(/^\/+|\/+$/g, "").split("/")[0] || "";
    sidebar.querySelectorAll("[data-nav-key]").forEach(function (link) {
      link.classList.toggle(
        "active",
        link.getAttribute("data-nav-key") === seg
      );
    });
    // If the active item is an Administrasi sub-item, ensure the group is open.
    var activeSub = sidebar.querySelector("#adminSubmenu [data-nav-key].active");
    if (activeSub) {
      var submenu = document.getElementById("adminSubmenu");
      if (submenu && !submenu.classList.contains("show") && window.bootstrap) {
        bootstrap.Collapse.getOrCreateInstance(submenu, { toggle: false }).show();
      }
    }
  }

  function wireSidebar() {
    var toggle = document.getElementById("sidebarToggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        var sb = document.getElementById("appSidebar");
        if (sb && sb.classList.contains("open")) closeSidebar();
        else openSidebar();
      });
    }
    var bd = document.getElementById("sidebarBackdrop");
    if (bd) bd.addEventListener("click", closeSidebar);
    var sb = document.getElementById("appSidebar");
    if (sb) {
      // Auto-close drawer after a real navigation link is clicked (mobile).
      sb.addEventListener("click", function (e) {
        if (e.target.closest("a[data-nav-key]")) closeSidebar();
      });
    }
    syncSidebarActive();
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireSidebar();

    /* DataTables Indonesian defaults so every list page stays consistent. */
    if (window.jQuery && jQuery.fn && jQuery.fn.dataTable) {
      jQuery.extend(true, jQuery.fn.dataTable.defaults, {
        language: {
          search: "Cari:",
          lengthMenu: "Tampilkan _MENU_ data",
          info: "Menampilkan _START_ - _END_ dari _TOTAL_ data",
          infoEmpty: "Belum ada data",
          emptyTable: "Belum ada data",
          zeroRecords: "Tidak ditemukan data yang cocok",
          paginate: { previous: "Sebelumnya", next: "Selanjutnya" },
        },
      });
    }
  });

  /* Re-sync after HTMX content swaps. */
  document.body.addEventListener("htmx:afterSettle", syncSidebarActive);
})();
