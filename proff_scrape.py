"""Proff.no scraping + Brreg-roller (sammensatt nøkkeltall-visning)."""
import re

import requests
from bs4 import BeautifulSoup

from brreg_api import HEADERS
from brreg_roles import fetch_brreg_roller


def fetch_proff_data(orgnr: str) -> dict:
    if not orgnr:
        return {}
    out = {"proff_url": f"https://www.proff.no/bransjes%C3%B8k?q={orgnr}"}
    roller_data = fetch_brreg_roller(orgnr)
    if "roller" in roller_data:
        out["roller"] = roller_data["roller"]
    elif "error" in roller_data:
        out["roller_error"] = roller_data["error"]

    proff_url = f"https://www.proff.no/selskap?orgnr={orgnr}"
    try:
        r = requests.get(proff_url, headers=HEADERS, timeout=8, allow_redirects=True)
        if r.status_code == 200 and r.text:
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text(" ", strip=True)
            for label, key in [
                ("Driftsinntekter", "driftsinntekter"),
                ("Driftsresultat", "driftsresultat"),
                ("Resultat før skatt", "resultat_for_skatt"),
                ("Sum egenkapital", "egenkapital"),
                ("Sum eiendeler", "eiendeler"),
            ]:
                m = re.search(rf"{re.escape(label)}\D{{0,15}}([\-\d\s.,]+)", text)
                if m:
                    out[key] = re.sub(r"\s+", " ", m.group(1).strip())[:50]
            out["proff_url"] = r.url
        else:
            out["proff_status"] = f"HTTP {r.status_code}"
    except Exception as e:
        out["proff_status"] = f"Kunne ikke hente: {str(e)[:80]}"
    return out
