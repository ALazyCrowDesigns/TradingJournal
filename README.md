# TradingJournal

Personal TraderSync-style trading journal with a fast Windows GUI, modern Python stack, and modular architecture.

## Features

- Import TraderSync-like CSVs
- Persist trades to SQLite (WAL) via SQLAlchemy 2.0 (typed ORM)
- Backfill daily OHLCV (Polygon) and previous day's close
- Store float per symbol from provided CSV
- Windows GUI using PySide6 (QTableView + custom model) with sorting
- Clean, swappable services and fast batch I/O

## Setup

1. Create and activate virtual environment:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:
```powershell
pip install -e ".[dev]"
```

3. Setup pre-commit hooks:
```powershell
pre-commit install
```

4. Configure environment:
```powershell
copy .env.example .env
# Edit .env and set your API keys
```

5. Run tests:
```powershell
pytest -q
```

6. Launch GUI:
```powershell
python app.py
```

## Project Structure

```
src/journal/
  __init__.py
  config.py
  db/
    __init__.py
    models.py
    dao.py
  ingest/
    tradersync.py
  services/
    __init__.py
    market.py
    fundamentals.py
    floatmap.py
    backfill.py
  ui/
    __init__.py
    main_window.py
    trades_model.py
tests/
  test_smoke.py
app.py
```
