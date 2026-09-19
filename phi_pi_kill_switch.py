# phi_pi_kill_switch.py
# =====================
# Phi–π Market Engine — HARD Kill Switch with Multi-Day Lock
#
# Authority level: MAXIMUM
#

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from statistics import mean

# =====================
# CONFIG
# =====================

MAX_DAILY_LOSS = -0.02
MAX_CONSECUTIVE_LOSSES = 7
MIN_EXPECTANCY = -0.005

HARD_LOCK_DAYS = 7   # ✅ CONFIRMED

LEDGER_ROOT = Path("output/ledger")
STATE_PATH = Path("output/analysis/kill_switch_state.json")

# =====================
# UTIL
# =====================

def now_utc():
    return datetime.now(timezone.utc)

def load_latest_ledger():
    dates = sorted(d.name for d in LEDGER_ROOT.iterdir() if d.is_dir())
    if not dates:
        raise RuntimeError("No ledger found")

    latest = dates[-1]
    ledger_path = LEDGER_ROOT / latest / "ledger.json"
    if not ledger_path.exists():
        raise RuntimeError(f"ledger.json missing for {latest}")

    return latest, json.loads(ledger_path.read_text(encoding="utf-8"))

def extract_returns(ledger):
    returns = []
    for t in ledger.get("trades", []):
        r = t.get("pnl", {}).get("proxy_return")
        if isinstance(r, (int, float)):
            returns.append(r)
    return returns

def consecutive_losses(returns):
    streak = max_streak = 0
    for r in returns:
        if r < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak

def write_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")

# =====================
# CORE
# =====================

def evaluate_kill_switch():
    # ① 若已存在 Hard Lock，且尚未到期 → 無條件鎖死
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        locked_until = state.get("locked_until")
        if locked_until:
            until = datetime.fromisoformat(locked_until)
            if now_utc() < until:
                return True, state["metrics"], state["reasons"]

    # ② 正常重新評估
    signal_date, ledger = load_latest_ledger()
    returns = extract_returns(ledger)

    reasons = []
    metrics = {
        "trade_count": len(returns),
        "daily_return": round(sum(returns), 6) if returns else 0.0,
        "max_consecutive_losses": consecutive_losses(returns),
        "expectancy": round(mean(returns), 6) if returns else 0.0
    }

    if metrics["daily_return"] <= MAX_DAILY_LOSS:
        reasons.append(f"DailyLoss {signal_date} {metrics['daily_return']:.4f}")

    if metrics["max_consecutive_losses"] >= MAX_CONSECUTIVE_LOSSES:
        reasons.append(f"ConsecutiveLoss {metrics['max_consecutive_losses']}")

    if metrics["expectancy"] <= MIN_EXPECTANCY:
        reasons.append(f"NegativeExpectancy {metrics['expectancy']:.4f}")

    active = len(reasons) > 0

    state = {
        "engine": "Phi–π Market Engine",
        "active": active,
        "date": signal_date,
        "reasons": reasons,
        "metrics": metrics,
        "locked_at": None,
        "locked_until": None
    }

    # ③ 若首次觸發 → 啟動 Hard Lock
    if active:
        locked_at = now_utc()
        locked_until = locked_at + timedelta(days=HARD_LOCK_DAYS)

        state["locked_at"] = locked_at.isoformat()
        state["locked_until"] = locked_until.isoformat()

    write_state(state)
    return active, metrics, reasons

# =====================
# CLI
# =====================

def main():
    print("=== KILL SWITCH STATUS ===")
    active, metrics, reasons = evaluate_kill_switch()

    out = {
        "engine": "Phi–π Market Engine",
        "timestamp": now_utc().isoformat(),
        "kill_switch_active": active,
        "reasons": reasons,
        "metrics": metrics
    }

    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
