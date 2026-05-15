"""Samlet API-blueprint under /api (kunder, import, søk)."""
from flask import Blueprint

web_api = Blueprint("web_api", __name__, url_prefix="/api")
