"""Bygg og les indeksert SQLite fra aksjeeierbok-CSV (2024).

Kun rader der «Fødselsår/orgnr» er nøyaktig ni siffer (juridisk aksjonær) lagres,
så databasen blir mindre og oppslag per selskap holder seg raske.

Bygg (én gang etter ny CSV):
  python aksjeeierbok_sqlite.py
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from paths import AKSJEBOK_CSV_2024, AKSJEBOK_DB_2024

# Standard csv.field_size_limit er 128 KiB; aksjeeierbok har sporadisk veldig lange felt.
try:
    csv.field_size_limit(min(2**31 - 1, sys.maxsize))
except OverflowError:
    csv.field_size_limit(50 * 1024 * 1024)


def _norm_orgnr(raw: str) -> str:
    s = (raw or "").strip().replace(" ", "")
    return s if len(s) == 9 and s.isdigit() else ""


def _parse_int(raw: str) -> int:
    try:
        return int((raw or "").strip().replace(" ", ""))
    except ValueError:
        return 0


def _csv_rows(path: Path) -> Iterator[Tuple[str, str, str, str, str, int, int]]:
    """Én rad per CSV-linje: selskap_orgnr, navn, klasse, aksjonaer_orgnr, aksjonaer_navn, aksjer, tot."""
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        r = csv.reader(f, delimiter=";")
        next(r, None)  # header
        for row in r:
            if len(row) < 9:
                continue
            ao = _norm_orgnr(row[4])
            if not ao:
                continue
            yield (
                row[0].strip(),
                row[1].strip(),
                row[2].strip(),
                ao,
                row[3].strip(),
                _parse_int(row[7]),
                _parse_int(row[8]),
            )


def build_from_csv(
    csv_path: Path = AKSJEBOK_CSV_2024,
    db_path: Path = AKSJEBOK_DB_2024,
    tick: Optional[Callable[[], None]] = None,
) -> int:
    """Opprett/overskriv SQLite fra CSV. Returnerer antall innsatte rader."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"Mangler CSV: {csv_path}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.executescript(
            """
            CREATE TABLE aksjeeier_org (
              selskap_orgnr TEXT NOT NULL,
              selskap_navn TEXT,
              aksjeklasse TEXT,
              aksjonaer_orgnr TEXT NOT NULL,
              aksjonaer_navn TEXT,
              aksjer INTEGER NOT NULL,
              aksjer_selskap INTEGER NOT NULL
            );
            CREATE INDEX idx_aksjeeier_selskap ON aksjeeier_org(selskap_orgnr);
            CREATE INDEX idx_aksjeeier_aksjonaer ON aksjeeier_org(aksjonaer_orgnr);
            """
        )
        batch: List[Tuple[str, str, str, str, str, int, int]] = []
        inserted = 0
        batch_size = 8000
        sql = (
            "INSERT INTO aksjeeier_org "
            "(selskap_orgnr, selskap_navn, aksjeklasse, aksjonaer_orgnr, aksjonaer_navn, aksjer, aksjer_selskap) "
            "VALUES (?,?,?,?,?,?,?)"
        )
        for tup in _csv_rows(csv_path):
            batch.append(tup)
            if len(batch) >= batch_size:
                conn.executemany(sql, batch)
                inserted += len(batch)
                batch.clear()
                if tick:
                    tick()
        if batch:
            conn.executemany(sql, batch)
            inserted += len(batch)
        conn.commit()
        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()
    return inserted


