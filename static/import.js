// =====================================================================
// import.js — Importer kunder fra Excel/CSV. Krever core + progress.
// =====================================================================

function openImportModal() {
  $("import-file").value = "";
  $("import-preview").hidden = true;
  $("modal-import").hidden = false;
}

$("btn-import").addEventListener("click", openImportModal);

const _setupImp = $("btn-setup-import");
if (_setupImp) _setupImp.addEventListener("click", openImportModal);

$("import-file").addEventListener("change", async e => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  $("import-info").textContent = "Leser fil...";
  $("import-preview").hidden = false;
  const r = await fetch("/api/import?preview=true", {method: "POST", body: fd});
  const data = await r.json();
  if (data.error) { $("import-info").textContent = "❌ " + data.error; return; }
  $("import-info").innerHTML = `📄 <b>${data.total}</b> rader funnet. Viser de ${data.rows.length} første.`;
  const mapHtml = Object.entries(data.mapping || {}).map(([k, v]) => `<code>${k}</code> ← <b>${esc(v)}</b>`).join(" · ") || "Ingen automatisk mapping";
  $("import-mapping").innerHTML = `<b>Auto-mapping:</b> ${mapHtml}`;
  const cols = data.columns;
  $("preview-table").innerHTML = `
    <thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
    <tbody>${data.rows.slice(0, 30).map(r =>
      `<tr>${cols.map(c => `<td>${esc(r.raw[c] ?? '')}</td>`).join('')}</tr>`
    ).join('')}</tbody>
  `;
});

$("btn-import-confirm").addEventListener("click", async () => {
  const f = $("import-file").files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  const r = await fetch("/api/import", {method: "POST", body: fd});
  const data = await r.json();
  if (data.error) { alert("Feil: " + data.error); return; }
  closeModal("modal-import");
  showProgress("Importerer kunder", "/api/import/status", true);
  pollProgress(async () => {
    await loadStats();
    if (!$("view-customers").hidden) {
      await loadCustomers();
      renderCustomersTab();
    }
  });
});
