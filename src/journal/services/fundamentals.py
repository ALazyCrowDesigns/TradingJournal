from __future__ import annotations

import httpx

from ..config import settings
from ..db.dao import get_symbols_missing_fundamentals, update_symbols_fundamentals

FMP_BASE = "https://financialmodelingprep.com/api/v3/profile"


def _enabled() -> bool:
    return bool(settings.fmp_api_key)


def _fetch_profile(sym: str) -> dict | None:
    url = f"{FMP_BASE}/{sym}"
    r = httpx.get(url, params={"apikey": settings.fmp_api_key}, timeout=30)
    r.raise_for_status()
    arr = r.json() or []
    if not arr:
        return None
    it = arr[0]
    return {
        "symbol": sym,
        "name": it.get("companyName"),
        "sector": it.get("sector"),
        "industry": it.get("industry"),
    }


def hydrate_missing(limit: int | None = None) -> dict:
    if not _enabled():
        return {"skipped": True, "updated": 0, "reason": "no FMP_API_KEY"}

    symbols = get_symbols_missing_fundamentals(limit=limit)
    updated = 0
    for s in symbols:
        try:
            rec = _fetch_profile(s)
            if rec:
                update_symbols_fundamentals([rec])
                updated += 1
        except Exception:
            # continue on errors; could log if desired
            pass
    return {"skipped": False, "updated": updated}


# CLI
def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Hydrate fundamentals (name/sector/industry) from FMP")
    p.add_argument("--limit", type=int, default=None, help="Max symbols to hydrate")
    args = p.parse_args()

    out = hydrate_missing(limit=args.limit)
    print(out)


if __name__ == "__main__":
    main()
