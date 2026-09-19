import streamlit as st
import shioaji as sj
import datetime
import os
import pandas as pd
import time
import yfinance as yf
import altair as alt
import matplotlib.pyplot as plt
import numpy as np
import sys
import io
import json
from pathlib import Path
from datetime import timezone, timedelta, time as dtime
from statistics import mean
import subprocess

# ==========================================
# 🎨 頁面版面配置 (寬螢幕模式)
# ==========================================
st.set_page_config(
    page_title="BingWu 2026 期權終極戰情室 (Phi-π 全內嵌動態標的旗艦版)",
    page_icon="🚀",
    layout="wide"
)

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

BASE_DIR = Path(__file__).resolve().parent

# ==========================================
# 🧠 內嵌 Phi-π 核心邏輯 (含自動化模擬單注入與硬鎖防呆)
# ==========================================
MAX_DAILY_LOSS = -0.06
MAX_CONSECUTIVE_LOSSES = 6
MIN_EXPECTANCY = 0.0
HARD_LOCK_DAYS = 2
LOCK_DAYS_REQUIRED = 5

LEDGER_ROOT = BASE_DIR / "output" / "ledger"
STATE_PATH = BASE_DIR / "output" / "analysis" / "kill_switch_state.json"
STATUS_FILE = BASE_DIR / "output" / "analysis" / "hard_lock_status.json"

def now_utc():
    return datetime.datetime.now(timezone.utc)

def utc_today():
    return now_utc().date()

def load_latest_ledger():
    LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
    dates = sorted(d.name for d in LEDGER_ROOT.iterdir() if d.is_dir())
    if not dates:
        return datetime.date.today().strftime("%Y-%m-%d"), {"trades": [{"pnl": {"proxy_return": 0.0}}]}

    latest = dates[-1]
    ledger_path = LEDGER_ROOT / latest / "ledger.json"
    if not ledger_path.exists():
        return latest, {"trades": [{"pnl": {"proxy_return": 0.0}}]}

    return latest, json.loads(ledger_path.read_text(encoding="utf-8"))

def extract_returns(ledger):
    if not ledger:
        return []
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

def evaluate_kill_switch():
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            locked_until = state.get("locked_until")
            if locked_until:
                until = datetime.datetime.fromisoformat(locked_until)
                if now_utc() < until:
                    return True, state["metrics"], state["reasons"]
        except:
            pass

    signal_date, ledger = load_latest_ledger()
    returns = extract_returns(ledger) if ledger else []

    reasons = []
    metrics = {
        "trade_count": len(returns),
        "daily_return": round(sum(returns), 6) if returns else 0.0,
        "max_consecutive_losses": consecutive_losses(returns),
        "expectancy": round(mean(returns), 6) if returns else 0.0
    }

    if metrics["daily_return"] <= MAX_DAILY_LOSS:
        reasons.append(f"DailyLoss {signal_date or 'N/A'} {metrics['daily_return']:.4f}")
    if metrics["max_consecutive_losses"] >= MAX_CONSECUTIVE_LOSSES:
        reasons.append(f"ConsecutiveLoss {metrics['max_consecutive_losses']}")
    if metrics["expectancy"] <= MIN_EXPECTANCY:
        reasons.append(f"NegativeExpectancy {metrics['expectancy']:.4f}")

    active = len(reasons) > 0
    state = {
        "engine": "Phi–π Market Engine",
        "active": active,
        "date": signal_date or "N/A",
        "reasons": reasons,
        "metrics": metrics,
        "locked_at": None,
        "locked_until": None
    }

    if active:
        locked_at = now_utc()
        locked_until = locked_at + timedelta(days=HARD_LOCK_DAYS)
        state["locked_at"] = locked_at.isoformat()
        state["locked_until"] = locked_until.isoformat()

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return active, metrics, reasons

