/* Shared SICAPEL front-end helpers. */

/* Point HTMX body swaps at the single content target and scroll to top on
   navigation. Kept defensive so missing elements never throw. */
document.body.addEventListener("htmx:afterSettle", function () {
  // Re-focus management is left to individual pages.
});

/* DataTables Indonesian defaults so every list page stays consistent. */
window.addEventListener("DOMContentLoaded", function () {
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
