import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

from phi_pi_kill_switch import evaluate_kill_switch

# ==============================
# CONFIG
# ==============================
LOCK_DAYS_REQUIRED = 7

OUTPUT_DIR = Path("output/analysis")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STATUS_FILE = OUTPUT_DIR / "hard_lock_status.json"


# ==============================
# HELPERS
# ==============================
def utc_today():
    return datetime.now(timezone.utc).date()


def load_existing_status():
    if STATUS_FILE.exists():
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_status(data):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ==============================
# CORE LOGIC
# ==============================
def compute_hard_lock_status():
    today = utc_today()

    # ---- Kill Switch ----
    kill_active, metrics, reasons = evaluate_kill_switch()

    # ---- Load previous lock (if any) ----
    prev = load_existing_status()
    prev_lock = prev["hard_lock"] if prev else None

    # ---- Determine lock start ----
    if kill_active:
        if prev_lock and prev_lock.get("active"):
            lock_start = datetime.fromisoformat(prev_lock["lock_start_date"]).date()
        else:
            lock_start = today
    else:
        lock_start = None

    # ---- Time lock calculation ----
    if lock_start:
        elapsed = (today - lock_start).days + 1
        remaining = max(LOCK_DAYS_REQUIRED - elapsed, 0)
        time_lock_passed = elapsed >= LOCK_DAYS_REQUIRED
    else:
        elapsed = 0
        remaining = 0
        time_lock_passed = True

    # ---- Conditions ----
    daily_loss_clear = not any("DailyLoss" in r for r in reasons)
    expectancy_positive = metrics.get("expectancy", 0) >= 0
    consecutive_loss_ok = metrics.get("max_consecutive_losses", 0) <= 5
    audit_live_allowed = not kill_active  # gate already encodes this

    all_conditions_clear = all([
        time_lock_passed,
        daily_loss_clear,
        expectancy_positive,
        consecutive_loss_ok,
        audit_live_allowed
    ])

    hard_lock_active = not all_conditions_clear

    # ---- Compose status ----
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hard_lock": {
            "active": hard_lock_active,
            "lock_start_date": lock_start.isoformat() if lock_start else None,
            "lock_days_required": LOCK_DAYS_REQUIRED,
            "lock_days_elapsed": elapsed,
            "lock_days_remaining": remaining
        },
        "conditions": {
            "time_lock_passed": time_lock_passed,
            "daily_loss_clear": daily_loss_clear,
            "expectancy_positive": expectancy_positive,
            "consecutive_loss_ok": consecutive_loss_ok,
            "audit_live_allowed": audit_live_allowed
        },
        "metrics_snapshot": {
            "daily_return": metrics.get("daily_return"),
            "expectancy": metrics.get("expectancy"),
            "max_consecutive_losses": metrics.get("max_consecutive_losses"),
            "trade_count": metrics.get("trade_count")
        },
        "unlock_ready": not hard_lock_active,
        "next_unlock_check_date": (
            (lock_start + timedelta(days=LOCK_DAYS_REQUIRED)).isoformat()
            if lock_start else today.isoformat()
        )
    }

    save_status(status)
    return status


# ==============================
# CLI DISPLAY
# ==============================
def print_cli(status):
    hl = status["hard_lock"]
    cond = status["conditions"]
    met = status["metrics_snapshot"]

    print("\n==============================")
    print(" HARD LOCK STATUS")
    print("==============================")
    print(f"Active            : {'YES' if hl['active'] else 'NO'}")
    print(f"Lock start date   : {hl['lock_start_date']}")
    print(f"Days elapsed      : {hl['lock_days_elapsed']} / {hl['lock_days_required']}")
    print(f"Days remaining    : {hl['lock_days_remaining']}")
    print("\n--- Conditions ---")
    print(f"Time lock passed  : {'✅' if cond['time_lock_passed'] else '❌'}")
    print(f"Daily loss clear  : {'✅' if cond['daily_loss_clear'] else '❌'}")
    print(f"Expectancy ≥ 0    : {'✅' if cond['expectancy_positive'] else '❌'} ({met.get('expectancy')})")
    print(f"Consecutive loss  : {'✅' if cond['consecutive_loss_ok'] else '❌'} ({met.get('max_consecutive_losses')})")
    print(f"Audit live gate   : {'✅' if cond['audit_live_allowed'] else '❌'}")
    print("\n➡ System is " + ("UNLOCKED" if status["unlock_ready"] else "LOCKED"))
    print(f"Next review date  : {status['next_unlock_check_date']}")
    print("==============================\n")


# ==============================
# ENTRY
# ==============================
if __name__ == "__main__":
    status = compute_hard_lock_status()
    print_cli(status)
