"""
京东监控控制面板
- 价格监控：手动开关，每5分钟检测
- 国补日报：每天北京时间 09:00 自动发送（面板打开即生效，无需手动启动）
- 各地区入口：开关控制是否在日报中包含31省市京东国补链接
"""
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path
import time
import datetime

BASE          = Path(__file__).parent
PRICE_SCRIPT  = str(BASE / "run_price_check.py")
REPORT_SCRIPT = str(BASE / "run_daily_report.py")
PYTHON        = sys.executable
PRICE_INTERVAL = 300        # 5分钟
REPORT_HOUR    = 9          # 北京时间 09:00
TZ_OFFSET      = datetime.timezone(datetime.timedelta(hours=8))  # UTC+8

# ── 工具：获取北京时间 ────────────────────────────────────
def now_bj():
    return datetime.datetime.now(TZ_OFFSET)

# ── 全局状态 ──────────────────────────────────────────────
_price_running  = False
_price_checking = False          # True = 子进程正在执行价格检测
_stop_price     = threading.Event()
_report_sent_date = [None]       # 记录今天是否已发过日报
# 各地区入口开关（True=日报包含31省链接，False=不含）
# 注意：这里只声明变量，实际 BooleanVar 在 root 创建后赋值
_province_var   = None

# ═══════════════════════════════════════════════════════════
# 价格监控线程（手动开关）
# ═══════════════════════════════════════════════════════════
def _price_loop():
    global _price_checking
    while not _stop_price.is_set():
        # 1. 执行价格检测
        _price_checking = True
        _run_script(PRICE_SCRIPT, "价格检测")
        _price_checking = False

        if _stop_price.is_set():
            break

        # 2. 检测完成后立即重置倒计时，再开始等待
        _next_price[0] = PRICE_INTERVAL
        for _ in range(PRICE_INTERVAL):
            if _stop_price.is_set():
                break
            time.sleep(1)

    log("🔴 价格监控已停止")
    root.after(0, _on_price_stopped)


def start_price():
    global _price_running
    if _price_running:
        return
    _price_running = True
    _stop_price.clear()
    _next_price[0] = PRICE_INTERVAL
    btn_toggle.config(text="⏹  停止监控", bg="#e74c3c",
                      activebackground="#c0392b", state="normal")
    lbl_price_status.config(text="价格监控：运行中 🟢", fg="#27ae60")
    log("🟢 价格监控已启动（每5分钟检测一次）")
    threading.Thread(target=_price_loop, daemon=True).start()


def stop_price():
    global _price_running
    if not _price_running:
        return
    _price_running = False
    _stop_price.set()
    btn_toggle.config(text="⏳ 停止中...", bg="#95a5a6", state="disabled")
    log("⏸ 正在停止价格监控...")


def _on_price_stopped():
    btn_toggle.config(text="▶  启动价格监控", bg="#27ae60",
                      activebackground="#1e8449", state="normal")
    lbl_price_status.config(text="价格监控：已停止 🔴", fg="#e74c3c")
    lbl_price_cd.config(text="")


def toggle_price():
    if _price_running:
        stop_price()
    else:
        start_price()


# ═══════════════════════════════════════════════════════════
# 国补日报线程（自动每天09:00，面板打开即生效）
# ═══════════════════════════════════════════════════════════
def _report_scheduler():
    """后台常驻线程：每30秒检查一次时间，到09:00发日报"""
    while True:
        bj = now_bj()
        today = bj.date()
        if (bj.hour == REPORT_HOUR and bj.minute == 0
                and _report_sent_date[0] != today):
            _report_sent_date[0] = today
            include = _province_var.get() if _province_var else True
            log(f"⏰ 北京时间 {REPORT_HOUR:02d}:00，自动发送国补日报"
                f"{'（含各地区入口）' if include else '（不含地区链接）'}...")
            _run_script(REPORT_SCRIPT, "国补日报",
                        extra_env={"REPORT_PROVINCE": "1" if include else "0"})
        time.sleep(30)   # 每30秒检查一次，精度足够


