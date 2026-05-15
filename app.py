"""LeadMap — Flask entrypoint (index + blueprint-import)."""
import os
from urllib.parse import quote

from flask import redirect, render_template, request

from state import app, import_xlsx_if_empty

import customers  # noqa: F401 — web_api blueprint
import analysis  # noqa: F401 — /api/analyze


@app.route("/")
def index():
    # Send uautentiserte brukere rett til /login-siden istedenfor å vise
    # leadmap-shellet med en modal oppå. Logget-inn brukere får appen som før.
    try:
        from blueprints.auth_routes import auth_relaxed_mode, get_current_user

        if not auth_relaxed_mode() and get_current_user() is None:
            invite = (request.args.get("invite") or "").strip()
            qs = f"?invite={quote(invite)}" if invite else ""
            return redirect(f"/login{qs}")
    except Exception:
        # Hvis auth-modulen ikke er klar (under boot) faller vi tilbake til index.
        pass
    return render_template("index.html")


if __name__ == "__main__":
    customers_dict = import_xlsx_if_empty()
    if customers_dict:
        print(f"[init] {len(customers_dict)} kunder lastet inn.")
    else:
        print("[init] Ingen kunder i data/ — bruk «Importer» i nettleseren for å laste opp et Excel/CSV-ark.")
    port = int(os.environ.get("LEADMAP_PORT") or os.environ.get("FLASK_RUN_PORT") or "5050")
    print(f"[init] Server starter på http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
