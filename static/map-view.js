/* map-view.js — Leaflet-kart for LeadMap
 * Laster Leaflet + MarkerCluster fra CDN ved første bruk.
 * Eksponerer window.MapView.show() / .hide() / .reload()
 * Krever: <div id="view-map" hidden> i index.html
 */
/* global L */
window.MapView = (() => {
  'use strict';

  let map = null;
  let markerLayer = null;
  let anchorLayer = null;
  let allLeads = [];
  let allAnchors = [];
  let initialized = false;
  let useTableFilter = true;  // bruk filtrert tabell-state som standard

  // ── Fargeskala ────────────────────────────────────────────────
  function scoreColor(score) {
    if (score >= 70) return '#16a34a';
    if (score >= 45) return '#d97706';
    if (score >= 20) return '#ea580c';
    return '#dc2626';
  }
  function statusEmoji(s) {
    return ({ Ny: '🆕', Kontaktet: '📞', 'Follow-up': '🔁',
      'Ikke aktuell': '🚫', Vunnet: '🏆' })[s] || s || '';
  }

  // ── CDN-lasting (lazy) ────────────────────────────────────────
  function loadLeaflet() {
    return new Promise(resolve => {
      if (window.L && window.L.markerClusterGroup) { resolve(); return; }
      const addLink = href => {
        const el = document.createElement('link');
        el.rel = 'stylesheet'; el.href = href;
        document.head.appendChild(el);
      };
      const addScript = (src, cb) => {
        const el = document.createElement('script');
        el.src = src; el.onload = cb;
        document.head.appendChild(el);
      };
      addLink('https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css');
      addLink('https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.Default.min.css');
      addLink('https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.min.css');
      addScript(
        'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js',
        () => addScript(
          'https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/leaflet.markercluster.min.js',
          resolve
        )
      );
    });
  }

  // ── Bygg innhold i #view-map ──────────────────────────────────
  function buildUI() {
    const root = document.getElementById('view-map');
    if (!root || root.dataset.mapBuilt) return;
    root.dataset.mapBuilt = '1';
    // Beregn top dynamisk (header + tab-bar)
    const navEl = document.querySelector('.main-tabs');
    const top = navEl ? Math.round(navEl.getBoundingClientRect().bottom) : 177;
    root.style.cssText = [
      'position:fixed',
      `top:${top}px`,
      'left:0',
      'right:0',
      'bottom:0',
      'z-index:20',
      'display:flex',
      'flex-direction:column',
      'background:var(--surface,#f8fafc)',
    ].join(';');

    root.innerHTML = `
      <div id="map-toolbar" style="
        display:flex;align-items:center;gap:10px;flex-wrap:wrap;
        padding:8px 14px;background:var(--card-bg,#fff);
        border-bottom:1px solid var(--border,#e2e8f0);font-size:13px;">
        <span id="map-lead-count" style="font-weight:600">Laster…</span>
        <span style="color:#ccc">|</span>
        <label style="display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none">
          <input type="checkbox" id="map-show-anchors" checked>Vis kunder (ankere)
        </label>
        <label style="display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none">
          <input type="checkbox" id="map-use-filter" checked>Bruk tabellfilter
        </label>
        <span style="flex:1"></span>
        <div style="display:flex;gap:10px;align-items:center;font-size:11px;color:#555">
          <span><svg width="11" height="11"><circle cx="5.5" cy="5.5" r="5" fill="#16a34a"/></svg> ≥70</span>
          <span><svg width="11" height="11"><circle cx="5.5" cy="5.5" r="5" fill="#d97706"/></svg> 45–69</span>
          <span><svg width="11" height="11"><circle cx="5.5" cy="5.5" r="5" fill="#ea580c"/></svg> 20–44</span>
          <span><svg width="11" height="11"><circle cx="5.5" cy="5.5" r="5" fill="#dc2626"/></svg> &lt;20</span>
          <span><svg width="11" height="11"><rect x="1" y="1" width="9" height="9" fill="#2563eb" rx="1"
            transform="rotate(45 5.5 5.5)"/></svg> Anker</span>
        </div>
        <button id="map-reload-btn" style="padding:5px 12px;background:#5e5ce6;color:#fff;
          border:none;border-radius:7px;cursor:pointer;font-size:12px;font-weight:500">
          ↻ Oppdater
        </button>
      </div>
      <div id="leaflet-map" style="flex:1;min-height:300px"></div>`;

    document.getElementById('map-reload-btn').addEventListener('click', reload);
    document.getElementById('map-show-anchors').addEventListener('change', renderMarkers);
    document.getElementById('map-use-filter').addEventListener('change', e => {
      useTableFilter = e.target.checked;
      reload();
    });
  }

  // ── Popup: lead ───────────────────────────────────────────────
  function leadPopup(lead) {
    const c = scoreColor(lead.score);
    const dist = lead.geoscore != null && lead.geoscore < 40_000_000
      ? `📏 ${(lead.geoscore / 1000).toFixed(1)} km fra anker` : '';
    const sigs = lead.signals.length
      ? lead.signals.slice(0, 4).map(s => s.replace(/_/g, ' ')).join(' · ')
        + (lead.signals.length > 4 ? ` +${lead.signals.length - 4}` : '') : '';
    return `<div style="min-width:230px;font-family:system-ui,sans-serif;line-height:1.5">
      <div style="font-weight:700;font-size:15px;margin-bottom:5px">${lead.navn}</div>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:7px">
        <span style="background:${c};color:#fff;font-weight:700;font-size:14px;
          padding:2px 10px;border-radius:99px">${lead.score}</span>
        <span style="font-size:13px">${statusEmoji(lead.status)}</span>
      </div>
      ${lead.kommune ? `<div style="font-size:12px;color:#555;margin-bottom:2px">📍 ${lead.kommune}</div>` : ''}
      ${lead.antallAnsatte ? `<div style="font-size:12px;color:#555;margin-bottom:2px">👥 ${lead.antallAnsatte} ansatte</div>` : ''}
      ${dist ? `<div style="font-size:12px;color:#555;margin-bottom:2px">${dist}</div>` : ''}
      ${sigs ? `<div style="font-size:11px;color:#888;margin-bottom:8px">🔔 ${sigs}</div>` : ''}
      <div style="display:flex;gap:5px;flex-wrap:wrap">
        <a href="https://w2.brreg.no/enhet/oppslag/detaljer.jsp?orgnr=${lead.orgnr}" target="_blank" rel="noopener"
           style="font-size:11px;padding:4px 9px;background:#f1f5f9;border-radius:5px;
                  text-decoration:none;color:#334155;border:1px solid #e2e8f0">Brreg</a>
        <a href="https://www.proff.no/selskap/-/-/-/${lead.orgnr}/" target="_blank" rel="noopener"
           style="font-size:11px;padding:4px 9px;background:#f1f5f9;border-radius:5px;
                  text-decoration:none;color:#334155;border:1px solid #e2e8f0">Proff</a>
        <a href="https://www.linkedin.com/search/results/companies/?keywords=${encodeURIComponent(lead.navn)}"
           target="_blank" rel="noopener"
           style="font-size:11px;padding:4px 9px;background:#f1f5f9;border-radius:5px;
                  text-decoration:none;color:#334155;border:1px solid #e2e8f0">LinkedIn</a>
      </div></div>`;
  }

  // ── Markører ──────────────────────────────────────────────────
  function makeLeadMarker(lead) {
    const c = scoreColor(lead.score);
    const r = Math.max(6, Math.min(18, 6 + lead.score / 8));
    const m = L.circleMarker([lead.lat, lead.lon],
      { radius: r, fillColor: c, color: '#fff', weight: 1.5, fillOpacity: 0.88 });
    m.bindPopup(leadPopup(lead), { maxWidth: 310 });
    return m;
  }

  function makeAnchorMarker(anchor) {
    const icon = L.divIcon({
      html: `<div style="width:14px;height:14px;background:#2563eb;border:2.5px solid #fff;
        border-radius:3px;transform:rotate(45deg);box-shadow:0 2px 5px rgba(0,0,0,.35)"></div>`,
      iconSize: [18, 18], iconAnchor: [9, 9], className: '',
    });
    const m = L.marker([anchor.lat, anchor.lon], { icon, zIndexOffset: -100 });
    m.bindPopup(`<div style="font-family:system-ui,sans-serif">
      <div style="font-weight:700;font-size:14px;margin-bottom:3px">🏢 ${anchor.navn}</div>
      <div style="font-size:11px;color:#666">Anker (eksisterende kunde)</div>
      ${anchor.adresse ? `<div style="font-size:11px;color:#888;margin-top:4px">${anchor.adresse}</div>` : ''}
    </div>`);
    return m;
  }

  // ── Render alle markører ──────────────────────────────────────
  function renderMarkers() {
    if (!map) return;
    markerLayer.clearLayers();
    anchorLayer.clearLayers();
    allLeads.forEach(lead => markerLayer.addLayer(makeLeadMarker(lead)));
    if (document.getElementById('map-show-anchors')?.checked)
      allAnchors.forEach(a => anchorLayer.addLayer(makeAnchorMarker(a)));
    const el = document.getElementById('map-lead-count');
    if (el) el.textContent = `${allLeads.length} leads på kart`;
  }

  // ── Hent data — fra filtrert tabell eller API ─────────────────
  async function reload() {
    const btn = document.getElementById('map-reload-btn');
    if (btn) { btn.textContent = '⏳'; btn.disabled = true; }
    try {
      if (useTableFilter && typeof window.getLeadsForMap === 'function') {
        // Bruk allerede-filtrerte leads fra tabellen (har geo_lat/geo_lon)
        const tableLeads = window.getLeadsForMap();
        allLeads = tableLeads
          .filter(l => l.geo_lat != null && l.geo_lon != null)
          .map(l => ({
            orgnr: String(l.orgnr || ''),
            navn: l.navn || '',
            score: Math.round((l.score || 0) * 10) / 10,
            lat: parseFloat(l.geo_lat),
            lon: parseFloat(l.geo_lon),
            antallAnsatte: l.antallAnsatte,
            kommune: l.forretningsadresse_kommune || l.kommunenavn || '',
            status: l.status || 'Ny',
            geo_tier: l.geo_tier || '',
            geoscore: l.geoscore,
            signals: (l.signals || []).map(s => s.type || s).filter(Boolean),
          }));
        // Ankere hentes fortsatt fra API (kunder er ikke i leads-state)
        if (!allAnchors.length) {
          const res = await fetch('/api/leads/map');
          if (res.ok) allAnchors = (await res.json()).anchors || [];
        }
      } else {
        // Hent alt fra API (ingen filter)
        const res = await fetch('/api/leads/map');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        allLeads = data.leads || [];
        allAnchors = data.anchors || [];
      }

      renderMarkers();
      if (allLeads.length > 0) {
        const pts = allLeads.map(l => [l.lat, l.lon]);
        allAnchors.forEach(a => pts.push([a.lat, a.lon]));
        map.fitBounds(L.latLngBounds(pts), { padding: [40, 40], maxZoom: 13 });
      }
    } catch (err) {
      console.error('[MapView]', err);
      const el = document.getElementById('map-lead-count');
      if (el) el.textContent = '⚠️ Klarte ikke laste kartdata';
    } finally {
      if (btn) { btn.textContent = '↻ Oppdater'; btn.disabled = false; }
    }
  }

  // ── Init kart ─────────────────────────────────────────────────
  async function init() {
    if (initialized) return;
    initialized = true;
    await loadLeaflet();
    buildUI();

    map = L.map('leaflet-map', { center: [64.5, 16.0], zoom: 5, preferCanvas: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> bidragsytere',
      maxZoom: 19,
    }).addTo(map);

    markerLayer = L.markerClusterGroup({
      maxClusterRadius: 55,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      iconCreateFunction(cluster) {
        const n = cluster.getChildCount();
        return L.divIcon({
          html: `<div style="background:#5e5ce6;color:#fff;font-weight:700;
            width:38px;height:38px;border-radius:50%;display:flex;align-items:center;
            justify-content:center;font-size:13px;border:2.5px solid #fff;
            box-shadow:0 2px 8px rgba(0,0,0,.3)">${n}</div>`,
          iconSize: [38, 38], iconAnchor: [19, 19], className: '',
        });
      },
    });
    markerLayer.addTo(map);
    anchorLayer = L.layerGroup().addTo(map);
    await reload();
  }

  // ── Offentlig API ─────────────────────────────────────────────
  function show() {
    const root = document.getElementById('view-map');
    if (root) { root.hidden = false; root.style.display = 'flex'; }
    if (!initialized) {
      init();
    } else {
      // Rekalkuér top i tilfelle viewport er resizet
      const navEl = document.querySelector('.main-tabs');
      if (navEl && root) {
        root.style.top = Math.round(navEl.getBoundingClientRect().bottom) + 'px';
      }
      setTimeout(() => map && map.invalidateSize(), 120);
    }
  }

  function hide() {
    const root = document.getElementById('view-map');
    if (root) { root.hidden = true; root.style.display = 'none'; }
  }

  return { init, show, hide, reload };
})();
