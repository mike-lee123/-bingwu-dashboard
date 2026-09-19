import argparse
import subprocess
import sys
from datetime import datetime

from phi_pi_kill_switch import evaluate_kill_switch
from phi_pi_hard_lock_status import compute_hard_lock_status, print_cli


# ==============================
# HELPERS
# ==============================
def run_step(cmd, title=None):
    if title:
        print(f"\n=== {title} ===\n")
    print("▶", " ".join(cmd), "\n")
    subprocess.run(cmd, check=True)


# ==============================
# PIPELINE
# ==============================
def run_pipeline(signal_date: str):
    print("===================================")
    print(" Phi–π Market Engine Daily Pipeline")
    print("===================================")
    print(f"Run time   : {datetime.now().isoformat()}")
    print(f"Signal date: {signal_date}")

    # --------------------------------------------------
    # STEP 0: HARD LOCK STATUS  (NEW)
    # --------------------------------------------------
    print("\n=== STEP 0: Hard Lock Status ===")
    hard_lock_status = compute_hard_lock_status()
    print_cli(hard_lock_status)

    hard_lock_active = hard_lock_status["hard_lock"]["active"]

    # --------------------------------------------------
    # STEP 1: Generate Signals
    # --------------------------------------------------
    run_step(
        [
            sys.executable,
            "batch_generate_phi_pi_clean.py",
            "--date",
            signal_date,
        ],
        title="STEP 1: Generate Signals",
    )

    run_step(
        [
            sys.executable,
            "build_phi_pi_option_signals.py",
            "--date",
            signal_date,
        ]
    )

    # --------------------------------------------------
    # STEP 2: Live Preview
    # --------------------------------------------------
    run_step(
        [
            sys.executable,
            "live_preview_phi_pi.py",
            "--signal-date",
            signal_date,
        ],
        title="STEP 2: Live Preview",
    )

    # --------------------------------------------------
    # STEP 3: Commit (SKIPPED if Hard Lock)
    # --------------------------------------------------
    if hard_lock_active:
        print("\n⏭️ Commit skipped due to HARD LOCK\n")
    else:
        run_step(
            [
                sys.executable,
                "commit_phi_pi_decision.py",
                "--signal-date",
                signal_date,
            ],
            title="STEP 3: Commit Decisions",
        )

    # --------------------------------------------------
    # STEP 4: Audit
    # --------------------------------------------------
    run_step(
        [
            sys.executable,
            "phi_pi_audit.py",
        ],
        title="STEP 4: Audit",
    )

    print("\n===================================")
    print(" PIPELINE COMPLETE")
    print("===================================\n")


# ==============================
# ENTRY
# ==============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-date", required=True)
    args = parser.parse_args()

    run_pipeline(args.signal_date)