def send_report_manual():
    include = _province_var.get() if _province_var else True
    btn_report.config(state="disabled", text="⏳ 发送中...")
    log(f"📋 手动触发：正在抓取国补并发送日报"
        f"{'（含各地区入口）' if include else '（不含地区链接）'}...")

    def _run():
        _run_script(REPORT_SCRIPT, "国补日报",
                    extra_env={"REPORT_PROVINCE": "1" if include else "0"})
        root.after(0, lambda: btn_report.config(
            state="normal", text="📋 立即发送国补日报"))

    threading.Thread(target=_run, daemon=True).start()


# ═══════════════════════════════════════════════════════════
# 公共：运行子进程
# ═══════════════════════════════════════════════════════════
def _run_script(script, label, extra_env=None):
    # 合并当前进程环境变量 + 额外参数（extra_env 优先）
    env = {**os.environ, **(extra_env or {})}
    try:
        r = subprocess.run(
            [PYTHON, "-X", "utf8", script],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=str(BASE), timeout=240, env=env,
        )
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if not out:
            log(f"{label} 完成（无输出）")
        elif len(out) > 1200:
            log(out[:600] + "\n…（省略中间内容）…\n" + out[-600:])
        else:
            log(out)
    except subprocess.TimeoutExpired:
        log(f"⚠️ {label} 超时，跳过本次")
    except Exception as e:
        log(f"❌ {label} 异常: {e}")


# ═══════════════════════════════════════════════════════════
# 倒计时与状态更新（每秒刷新）
# ═══════════════════════════════════════════════════════════
_next_price = [PRICE_INTERVAL]

def _tick():
    # 价格倒计时：检测中显示"检测中..."，等待中显示倒计时
    if _price_running:
        if _price_checking:
            lbl_price_cd.config(text="检测中...")
        elif _next_price[0] > 0:
            _next_price[0] -= 1
            m, s = divmod(_next_price[0], 60)
            lbl_price_cd.config(text=f"下次：{m:02d}:{s:02d}")
        else:
            lbl_price_cd.config(text="即将检测...")
    else:
        lbl_price_cd.config(text="")

    # 日报下次时间
    bj = now_bj()
    nxt = bj.replace(hour=REPORT_HOUR, minute=0, second=0, microsecond=0)
    if bj >= nxt:
        nxt += datetime.timedelta(days=1)
    diff = int((nxt - bj).total_seconds())
    h, rem = divmod(diff, 3600)
    m2, s2 = divmod(rem, 60)
    lbl_report_cd.config(text=f"下次日报：{h:02d}h {m2:02d}m")

    # 当前北京时间
    lbl_clock.config(text=f"北京时间 {bj.strftime('%H:%M:%S')}")

    root.after(1000, _tick)


# ═══════════════════════════════════════════════════════════
# 日志
# ═══════════════════════════════════════════════════════════
def log(msg: str):
    def _do():
        txt.config(state="normal")
        ts = now_bj().strftime("%H:%M:%S")
        txt.insert("end", f"[{ts}] {msg}\n")
        txt.see("end")
        txt.config(state="disabled")
    root.after(0, _do)


# ═══════════════════════════════════════════════════════════
# 界面
# ═══════════════════════════════════════════════════════════
root = tk.Tk()
root.title("京东监控控制面板")
root.geometry("540x570")
root.resizable(False, False)
root.configure(bg="#f0f0f0")

# 在 root 创建后才能初始化 BooleanVar
_province_var = tk.BooleanVar(value=True)

fnt_title = tkfont.Font(family="微软雅黑", size=13, weight="bold")
fnt_mid   = tkfont.Font(family="微软雅黑", size=11)
fnt_small = tkfont.Font(family="微软雅黑", size=9)
fnt_mono  = ("Consolas", 8)

# 顶部标题 + 时钟
frm_top = tk.Frame(root, bg="#2c3e50")
frm_top.pack(fill="x")
tk.Label(frm_top, text="🛒 京东监控控制面板",
         font=fnt_title, bg="#2c3e50", fg="white", pady=10).pack(side="left", padx=14)
lbl_clock = tk.Label(frm_top, text="", font=fnt_small,
                     bg="#2c3e50", fg="#95a5a6")
lbl_clock.pack(side="right", padx=14)

# ── 区块1：价格监控 ───────────────────────────────────────
frm_p = tk.LabelFrame(root, text=" 📊 价格监控（每5分钟）",
                       font=fnt_small, bg="#f0f0f0", padx=10, pady=8)