def connect_readonly(db_path: Path = AKSJEBOK_DB_2024) -> Optional[sqlite3.Connection]:
    if not db_path.is_file():
        return None
    uri = db_path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def shareholder_hits_for_company(
    conn: sqlite3.Connection,
    selskap_orgnr: str,
    customer_orgnrs: frozenset,
) -> Dict[str, Dict[str, object]]:
    """Slå opp aksjonærer med org.nr for ett selskap; returner kun treff mot kundesett.

    Aggregerer flere aksjeklasser per aksjonær (sum aksjer).
    """
    lo = (selskap_orgnr or "").strip().replace(" ", "")
    if not lo or not customer_orgnrs:
        return {}
    cur = conn.execute(
        "SELECT aksjonaer_orgnr, aksjonaer_navn, aksjer, aksjer_selskap "
        "FROM aksjeeier_org WHERE selskap_orgnr = ?",
        (lo,),
    )
    agg: Dict[str, Dict[str, object]] = {}
    for ao, navn, aksjer, tot in cur:
        if ao not in customer_orgnrs:
            continue
        if ao not in agg:
            agg[ao] = {"navn": (navn or ao).strip(), "aksjer": 0, "tot": int(tot or 0)}
        agg[ao]["aksjer"] = int(agg[ao]["aksjer"]) + int(aksjer or 0)
        t0 = int(agg[ao]["tot"] or 0)
        t1 = int(tot or 0)
        agg[ao]["tot"] = max(t0, t1)
    return agg


def ownership_pct_in_company(
    conn: sqlite3.Connection,
    selskap_orgnr: str,
    aksjonaer_orgnr: str,
) -> Optional[float]:
    """Samlet eierandel i % for aksjonaer_orgnr i selskap_orgnr (alle aksjeklasser), eller None."""
    ao = (aksjonaer_orgnr or "").strip().replace(" ", "")
    so = (selskap_orgnr or "").strip().replace(" ", "")
    if not ao or not so:
        return None
    cur = conn.execute(
        "SELECT SUM(aksjer), MAX(aksjer_selskap) FROM aksjeeier_org "
        "WHERE selskap_orgnr = ? AND aksjonaer_orgnr = ?",
        (so, ao),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    ak, tot = int(row[0] or 0), int(row[1] or 0)
    if tot <= 0:
        return None
    return 100.0 * ak / float(tot)


def stakes_owned_by_orgnr(
    conn: sqlite3.Connection,
    aksjonaer_orgnr: str,
    min_pct: float = 5.0,
    limit: int = 250,
) -> List[Dict[str, object]]:
    """Selskap der aksjonaer_orgnr eier minst ``min_pct`` % ifølge aksjeeierbok-tabellen."""
    ao = (aksjonaer_orgnr or "").strip().replace(" ", "")
    if not ao or len(ao) != 9 or not ao.isdigit():
        return []
    thr = min_pct / 100.0
    cur = conn.execute(
        """
        SELECT selskap_orgnr, MAX(selskap_navn) AS navn, SUM(aksjer) AS ak, MAX(aksjer_selskap) AS tot
        FROM aksjeeier_org
        WHERE aksjonaer_orgnr = ?
        GROUP BY selskap_orgnr
        HAVING MAX(aksjer_selskap) > 0 AND (SUM(aksjer) * 1.0 / MAX(aksjer_selskap)) >= ?
        ORDER BY (SUM(aksjer) * 1.0 / MAX(aksjer_selskap)) DESC
        LIMIT ?
        """,
        (ao, thr, limit),
    )
    out: List[Dict[str, object]] = []
    for so, navn, ak, tot in cur:
        tot_i = int(tot or 0)
        ak_i = int(ak or 0)
        if tot_i <= 0:
            continue
        pct = 100.0 * ak_i / float(tot_i)
        out.append(
            {
                "orgnr": str(so).strip(),
                "navn": (navn or so or "").strip(),
                "pct": round(pct, 1),
                "aksjer": ak_i,
                "aksjer_selskap": tot_i,
            }
        )
    return out


def main(argv: List[str]) -> int:
    csv_p = Path(argv[1]).resolve() if len(argv) > 1 else AKSJEBOK_CSV_2024
    db_p = Path(argv[2]).resolve() if len(argv) > 2 else AKSJEBOK_DB_2024
    n = build_from_csv(csv_p, db_p)
    print(f"OK: {n} rader → {db_p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