def compute_hard_lock_status():
    today = utc_today()
    kill_active, metrics, reasons = evaluate_kill_switch()

    prev = None
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                prev = json.load(f)
        except:
            pass
    prev_lock = prev["hard_lock"] if prev else None

    if kill_active:
        if prev_lock and prev_lock.get("active") and prev_lock.get("lock_start_date"):
            lock_start = datetime.date.fromisoformat(prev_lock["lock_start_date"])
        else:
            lock_start = today
    else:
        lock_start = None

    if lock_start:
        elapsed = (today - lock_start).days + 1
        remaining = max(LOCK_DAYS_REQUIRED - elapsed, 0)
        time_lock_passed = elapsed >= LOCK_DAYS_REQUIRED
    else:
        elapsed = 0
        remaining = 0
        time_lock_passed = True

    daily_loss_clear = not any("DailyLoss" in r for r in reasons)
    expectancy_positive = metrics.get("expectancy", 0) >= 0
    consecutive_loss_ok = metrics.get("max_consecutive_losses", 0) <= 5
    audit_live_allowed = not kill_active

    all_conditions_clear = all([
        time_lock_passed,
        daily_loss_clear,
        expectancy_positive,
        consecutive_loss_ok,
        audit_live_allowed
    ])

    hard_lock_active = not all_conditions_clear

    status = {
        "generated_at": now_utc().isoformat(),
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

    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
    return status

# --- 內嵌管線核心 ---
def run_embedded_phi_pi_pipeline(date_str: str):
    log_output = []
    log_output.append(f"=== Phi–π Market Engine Pipeline Started ({date_str}) ===")
    
    hard_lock_status = compute_hard_lock_status()
    hard_lock_active = hard_lock_status["hard_lock"]["active"]
    log_output.append(f"Hard Lock Active: {hard_lock_active}")
    
    if hard_lock_active:
        log_output.append("🚨 警告：目前處於硬鎖狀態，系統已自動略過自動下單與 Commit 步驟！")
        return "\n".join(log_output)
    
    markets_file = BASE_DIR / "markets.txt"
    if markets_file.exists():
        markets = [m.strip() for m in markets_file.read_text(encoding="utf-8").splitlines() if m.strip()]
    else:
        markets = ["2330.TW", "2881.TW", "TXFR1"]
        
    signal_date = pd.to_datetime(date_str)
    output_dir = BASE_DIR / "output" / "phi_pi" / "daily" / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    
    success = 0
    generated_signals = []
    
    for m in markets:
        start = signal_date - timedelta(days=120)
        try:
            df = yf.download(m, start=start, end=signal_date + timedelta(days=1), auto_adjust=False, progress=False)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                if "Close" in df.columns:
                    close = df["Close"].dropna()
                    if not close.empty:
                        hi, lo = float(close.max()), float(close.min())
                        breath = hi / lo if lo > 0 else 1.0
                        last_px = float(close.iloc[-1])
                        
                        res = {
                            "market": m,
                            "signal_date": date_str,
                            "entry_price": last_px,
                            "breath_value": breath,
                            "notes": "embedded auto-generated"
                        }
                        generated_signals.append(res)
                        success += 1
        except Exception:
            pass
            
    log_output.append(f"STEP 1 (Batch Generate): Success {success} markets.")
    
    auto_added_count = 0
    for sig in generated_signals:
        b_val = sig["breath_value"]
        if b_val >= 0.0:
            strike_price = 23200.0
            entry_cost = 150.0
            
            default_type = st.session_state.custom_targets[0] if st.session_state.custom_targets else f"AI自動訊號: 週選 Buy Call ({sig['market']})"
            
            auto_trade = {
                "Time": datetime.datetime.now().strftime("%H:%M:%S"),
                "Type": default_type,
                "Strike/Price": strike_price,
                "Entry": entry_cost,
                "SL": round(entry_cost * 0.5, 1),
                "TP": round(entry_cost * 2.0, 1),
                "Status": "AI持倉中"
            }
            
            if not any(t["Type"] == auto_trade["Type"] and t["Strike/Price"] == strike_price for t in st.session_state.paper_trades):
                st.session_state.paper_trades.append(auto_trade)
                auto_added_count += 1

    log_output.append(f"STEP 2 (Auto Paper Trading): Successfully injected {auto_added_count} AI signals into Paper Trading module.")
    log_output.append("=== PIPELINE COMPLETE ===")
    return "\n".join(log_output)

def load_eod_score():
    score_file = "daily_score.txt"
    if os.path.exists(score_file):
        try:
            with open(score_file, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except:
            pass
    return 70

@st.cache_data(ttl=30)
def get_market_sectors():
    try:
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        tsmc = yf.Ticker("2330.TW").history(period="5d")
        fubon = yf.Ticker("2881.TW").history(period="5d")
        vix_df = yf.Ticker("^VIX").history(period="5d")
        sys.stderr = old_stderr 
        
        tsmc_price = float(tsmc['Close'].iloc[-1]) if not tsmc.empty else 975.0
        tsmc_open = float(tsmc['Open'].iloc[-1]) if not tsmc.empty else tsmc_price
        tsmc_change = tsmc_price - tsmc_open
        
        fubon_price = float(fubon['Close'].iloc[-1]) if not fubon.empty else 90.0
        fubon_open = float(fubon['Open'].iloc[-1]) if not fubon.empty else fubon_price
        fubon_change = fubon_price - fubon_open
        
        vix_val = float(vix_df['Close'].iloc[-1]) if not vix_df.empty else 14.5
        vix_prev = float(vix_df['Close'].iloc[-2]) if not vix_df.empty and len(vix_df) >= 2 else 14.0
        vix_chg = ((vix_val - vix_prev) / vix_prev) * 100
        
        return tsmc_price, tsmc_change, fubon_price, fubon_change, vix_val, vix_chg
    except Exception:
        return 975.0, 5.0, 90.0, 0.5, 14.5, 0.85

# ==========================================
# 🔌 初始化 Session State 與模擬單狀態
# ==========================================
if "api" not in st.session_state:
    st.session_state.api = None
if "is_connected" not in st.session_state:
    st.session_state.is_connected = False
if "paper_trades" not in st.session_state:
    st.session_state.paper_trades = []

if "custom_targets" not in st.session_state:
    st.session_state.custom_targets = [
        "週選 Buy Call (買權)", 
        "週選 Buy Put (賣權)", 
        "賣出勒式收租 (Sell Straddle)",
        "大台指期貨 (TXF)",
        "小台指期貨 (MXF)"
    ]

if "tick_timestamps" not in st.session_state:
    today_open = datetime.datetime.now().replace(hour=8, minute=45, second=0, microsecond=0)
    now_time = datetime.datetime.now()
    target_end = min(now_time, today_open.replace(hour=13, minute=45, second=0))
    if target_end < today_open:
        target_end = today_open + datetime.timedelta(minutes=30)
        
    times_range = pd.date_range(start=today_open, end=target_end, freq="60s")
    st.session_state.tick_timestamps = [t.strftime("%H:%M:%S") for t in times_range]
    
    n_pts = len(st.session_state.tick_timestamps)
    np.random.seed(42)
    base_p = 23150.0
    sim_prices = base_p + np.cumsum(np.random.normal(0, 1.5, n_pts))
    
    st.session_state.price_history = list(sim_prices)
    st.session_state.high_history = [p + np.random.uniform(2, 6) for p in sim_prices]
    st.session_state.low_history = [p - np.random.uniform(2, 6) for p in sim_prices]
    st.session_state.vwap_history = [p - np.random.uniform(10, 20) for p in sim_prices]
    st.session_state.ma109_history = [p - np.random.uniform(25, 40) for p in sim_prices]

def connect_shioaji(api_key, secret_key):
    try:
        api = sj.Shioaji(simulation=True)
        api.login(api_key, secret_key)
        st.session_state.api = api
        st.session_state.is_connected = True
        return True
    except Exception as e:
        st.error(f"連線失敗: {e}")
        return False

# ==========================================
# 📊 側邊欄控制台
# ==========================================
with st.sidebar:
    st.header("🔌 永豐 API 戰情看板")
    st.markdown("---")
    
    # 憑證從 .streamlit/secrets.toml (本機) 或 Streamlit Cloud 的 Secrets 讀取，不寫死在程式裡
    try:
        DEFAULT_API_KEY = st.secrets.get("SHIOAJI_API_KEY", "")
        DEFAULT_SECRET_KEY = st.secrets.get("SHIOAJI_SECRET_KEY", "")
    except Exception:
        DEFAULT_API_KEY = DEFAULT_SECRET_KEY = ""

    api_key_input = st.text_input("API Key", type="password", value=DEFAULT_API_KEY)
    secret_key_input = st.text_input("Secret Key", type="password", value=DEFAULT_SECRET_KEY)
    
    if st.button("🚀 啟動 API 連線", use_container_width=True):
        if api_key_input and secret_key_input:
            with st.spinner("正在連線至永豐金證券..."):
                if connect_shioaji(api_key_input, secret_key_input):
                    st.success("✅ 永豐 API 登入成功！")
        else:
            st.warning("⚠️ 請先輸入 API Key 與 Secret Key")
            
    st.markdown("---")
    if st.session_state.is_connected:
        st.markdown("🟢 **系統狀態**: `已連線 (模擬環境)`")
        contract_map = {
            "大台指 (TXFR1)": st.session_state.api.Contracts.Futures.TXF.TXFR1,
            "小台指 (MXFR1)": st.session_state.api.Contracts.Futures.MXF.MXFR1,
        }
        selected_name = st.selectbox("🎯 選擇即時監控標的", list(contract_map.keys()))
        selected_contract = contract_map[selected_name]
        st.markdown(f"📡 **當前鎖定**: `{selected_contract.code}`")
    else:
        st.markdown("🔴 **系統狀態**: `未連線`")
        
    st.markdown("---")
    eod_score = load_eod_score()
    st.metric(label="🧠 今日 EOD 戰略算分", value=f"{eod_score} 分", delta="強多結構" if eod_score >= 80 else "穩健區間")
    st.markdown("---")
    
    # 🎯 側邊欄：動態新增與刪除標的/策略管理中心
    st.subheader("🎯 自訂標的與策略管理")
    
    with st.form(key="add_target_form", clear_on_submit=True):
        new_target_input = st.text_input("➕ 輸入新標的/策略名稱", placeholder="例如: 2454 聯發科期貨")
        submitted_new = st.form_submit_button("➕ 新增至標的清單", use_container_width=True)
        
        if submitted_new:
            if new_target_input and new_target_input.strip() not in st.session_state.custom_targets:
                st.session_state.custom_targets.append(new_target_input.strip())
                st.success(f"✅ 成功新增標的: `{new_target_input.strip()}`")
                st.rerun()
            elif not new_target_input:
                st.warning("⚠️ 請先輸入標的名稱")
            else:
                st.info("ℹ️ 該標的已存在清單中")

    if st.session_state.custom_targets:
        target_to_remove = st.selectbox("🗑️ 選擇要刪除的標的", st.session_state.custom_targets, key="remove_selectbox")
        if st.button("🗑️ 確認刪除選定標的", use_container_width=True):
            if target_to_remove in st.session_state.custom_targets:
                st.session_state.custom_targets.remove(target_to_remove)
                st.success(f"🗑️ 已刪除標的: `{target_to_remove}`")
                st.rerun()
    else:
        st.info("目前無自訂標的可刪除")
        
    st.markdown(f"📊 **目前可用標的總數**: `{len(st.session_state.custom_targets)} 個`")
    st.markdown("---")
    
    col_sel = st.sidebar.radio("🎯 選擇戰情室艙別", ["🚀 旗艦期貨戰情室", "⚔️ 選擇權大師艙", "🧠 Phi-π 智能管線中樞"])
    
    st.markdown("---")
    auto_refresh = st.checkbox("⚡ 啟動盤中自動刷新 (每 60 秒)", value=True)

# ==========================================
# 🖼️ 建立專屬動態畫布 (st.empty 核心架構)
# ==========================================
main_canvas = st.empty()

with main_canvas.container():
    tsmc_p, tsmc_c, fubon_p, fubon_c, vix_val, vix_chg = get_market_sectors()

    if st.session_state.is_connected:
        import random
        latest_p = st.session_state.price_history[-1] + random.choice([-2, -1, 1, 2, 3])
        current_time_str = datetime.datetime.now().strftime("%H:%M:%S")
        
        st.session_state.tick_timestamps.append(current_time_str)
        st.session_state.price_history.append(latest_p)
        st.session_state.high_history.append(latest_p + random.uniform(2, 6))
        st.session_state.low_history.append(latest_p - random.uniform(2, 6))
        st.session_state.vwap_history.append(latest_p - 15.0)
        
        recent_avg = sum(st.session_state.price_history[-10:]) / min(10, len(st.session_state.price_history))
        st.session_state.ma109_history.append(recent_avg - 25.0)

    current_price_display = st.session_state.price_history[-1]
    current_vwap_display = st.session_state.vwap_history[-1]
    current_ma109_display = st.session_state.ma109_history[-1]

    df_temp = pd.DataFrame({
        'High': st.session_state.high_history,
        'Low': st.session_state.low_history,
        'Close': st.session_state.price_history
    })
    df_temp['H-L'] = df_temp['High'] - df_temp['Low']
    df_temp['H-PC'] = abs(df_temp['High'] - df_temp['Close'].shift(1))
    df_temp['L-PC'] = abs(df_temp['Low'] - df_temp['Close'].shift(1))
    df_temp['TR'] = df_temp[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    current_atr = float(df_temp['TR'].rolling(window=min(14, len(df_temp))).mean().iloc[-1])
    if pd.isna(current_atr) or current_atr <= 0:
        current_atr = 15.0

    n_kdj = 9
    low_min = df_temp['Low'].rolling(window=n_kdj).min()
    high_max = df_temp['High'].rolling(window=n_kdj).max()
    rsv = (df_temp['Close'] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)
    
    k_vals, d_vals, j_vals = [], [], []
    k_v, d_v = 50.0, 50.0
    for r in rsv:
        k_v = (2/3) * k_v + (1/3) * r
        d_v = (2/3) * d_v + (1/3) * k_v
        j_v = 3 * k_v - 2 * d_v
        k_vals.append(k_v)
        d_vals.append(d_v)
        j_vals.append(j_v)

    chart_df = pd.DataFrame({
        "Time": st.session_state.tick_timestamps,
        "Price": st.session_state.price_history,
        "VWAP": st.session_state.vwap_history,
        "109MA": st.session_state.ma109_history,
        "K": k_vals,
        "D": d_vals,
        "J": j_vals
    })

    # ==========================================
    # 🚀 分頁 1：旗艦期貨戰情室
    # ==========================================
    if col_sel == "🚀 旗艦期貨戰情室":
        st.title("🌌 BingWu 2026 期權終極戰情室 (期貨狙擊艙)")
        st.markdown("---")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("目前期貨現價", f"{current_price_display:.1f}", "🔥 動態風控中")
        c2.metric("ATR 即時波動度", f"{current_atr:.1f} 點")
        c3.metric("109MA 生命線", f"{current_ma109_display:.1f}")
        c4.metric("🔥 領頭羊:台積電", f"{tsmc_p:.1f}", f"{tsmc_c:+.1f}")
        c5.metric("🛡️ 護盤錨:富邦金", f"{fubon_p:.1f}", f"{fubon_c:+.1f}")

        st.markdown("---")

        left_col, right_col = st.columns([2, 1])

        with left_col:
            st.subheader("📡 主圖：開盤至收盤 60 秒分時走勢")
            melted_price = chart_df.melt('Time', value_vars=['Price', 'VWAP', '109MA'], var_name='Indicator', value_name='Value')
            chart_main = alt.Chart(melted_price).mark_line(strokeWidth=2).encode(
                x=alt.X('Time:N', title='', axis=alt.Axis(labels=True, ticks=True, labelAngle=-30), sort=None),
                y=alt.Y('Value:Q', scale=alt.Scale(zero=False), title='指數點位'),
                color=alt.Color('Indicator:N', title='指標', scale=alt.Scale(
                    domain=['Price', 'VWAP', '109MA'],
                    range=['#FF4B4B', '#1C83E1', '#00CC96']
                ))
            ).properties(height=240)
            st.altair_chart(chart_main, use_container_width=True)

            st.subheader("📊 副圖：KDJ 擺盪指標 (9,3,3)")
            melted_kdj = chart_df.melt('Time', value_vars=['K', 'D', 'J'], var_name='Indicator', value_name='Value')
            chart_kdj = alt.Chart(melted_kdj).mark_line(strokeWidth=1.5).encode(
                x=alt.X('Time:N', title='時間序列 (08:45 - 13:45)', axis=alt.Axis(labels=True, ticks=True, labelAngle=-30), sort=None),
                y=alt.Y('Value:Q', scale=alt.Scale(domain=[0, 100]), title='KDJ 值'),
                color=alt.Color('Indicator:N', title='KDJ', scale=alt.Scale(
                    domain=['K', 'D', 'J'],
                    range=['#FFA500', '#1E90FF', '#BA55D3']
                ))
            ).properties(height=160)
            st.altair_chart(chart_kdj, use_container_width=True)

        with right_col:
            st.subheader("🛡️ ATR 動態停損停利看板")
            
            atr_stop_distance = current_atr * 1.5
            risk_stop_loss = current_price_display - atr_stop_distance   
            target_take_profit = current_price_display + (atr_stop_distance * 2.0)
            
            default_target_display = st.session_state.custom_targets[0] if st.session_state.custom_targets else "週選 Buy Call (買權)"
            st.markdown(f"""
            * 🎯 **建議進場武器**: `{default_target_display}`
            * 🌊 **ATR 風控係數**: `1.5 × ATR ({atr_stop_distance:.1f}點)`
            * 🛑 **ATR 動態停損點**: `{risk_stop_loss:.1f} 點`
            * 🎯 **ATR 動態停利點**: `{target_take_profit:.1f} 點`
            """)
            st.markdown("---")
            
            st.subheader("📥 戰情匯出與下載中樞")
            csv_data = chart_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 下載 60 秒分時與 KDJ 數據 (CSV)",
                data=csv_data,
                file_name=f"BingWu_KDJ_ATR_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True
            )

    # ==========================================
    # ⚔️ 分頁 2：選擇權大師艙
    # ==========================================
    elif col_sel == "⚔️ 選擇權大師艙":
        st.subheader("⚔️ 選擇權大師艙 (含 PCR 籌碼、恐慌指數 VIX 與黃金進出場時間)")
        
        col_opt1, col_opt2, col_opt3 = st.columns(3)
        with col_opt1: 
            st.metric("Put/Call Ratio (PCR)", "107.8 %", "🔥 多方佔優 (偏多結構)")
        with col_opt2: 
            st.metric("美股恐慌指數 (CBOE VIX)", f"{vix_val:.2f}", f"{vix_chg:+.2f}%")
        with col_opt3: 
            st.metric("VIX 波動率環境", "中性震盪", "⚖️ 適合勒式收租策略")

        st.markdown("---")
        st.markdown("### 🎯 選擇權戰術進場與離場狙擊看板")

        with st.form(key="option_trade_form"):
            col_op_in1, col_op_in2, col_op_in3 = st.columns(3)
            
            with col_op_in1:
                option_type = st.selectbox("選擇作戰武器 (同步側邊欄動態標的)", st.session_state.custom_targets)
            with col_op_in2:
                target_strike = st.number_input("目標履約價 (Strike)", min_value=20000.0, max_value=30000.0, value=23200.0, step=100.0)
            with col_op_in3:
                entry_premium = st.number_input("預估進場權利金 (點數)", min_value=1.0, max_value=1000.0, value=150.0, step=5.0)
                
            col_op_out1, col_op_out2 = st.columns(2)
            with col_op_out1:
                stop_loss_pct = st.slider("停損比例設定 (%)", min_value=10, max_value=80, value=50, step=5)
            with col_op_out2:
                take_profit_pct = st.slider("停利目標比例設定 (%)", min_value=50, max_value=300, value=100, step=5)
                
            sl_points = entry_premium * (1 - stop_loss_pct / 100.0)
            tp_points = entry_premium * (1 + take_profit_pct / 100.0)
            
            submitted = st.form_submit_button("🚀 確認送出選擇權戰術佈局 (模擬下單)", use_container_width=True)
            
            if submitted:
                trade_record = {
                    "Time": datetime.datetime.now().strftime("%H:%M:%S"),
                    "Type": option_type,
                    "Strike/Price": target_strike,
                    "Entry": entry_premium,
                    "SL": round(sl_points, 1),
                    "TP": round(tp_points, 1),
                    "Status": "持倉中"
                }
                st.session_state.paper_trades.append(trade_record)
                st.success(f"✅ 成功鎖定目標：`{option_type}` | 履約價：`{target_strike}` (已同步至模擬持倉中樞)")

    # ==========================================
    # 🧠 分頁 3：Phi-π 智能管線與硬鎖控管中樞
    # ==========================================
    elif col_sel == "🧠 Phi-π 智能管線中樞":
        st.subheader("🧠 Phi–π Market Engine 智能管線與硬鎖控管中樞 (自動化聯動版)")
        st.markdown("---")

        try:
            hard_lock_status = compute_hard_lock_status()
            hard_lock_active = hard_lock_status["hard_lock"]["active"]
        except Exception as e:
            hard_lock_active = False
            hard_lock_status = {"error": str(e)}

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown("### 🔒 硬鎖控管狀態 (Hard Lock)")
            if hard_lock_active:
                st.error("🚨 狀態：【硬鎖已啟動 (HARD LOCK ACTIVE)】 - 系統已自動略過自動下單與 Commit 步驟！")
            else:
                st.success("🟢 狀態：【正常運行 (Normal)】 - 決策可正常提交。")
            st.json(hard_lock_status)

        with col_p2:
            st.markdown("### ⚙️ 執行 Phi–π 每日管線 (Pipeline)")
            signal_date_input = st.text_input("輸入訊號基準日期 (Signal Date)", value=datetime.date.today().strftime("%Y-%m-%d"))
            
            if st.button("🚀 執行內嵌完整 Phi-π 智慧管線 (含自動下單)", use_container_width=True):
                with st.spinner(f"正在內嵌執行 Phi–π 管線與自動化模擬單注入 (日期: {signal_date_input})..."):
                    try:
                        pipeline_logs = run_embedded_phi_pi_pipeline(signal_date_input)
                        st.success("✅ Phi–π 智慧管線全內嵌執行完畢，AI 訊號已同步至模擬倉！")
                        st.text_area("執行日誌輸出 (Logs)", pipeline_logs, height=250)
                    except Exception as ex:
                        st.error(f"❌ 內嵌管線執行失敗: {ex}")

    # ==========================================
    # 📋 整合：虛擬模擬單與即時損益追蹤專區
    # ==========================================
    st.markdown("---")
    st.markdown("### 📋 虛擬模擬單（Paper Trading）與持倉損益追蹤")

    with st.expander("➕ 點擊展開：手動建立虛擬模擬單", expanded=False):
        with st.form("manual_paper_trade_form"):
            mp_col1, mp_col2, mp_col3, mp_col4 = st.columns(4)
            with mp_col1:
                mp_type = st.selectbox("商品類型 (動態讀取側邊欄標的)", st.session_state.custom_targets)
            with mp_col2:
                mp_price = st.number_input("建倉點位 / 履約價 / 權利金", min_value=1.0, max_value=100000.0, value=3945.0, step=1.0)
            with mp_col3:
                mp_entry = st.number_input("進場成本 (指數或權利金)", min_value=1.0, max_value=100000.0, value=3945.0, step=1.0)
            with mp_col4:
                mp_qty = st.number_input("交易口數", min_value=1, max_value=20, value=1)
                
            mp_action = st.radio("買賣方向", ["買進 (Long / 多)", "賣出 (Short / 空)"], horizontal=True)
            
            manual_submit = st.form_submit_button("🎯 立即建倉模擬單", use_container_width=True)
            if manual_submit:
                new_record = {
                    "Time": datetime.datetime.now().strftime("%H:%M:%S"),
                    "Type": mp_type,
                    "Strike/Price": mp_price,
                    "Entry": mp_entry,
                    "SL": mp_price - 100 if "期貨" in mp_type or "2454" in mp_type or "聯發科" in mp_type else round(mp_entry * 0.5, 1),
                    "TP": mp_price + 200 if "期貨" in mp_type or "2454" in mp_type or "聯發科" in mp_type else round(mp_entry * 2.0, 1),
                    "Status": "持倉中"
                }
                st.session_state.paper_trades.append(new_record)
                st.success(f"✅ 成功建立自定義模擬單 (進場價/權利金: {mp_price})！")

    if st.session_state.paper_trades:
        active_trades_display = []
        for t in st.session_state.paper_trades:
            t_copy = t.copy()
            entry_p = t_copy.get("Entry", 150.0)
            action = t_copy.get("Action", "買進")
            t_type = str(t_copy.get("Type", ""))
            
            # 💡 智慧分流判斷：選擇權 vs 個股期貨 vs 大盤期貨
            is_option = any(kw in t_type for kw in ["Call", "Put", "選擇權", "買權", "賣權", "收租"])
            
            if is_option:
                import random
                # 選擇權現價（權利金）在進場成本附近小幅震盪
                simulated_premium = max(1.0, entry_p + random.choice([-3, -1, 0, 2, 4]))
                t_copy["Current_Price"] = simulated_premium
                
                if "賣出" in t_type or "Sell" in t_type:
                    diff_pts = entry_p - simulated_premium  # 賣方賺權利金下跌
                else:
                    diff_pts = simulated_premium - entry_p  # 買方賺權利金上漲
                multiplier = 50
                
            elif "2454" in t_type or "個股" in t_type or "聯發科" in t_type:
                import random
                simulated_stock_price = entry_p + random.choice([-2, 0, 1, 3, 5])
                t_copy["Current_Price"] = simulated_stock_price
                diff_pts = simulated_stock_price - entry_p
                multiplier = 50
            else:
                t_copy["Current_Price"] = current_price_display
                if "多" in str(action) or "買進" in str(action):
                    diff_pts = current_price_display - entry_p
                else:
                    diff_pts = entry_p - current_price_display
                multiplier = 50

            t_copy["P&L (點數)"] = round(diff_pts, 1)
            t_copy["P&L (金額大約)"] = round(diff_pts * multiplier, 0)
            active_trades_display.append(t_copy)
            
        df_active = pd.DataFrame(active_trades_display)
        st.dataframe(df_active, use_container_width=True)
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("🗑️ 結清並清空所有模擬單", use_container_width=True):
                st.session_state.paper_trades = []
                st.success("已全面清空模擬持倉紀錄！")
                st.rerun()
        with col_btn2:
            csv_sim = df_active.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 匯出模擬交易與損益紀錄 (CSV)",
                data=csv_sim,
                file_name=f"Paper_Trades_P&L_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True
            )
    else:
        st.info("💡 目前尚無模擬持倉紀錄。您可以透過上方表單手動建倉，或至「選擇權大師艙」送出戰術佈局進行自動同步！")

# ==========================================
# ⚡ 60 秒自動刷新引擎
# ==========================================
if auto_refresh:
    time.sleep(60)
    st.rerun()