frm_p.pack(fill="x", padx=14, pady=(12, 6))

frm_p_row = tk.Frame(frm_p, bg="#f0f0f0")
frm_p_row.pack(fill="x")
lbl_price_status = tk.Label(frm_p_row, text="价格监控：已停止 🔴",
                             font=fnt_mid, bg="#f0f0f0", fg="#e74c3c")
lbl_price_status.pack(side="left")
lbl_price_cd = tk.Label(frm_p_row, text="",
                         font=fnt_small, bg="#f0f0f0", fg="#7f8c8d")
lbl_price_cd.pack(side="right")

btn_toggle = tk.Button(frm_p, text="▶  启动价格监控",
                        font=fnt_mid, bg="#27ae60", fg="white",
                        activebackground="#1e8449", activeforeground="white",
                        bd=0, pady=10, cursor="hand2", command=toggle_price)
btn_toggle.pack(fill="x", pady=(8, 0))

# ── 区块2：国补日报 ───────────────────────────────────────
frm_r = tk.LabelFrame(root, text=" 📋 国补日报（每天北京时间 09:00 自动发送）",
                       font=fnt_small, bg="#f0f0f0", padx=10, pady=8)
frm_r.pack(fill="x", padx=14, pady=6)

frm_r_row = tk.Frame(frm_r, bg="#f0f0f0")
frm_r_row.pack(fill="x")
tk.Label(frm_r_row, text="状态：常驻运行 🟢  面板打开即生效",
         font=fnt_small, bg="#f0f0f0", fg="#27ae60").pack(side="left")
lbl_report_cd = tk.Label(frm_r_row, text="",
                          font=fnt_small, bg="#f0f0f0", fg="#7f8c8d")
lbl_report_cd.pack(side="right")

# 各地区入口开关
frm_r_opt = tk.Frame(frm_r, bg="#f0f0f0")
frm_r_opt.pack(fill="x", pady=(6, 0))
tk.Checkbutton(
    frm_r_opt,
    text="📍 发送时包含各地区国补政策文字（31省市）",
    variable=_province_var,
    font=fnt_small, bg="#f0f0f0", fg="#2c3e50",
    activebackground="#f0f0f0", selectcolor="#f0f0f0",
    cursor="hand2",
).pack(side="left")

btn_report = tk.Button(frm_r, text="📋 立即发送国补日报",
                        font=fnt_mid, bg="#2980b9", fg="white",
                        activebackground="#1a6ea8", activeforeground="white",
                        bd=0, pady=10, cursor="hand2", command=send_report_manual)
btn_report.pack(fill="x", pady=(8, 0))

# ── 日志 ──────────────────────────────────────────────────
tk.Label(root, text="运行日志", font=fnt_small,
         bg="#f0f0f0", fg="#7f8c8d").pack(anchor="w", padx=16, pady=(6, 0))

frm_log = tk.Frame(root, bg="#f0f0f0")
frm_log.pack(fill="both", expand=True, padx=14, pady=(0, 10))

sb = tk.Scrollbar(frm_log)
sb.pack(side="right", fill="y")
txt = tk.Text(frm_log, font=fnt_mono, bg="#1e1e1e", fg="#dcdcdc",
              state="disabled", wrap="word", yscrollcommand=sb.set,
              relief="flat", bd=0, padx=6, pady=6)
txt.pack(fill="both", expand=True)
sb.config(command=txt.yview)

# 底部提示
tk.Label(root, text="⚠️ 启动前请关闭 VPN，否则京东/飞书接口无法访问",
         font=fnt_small, bg="#f0f0f0", fg="#e67e22").pack(pady=(0, 8))

# ── 启动 ──────────────────────────────────────────────────
_tick()
threading.Thread(target=_report_scheduler, daemon=True).start()

bj0 = now_bj()
log(f"控制面板已就绪  北京时间 {bj0.strftime('%Y-%m-%d %H:%M:%S')}")
log(f"国补日报调度器已启动，将在每天 {REPORT_HOUR:02d}:00 自动发送")
log("点击「启动价格监控」开始每5分钟价格检测")

root.mainloop()
