// auth-ui.js — Google-innlogging, invitasjonslenke, brukerpanel, skjul knapper etter rettigheter.
(function () {
  const $ = (id) => document.getElementById(id);

  function applyPermissionUi(user) {
    const p = (user && user.permissions) || {};
    const hide = (id) => {
      const el = $(id);
      if (el) el.hidden = true;
    };
    const show = (id) => {
      const el = $(id);
      if (el) el.hidden = false;
    };
    if (!p.delete_customers) {
      hide("btn-delete-all");
      hide("btn-dedupe");
    } else {
      show("btn-delete-all");
      show("btn-dedupe");
    }
    if (!p.full_reanalyze) hide("btn-analyze-full");
    else show("btn-analyze-full");
    if (!p.add) {
      hide("btn-promote-whole-owned-leads");
    } else {
      show("btn-promote-whole-owned-leads");
    }
    const bulk = $("btn-bulk-delete-tab");
    if (bulk) bulk.hidden = !p.delete_customers;
    const adm = $("btn-auth-admin");
    if (adm) adm.hidden = !p.manage_users;
  }

  function setHdrAuth(user, relaxed) {
    const label = $("hdr-auth-label");
    const lo = $("btn-auth-logout");
    if (relaxed) {
      if (label) label.textContent = user ? `${user.name || user.email} (ingen OAuth)` : "";
      if (lo) lo.hidden = true;
      applyPermissionUi(
        user || {
          permissions: {
            add: true,
            full_reanalyze: true,
            delete_customers: true,
            manage_users: true,
          },
        },
      );
      return;
    }
    if (label) label.textContent = user ? `${user.name || ""} (${user.email})`.trim() : "";
    if (lo) lo.hidden = !user;
    applyPermissionUi(user);
  }

  function showAuthGate(msg, inviteToken, oauthOk, relaxed) {
    const ov = $("auth-gate-overlay");
    const m = $("auth-gate-msg");
    const hint = $("auth-gate-invite-hint");
    const btn = $("auth-gate-google-btn");
    const rel = $("auth-gate-relaxed");
    if (!ov) return;
    if (relaxed) {
      ov.hidden = true;
      return;
    }
    ov.hidden = false;
    if (m) m.textContent = msg || "Logg inn med Google for å bruke LeadMap.";
    if (hint) {
      hint.hidden = !inviteToken;
      hint.textContent = inviteToken
        ? "Du har en invitasjonslenke — etter innlogging kobles kontoen din automatisk."
        : "";
    }
    if (rel) rel.hidden = oauthOk;
    if (btn) {
      if (!oauthOk) {
        btn.hidden = true;
      } else {
        btn.hidden = false;
        const q = inviteToken ? `?invite=${encodeURIComponent(inviteToken)}` : "";
        btn.href = `/api/auth/google/start${q}`;
      }
    }
  }

  function hideAuthGate() {
    const ov = $("auth-gate-overlay");
    if (ov) ov.hidden = true;
  }

  function readInviteFromUrl() {
    try {
      const u = new URL(window.location.href);
      return (u.searchParams.get("invite") || "").trim();
    } catch (e) {
      return "";
    }
  }

  async function openAdminModal() {
    const modal = $("modal-admin-users");
    if (!modal) return;
    modal.hidden = false;
    const box = $("admin-users-body");
    if (box) box.textContent = "Laster…";
    try {
      const data = await fetchJSON("/api/admin/users");
      if (box) {
        box.innerHTML = (data.users || [])
          .map((u) => {
            const nm = String(u.name || "").replace(/</g, "&lt;");
            const em = String(u.email || "").replace(/</g, "&lt;");
            return (
              `<div class="admin-user-row" data-id="${u.id}"><b>${nm}</b> ` +
              `<span class="muted">${em}</span> · ${u.role} ` +
              `${u.active ? "" : "(deaktivert)"} · ` +
              `+kunde:${u.can_add_customers ? "ja" : "nei"} · full re-analyse:${u.can_full_reanalyze ? "ja" : "nei"} · ` +
              `slett:${u.can_delete_customers ? "ja" : "nei"} · admin:${u.can_manage_users ? "ja" : "nei"}` +
              (u.role === "owner"
                ? ""
                : ` <button type="button" class="small secondary admin-del-user" data-id="${u.id}">Fjern tilgang</button>`) +
              `</div>`
            );
          })
          .join("");
        box.querySelectorAll(".admin-del-user").forEach((b) => {
          b.addEventListener("click", async () => {
            const id = b.getAttribute("data-id");
            if (!id || !confirm("Fjerne tilgang for denne brukeren?")) return;
            await fetchJSON(`/api/admin/users/${id}`, { method: "DELETE" });
            await openAdminModal();
          });
        });
      }
    } catch (e) {
      if (box) box.textContent = String(e.message || e);
    }
  }

  async function createInvite() {
    const days = parseInt(($("admin-invite-days") && $("admin-invite-days").value) || "14", 10) || 14;
    const emailLock = ($("admin-invite-email") && $("admin-invite-email").value.trim()) || "";
    const canAdd = $("admin-invite-canadd") ? $("admin-invite-canadd").checked : true;
    const canFull = $("admin-invite-canfull") ? $("admin-invite-canfull").checked : false;
    const out = $("admin-invite-result");
    try {
      const data = await fetchJSON("/api/admin/invites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          days_valid: days,
          email_lock: emailLock || null,
          can_add_customers: canAdd,
          can_full_reanalyze: canFull,
        }),
      });
      if (out) {
        const safe = String(data.invite_url || "").replace(/"/g, "&quot;");
        out.innerHTML = `<label>Invitasjonslenke (kopier)</label><input type="text" readonly style="width:100%" value="${safe}">`;
      }
    } catch (e) {
      if (out) out.textContent = String(e.message || e);
    }
  }

  window.addEventListener("leadmap-auth-required", () => {
    showAuthGate("Økten utløp — logg inn på nytt.", readInviteFromUrl(), true, false);
  });

  document.addEventListener("DOMContentLoaded", async () => {
    const invite = readInviteFromUrl();
    try {
      const m = await fetchJSON("/api/auth/me");
      window.LEADMAP_AUTH = m;
      if (m.auth_relaxed) {
        hideAuthGate();
        setHdrAuth(m.user, true);
        return;
      }
      if (!m.authenticated) {
        setHdrAuth(null, false);
        showAuthGate(null, invite, m.oauth_configured, false);
        return;
      }
      hideAuthGate();
      setHdrAuth(m.user, false);
    } catch (e) {
      console.warn("[auth-ui]", e);
    }

    const lo = $("btn-auth-logout");
    if (lo) {
      lo.addEventListener("click", async () => {
        await fetchJSON("/api/auth/logout", { method: "POST" });
        window.location.reload();
      });
    }
    const ba = $("btn-auth-admin");
    if (ba) ba.addEventListener("click", () => openAdminModal());
    const bi = $("btn-admin-invite-create");
    if (bi) bi.addEventListener("click", () => createInvite());
    const params = new URLSearchParams(window.location.search);
    const err = params.get("auth_error");
    if (err) {
      showAuthGate(`Innlogging feilet: ${err}`, invite, true, false);
    }
  });
})();
