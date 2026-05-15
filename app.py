"""LeadMap — Flask entrypoint (index + blueprint-import)."""
import os

from flask import render_template

from state import app, import_xlsx_if_empty

import customers  # noqa: F401 — web_api blueprint
import analysis  # noqa: F401 — /api/analyze


@app.route("/")
def index():
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
