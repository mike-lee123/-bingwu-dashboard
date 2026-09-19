# -*- coding: utf-8 -*-

import json
import argparse
from pathlib import Path
from datetime import datetime, time

import pandas as pd
import yfinance as yf

BASE_DIR = Path(__file__).resolve().parent


# --------------------------------------------------
# Load signals
# --------------------------------------------------

def load_option_signals(signal_date: str):
    path = BASE_DIR / "output" / "option" / signal_date / "phi_pi_option_signals.json"
    if not path.exists():
        raise FileNotFoundError(f"Option signals not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("signals", [])


# --------------------------------------------------
# Fallback rules (code-level)
# --------------------------------------------------

def decide_weights(vol_state: str):
    """
    Vol × structure weights (fallback included)
    - high   -> fixed 重
    - normal -> delta 重
    - low/None -> 均分
    """
    if vol_state == "high":
        return {"atm": 0.10, "fixed": 0.80, "delta": 0.10}
    if vol_state == "normal":
        return {"atm": 0.20, "fixed": 0.30, "delta": 0.50}
    return {"atm": 0.33, "fixed": 0.33, "delta": 0.34}


def infer_vol_state_from_proxy(breath_proxy: float):
    """
    沒有 vol_state 時，用盤中 breath_proxy 推斷 (fallback)
    """
    if breath_proxy >= 1.05:
        return "high"
    if breath_proxy >= 1.02:
        return "normal"
    return "low"


# --------------------------------------------------
# yfinance normalization (MOST IMPORTANT PART)
# --------------------------------------------------

def normalize_yf_ohlc(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """
    統一 yfinance 回傳格式：
    1) MultiIndex columns -> 取出 ticker 那一層，展平成單層欄位
    2) 欄位名大小寫/空白 -> normalize
    3) 如果只有 Adj Close -> 補 Close
    4) 如果缺 Open/High/Low -> 用 Close 補（保命）
    """
    if df is None or df.empty:
        return df

    # --- Case A: MultiIndex columns (common with some yfinance versions)
    if isinstance(df.columns, pd.MultiIndex):
        # 常見結構：level0=OHLC, level1=ticker
        # 也可能反過來：level0=ticker, level1=OHLC
        lv0 = df.columns.get_level_values(0)
        lv1 = df.columns.get_level_values(1)

        if ticker in set(lv1):
            # ('Open','1605.TW') 形式
            df = df.xs(ticker, axis=1, level=1, drop_level=True)
        elif ticker in set(lv0):
            # ('1605.TW','Open') 形式
            df = df.xs(ticker, axis=1, level=0, drop_level=True)
        else:
            # 最後保命：直接取第一層當欄位名
            df.columns = [c[0] for c in df.columns]

    # --- normalize column names
    cols = [str(c).strip() for c in df.columns]
    df.columns = cols

    # 對大小寫做 normalize
    ren = {}
    for c in df.columns:
        lc = c.lower()
        if lc == "open":
            ren[c] = "Open"
        elif lc == "high":
            ren[c] = "High"
        elif lc == "low":
            ren[c] = "Low"
        elif lc == "close":
            ren[c] = "Close"
        elif lc in ("adj close", "adjclose", "adj_close"):
            ren[c] = "Adj Close"
        elif lc == "volume":
            ren[c] = "Volume"
    if ren:
        df = df.rename(columns=ren)

    # --- ensure Close exists
    if "Close" not in df.columns and "Adj Close" in df.columns:
        df["Close"] = df["Adj Close"]

    # --- ensure OHLC exists (intraday 有時只回 Close)
    if "Close" not in df.columns:
        raise ValueError(f"[{ticker}] No Close/Adj Close found in downloaded data")

    for k in ["Open", "High", "Low"]:
        if k not in df.columns:
            df[k] = df["Close"]

    # 保留必要欄位
    keep = ["Open", "High", "Low", "Close"]
    if "Volume" in df.columns:
        keep.append("Volume")

    df = df[keep]
    return df


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    signal_date = args.signal_date

    print("\n=== Phi–π Live Preview Mode ===")
    print(f"Signal date : {signal_date}")
    print("Window      : 09:30–10:30")

    signals = load_option_signals(signal_date)
    if not signals:
        print("⚠️ No signals found.")
        return

    # 台股 09:30–10:30 (Asia/Taipei) -> 轉 UTC 來對齊 yfinance intraday index
    d = pd.to_datetime(signal_date).date()

    window_start = pd.Timestamp.combine(d, time(9, 30)).tz_localize("Asia/Taipei").tz_convert("UTC")
    window_end   = pd.Timestamp.combine(d, time(10, 30)).tz_localize("Asia/Taipei").tz_convert("UTC")

    results = []

    for s in signals:
        market = s.get("market")
        breath_signal = s.get("breath_value", None)

        if not market or breath_signal is None:
            continue

        print(f"\n▶ {market}")

        try:
            raw = yf.download(
                market,
                period="5d",
                interval="5m",
                auto_adjust=False,
                group_by="column",   # 降低 MultiIndex 混亂，但仍需 normalize
                progress=False,
            )
        except Exception as e:
            print(f"❌ download error: {e}")
            continue

        if raw is None or raw.empty:
            print("❌ empty dataframe")
            continue

        try:
            df = normalize_yf_ohlc(raw, market)
        except Exception as e:
            print(f"❌ normalize error: {e}")
            continue

        # 這裡一定存在 Open/High/Low/Close
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        if df.empty:
            print("❌ all rows are NA after dropna")
            continue

        intraday = df.loc[(df.index >= window_start) & (df.index <= window_end)]
        if intraday.empty:
            print("❌ no data in 09:30–10:30 window")
            continue

        hi = float(intraday["High"].max())
        lo = float(intraday["Low"].min())
        open_px = float(intraday["Open"].iloc[0])
        close_px = float(intraday["Close"].iloc[-1])

        if lo <= 0 or open_px <= 0:
            print("❌ invalid price range")
            continue

        breath_proxy = hi / lo
        ret_proxy = (close_px - open_px) / open_px

        # vol_state：如果 signal 沒提供（Mode B/C 常見），用 proxy 推斷
        vol_state = s.get("vol_state")
        if vol_state is None:
            vol_state = infer_vol_state_from_proxy(breath_proxy)

        weights = decide_weights(vol_state)

        print(
            f"breath(signal)={float(breath_signal):.3f} | "
            f"breath(proxy)={breath_proxy:.3f} | "
            f"ret(proxy)={ret_proxy:.2%} | "
            f"vol={vol_state}"
        )
        print(f"weights={weights}")

        results.append({
            "market": market,
            "breath_signal": round(float(breath_signal), 6),
            "breath_proxy": round(float(breath_proxy), 6),
            "ret_proxy": round(float(ret_proxy), 6),
            "vol_state": vol_state,
            "weights": weights,
        })

    if not results:
        print("\n⚠️ No valid live preview results.")
        return

    output_dir = BASE_DIR / "output" / "live_preview" / signal_date
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "signal_date": signal_date,
        "window": "09:30-10:30",
        "generated_at": datetime.now().astimezone().isoformat(),
        "mode": "Mode C: Live Preview",
        "markets": results,
    }

    out_path = output_dir / "live_preview.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n✅ live_preview.json written → {out_path}")


if __name__ == "__main__":
    main()
