"""Registrerer web_api-blueprint (kunder, konsern, import, leads, innstillinger) og innlogging."""
from state import app
from blueprints.auth_routes import register_auth

register_auth(app)

from blueprints.web_api import web_api

import blueprints.customers_crud  # noqa: F401
import blueprints.customers_konsern  # noqa: F401
import blueprints.customers_importer  # noqa: F401
import blueprints.leads_routes  # noqa: F401
import blueprints.settings_routes  # noqa: F401
import blueprints.admin_routes  # noqa: F401

app.register_blueprint(web_api)
