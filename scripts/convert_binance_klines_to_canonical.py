from __future__ import annotations

import csv
import zipfile
from pathlib import Path
from datetime import datetime, timezone


SYMBOL = "BTCUSDT"
TIMEFRAME = "15m"

RAW_DIR = Path(f"data/raw/binance/{SYMBOL}/{TIMEFRAME}")
OUT_PATH = Path(f"data/historical/{SYMBOL}/{TIMEFRAME}/{SYMBOL}_{TIMEFRAME}.csv")

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

rows = []

for zip_path in sorted(RAW_DIR.glob("*.zip")):
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if not name.endswith(".csv"):
                continue

            with z.open(name) as f:
                decoded = (line.decode("utf-8").strip() for line in f)
                reader = csv.reader(decoded)

                for row in reader:
                    if not row:
                        continue

                    # Binance monthly kline CSV usually has:
                    # open_time, open, high, low, close, volume, close_time, ...
                    # open_time is usually milliseconds.
                    try:
                        open_time = int(row[0])
                    except ValueError:
                        # skip header if present
                        continue

                    timestamp = datetime.fromtimestamp(
                        open_time / 1000,
                        tz=timezone.utc,
                    ).isoformat().replace("+00:00", "Z")

                    rows.append({
                        "timestamp": timestamp,
                        "open": row[1],
                        "high": row[2],
                        "low": row[3],
                        "close": row[4],
                        "volume": row[5],
                    })

rows.sort(key=lambda r: r["timestamp"])

with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=["timestamp", "open", "high", "low", "close", "volume"],
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"Wrote {len(rows)} rows to {OUT_PATH}")