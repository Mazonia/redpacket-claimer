import os
import sys
import json
import time
import subprocess
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console()
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STATUS_FILE = os.path.join(BASE_DIR, "worker_status.json")
CACHE_FILE = os.path.join(BASE_DIR, "claimed_cache.json")
LOG_FILE = os.path.join(BASE_DIR, "claimer.log")
LOCKOUT_FILE = os.path.join(BASE_DIR, "user_data", "lockout_state.json")


def format_relative_time(timestamp: float) -> str:
    """Returns human-friendly relative time string (e.g., '3m ago', 'Just now')."""
    if not timestamp or timestamp <= 0:
        return "Unknown"
    diff = time.time() - timestamp
    if diff < 0:
        return "Just now"
    if diff < 60:
        return f"{int(diff)}s ago"
    minutes = int(diff // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    rem_m = minutes % 60
    if hours < 24:
        return f"{hours}h {rem_m}m ago"
    days = int(hours // 24)
    return f"{days}d ago"


def get_active_claimer_process() -> Tuple[bool, Optional[int], Optional[str], Optional[float]]:
    """
    Checks if a redpacket claimer process is actively running in this directory.
    Returns (is_running, pid, process_name, uptime_seconds).
    """
    try:
        import psutil
        cur_pid = os.getpid()
        cur_dir = BASE_DIR.lower()

        # Check PID recorded in status file first
        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                saved_pid = sdata.get("pid")
                if saved_pid and psutil.pid_exists(saved_pid) and saved_pid != cur_pid:
                    p = psutil.Process(saved_pid)
                    if p.is_running():
                        p_name = p.name().lower()
                        cmdline = " ".join(p.cmdline() or []).lower()
                        if "redpacket" in p_name or ("main.py" in cmdline and cur_dir in cmdline):
                            uptime = time.time() - p.create_time()
                            return True, p.pid, p.name(), uptime
            except Exception:
                pass

        # Scan running processes
        for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                if p.pid == cur_pid:
                    continue
                p_name = p.info.get('name', '').lower()
                cmdline = " ".join(p.info.get('cmdline') or []).lower()
                if "redpacket-claimer.exe" in p_name and cur_dir in cmdline:
                    uptime = time.time() - (p.info.get('create_time') or time.time())
                    return True, p.pid, p.info.get('name'), uptime
                if ("python.exe" in p_name or "pythonw.exe" in p_name) and "main.py" in cmdline and cur_dir in cmdline:
                    uptime = time.time() - (p.info.get('create_time') or time.time())
                    return True, p.pid, p.info.get('name'), uptime
            except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                pass
    except Exception:
        pass
    return False, None, None, None


def check_autostart_health() -> Dict[str, Any]:
    """Inspects Windows Scheduled Task and other autostart mechanisms."""
    result = {
        "scheduled_task_registered": False,
        "scheduled_task_state": "Not Found",
        "last_run_time": "Never",
        "last_task_result": "N/A",
        "startup_shortcut": False,
        "registry_entry": False,
        "is_configured": False
    }

    try:
        # Check Scheduled Task
        ps_cmd = "$t = Get-ScheduledTask -TaskName 'Binance-RedPacket-Claimer' -ErrorAction SilentlyContinue; if ($t) { $info = Get-ScheduledTaskInfo -TaskName 'Binance-RedPacket-Claimer' -ErrorAction SilentlyContinue; [PSCustomObject]@{ State = $t.State.ToString(); LastRunTime = $info.LastRunTime.ToString(); LastResult = $info.LastTaskResult } | ConvertTo-Json -Compress }"
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip())
            result["scheduled_task_registered"] = True
            result["scheduled_task_state"] = data.get("State", "Unknown")
            result["last_run_time"] = data.get("LastRunTime", "N/A")
            res_code = data.get("LastResult", 0)
            result["last_task_result"] = "Success (0)" if res_code == 0 else f"Code {res_code}"
            result["is_configured"] = True
    except Exception:
        pass

    # Check Startup folder
    try:
        startup_dir = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
        lnk_path = os.path.join(startup_dir, "Binance-RedPacket-Claimer.lnk")
        if os.path.exists(lnk_path):
            result["startup_shortcut"] = True
            result["is_configured"] = True
    except Exception:
        pass

    # Check Registry Run key
    try:
        ps_reg = "Get-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name 'Binance-RedPacket-Claimer' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty 'Binance-RedPacket-Claimer'"
        proc_reg = subprocess.run(["powershell", "-NoProfile", "-Command", ps_reg], capture_output=True, text=True, timeout=5)
        if proc_reg.returncode == 0 and proc_reg.stdout.strip():
            result["registry_entry"] = True
            result["is_configured"] = True
    except Exception:
        pass

    return result


def load_worker_status() -> Dict[str, Any]:
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_last_claimed_fallback() -> Optional[Dict[str, Any]]:
    """Extracts the latest claimed item from claimed_cache.json if worker_status.json is missing."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    # Search backwards for a rich entry
                    for item in reversed(data):
                        if isinstance(item, dict) and item.get("identifier"):
                            return item
                    first_item = data[-1]
                    if isinstance(first_item, str):
                        return {
                            "identifier": first_item,
                            "type": "code",
                            "channel": "Cached Drop",
                            "claimed_at": "Earlier today",
                            "timestamp": 0.0,
                            "status": "claimed"
                        }
        except Exception:
            pass
    return None


def show_worker_dashboard():
    """Renders the comprehensive diagnostic dashboard with health, last claimed code, and recent history."""
    console.clear()
    console.print()
    console.print("================================================================================", style="bold cyan")
    console.print("       🔍 BINANCE AUTO-CLAIMER — BACKGROUND WORKER DIAGNOSTIC MONITOR", style="bold yellow")
    console.print("================================================================================", style="bold cyan")
    console.print()

    # 1. Process Status
    is_running, pid, proc_name, uptime_s = get_active_claimer_process()
    sdata = load_worker_status()
    last_hb_ts = sdata.get("last_heartbeat_timestamp", 0)
    hb_fresh = (time.time() - last_hb_ts) < 60 if last_hb_ts else False

    if is_running:
        uptime_str = format_duration_short(int(uptime_s)) if uptime_s else "Active"
        hb_str = format_relative_time(last_hb_ts) if last_hb_ts else "Just started"
        proc_status_text = (
            f"[bold green]● RUNNING & ACTIVE[/bold green] (PID: [bold white]{pid}[/bold white], "
            f"Process: [bold cyan]{proc_name}[/bold cyan], Uptime: [bold white]{uptime_str}[/bold white], "
            f"Heartbeat: [bold green]{hb_str}[/bold green])"
        )
    else:
        proc_status_text = "[bold red]○ NOT RUNNING / OFFLINE[/bold red] (No active background worker process found)"

    status_panel_text = f"Worker State:      {proc_status_text}\n"
    mode_text = "Headless (Silent Background)" if sdata.get("headless", True) else "Visible (Headful)"
    status_panel_text += f"Execution Mode:    [cyan]{mode_text}[/cyan]\n"

    channels = sdata.get("channels", [])
    ch_text = ", ".join(channels) if channels else "Configured in .env"
    status_panel_text += f"Monitored Channels:[bold magenta] {ch_text}[/bold magenta]\n"

    tg_connected = sdata.get("telegram_connected")
    if tg_connected is True:
        tg_status_str = "[bold green]✓ Connected & Actively Listening[/bold green]"
    elif tg_connected is False and is_running:
        tg_status_str = "[bold yellow]🔄 Reconnecting / Offline[/bold yellow]"
    else:
        tg_status_str = "[dim]Offline[/dim]"
    status_panel_text += f"Telegram Listener: {tg_status_str}\n"

    # Lockout status
    lockout_active = sdata.get("lockout_active", False)
    rem_str = sdata.get("lockout_remaining_str", "")
    if lockout_active:
        status_panel_text += f"Binance Cooldown:  [bold red]⏳ ACTIVE ({rem_str} remaining)[/bold red]\n"
    else:
        status_panel_text += f"Binance Cooldown:  [bold green]✓ Clear (Ready to claim drops)[/bold green]\n"

    cached_count = sdata.get("total_cached_items")
    if cached_count is None:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    c_data = json.load(f)
                    cached_count = len(c_data) if isinstance(c_data, (list, dict)) else 0
            except Exception:
                cached_count = "N/A"
        else:
            cached_count = 0

    count_str = f"{cached_count:,}" if isinstance(cached_count, int) else str(cached_count)
    status_panel_text += f"Cached Codes:      [bold white]{count_str}[/bold white] items indexed"

    console.print(Panel(status_panel_text, title="[bold cyan]⚡ Worker Health & Runtime State[/bold cyan]", border_style="cyan"))

    # 2. Autostart Status
    auto = check_autostart_health()
    auto_lines = []
    if auto["scheduled_task_registered"]:
        task_state_style = "bold green" if auto["scheduled_task_state"] in ["Ready", "Running"] else "bold yellow"
        auto_lines.append(f"Task Scheduler:    [{task_state_style}]{auto['scheduled_task_state']}[/{task_state_style}] (Task Name: [bold white]Binance-RedPacket-Claimer[/bold white])")
        auto_lines.append(f"Boot / Wake Sync:  [bold green]✓ Active[/bold green] (Triggers automatically 15s after Windows boot and wake-from-sleep)")
        auto_lines.append(f"Last Task Run:     [white]{auto['last_run_time']}[/white] (Result: [bold green]{auto['last_task_result']}[/bold green])")
    else:
        auto_lines.append("Task Scheduler:    [yellow]Not registered (Run setup_autostart.bat as Admin to enable 24/7 background service)[/yellow]")

    if auto["startup_shortcut"]:
        auto_lines.append("Startup Shortcut:  [bold green]✓ Installed[/bold green] in Windows Startup Folder")
    if auto["registry_entry"]:
        auto_lines.append("Registry Run Key:  [bold green]✓ Registered[/bold green] in HKCU Run Key")

    auto_panel_style = "green" if auto["is_configured"] else "yellow"
    console.print(Panel("\n".join(auto_lines), title="[bold yellow]🔄 Windows Auto-Start Configuration[/bold yellow]", border_style=auto_panel_style))

    # 3. HERO SECTION: LAST CODE REDEEMED
    last_claim = sdata.get("last_code_claimed") or load_last_claimed_fallback()

    if last_claim:
        code_ident = last_claim.get("identifier", "N/A")
        code_channel = last_claim.get("channel", "Unknown Channel")
        claimed_at = last_claim.get("claimed_at", "N/A")
        ts = last_claim.get("timestamp", 0)
        rel_time = format_relative_time(ts) if ts else ""
        rel_time_str = f" ({rel_time})" if rel_time else ""
        c_status = last_claim.get("status", "claimed").lower()
        reward = last_claim.get("reward", "")

        status_display = {
            "success": "[bold green]🎉 SUCCESSFUL CLAIM[/bold green]",
            "expired": "[bold yellow]❌ EXPIRED (Fully claimed by others)[/bold yellow]",
            "already_claimed": "[bold yellow]↷ ALREADY CLAIMED (Previously claimed)[/bold yellow]",
            "invalid": "[bold red]⚠️ INVALID CODE[/bold red]",
            "rate_limited": "[bold red]⏳ RATE LIMITED (Queued for cooldown expiry)[/bold red]",
        }.get(c_status, f"[cyan]{c_status.upper()}[/cyan]")

        hero_text = (
            f"[bold white]Redeemed Code:[/bold white]    [bold gold1 on grey15]  {code_ident}  [/bold gold1 on grey15]\n"
            f"[bold white]Source Channel:[/bold white]   [bold cyan]{code_channel}[/bold cyan]\n"
            f"[bold white]Time Claimed:[/bold white]     [bold white]{claimed_at}[/bold white]{rel_time_str}\n"
            f"[bold white]Claim Outcome:[/bold white]    {status_display}"
        )
        if reward:
            hero_text += f"\n[bold white]Reward Won:[/bold white]       [bold green]{reward}[/bold green]"

        console.print(Panel(hero_text, title="[bold gold1]🎁 LAST CODE REDEEMED[/bold gold1]", border_style="gold1"))
    else:
        console.print(Panel(
            "[dim yellow]No codes claimed in current session yet.\n"
            "The background worker is actively listening for live drops from your channels.[/dim yellow]",
            title="[bold gold1]🎁 Last Code Redeemed[/bold gold1]",
            border_style="yellow"
        ))

    # 4. Recent Claims History Table
    recent_history: List[Dict[str, Any]] = sdata.get("recent_history", [])
    if not recent_history and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cdata = json.load(f)
                if isinstance(cdata, list):
                    rich_items = [it for it in cdata if isinstance(it, dict) and it.get("identifier")]
                    recent_history = list(reversed(rich_items[-10:]))
        except Exception:
            pass

    if recent_history:
        table = Table(title="📋 Recent Redemption Activity", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Time", style="bold white", width=20)
        table.add_column("Code / Item", style="bold gold1", width=18)
        table.add_column("Source Channel", style="cyan", width=22)
        table.add_column("Type", style="dim", width=8)
        table.add_column("Status", style="bold", width=20)

        for i, item in enumerate(recent_history[:10], start=1):
            t_str = item.get("claimed_at") or "Unknown"
            ident = item.get("identifier") or "N/A"
            ch = item.get("channel") or "Unknown"
            itype = item.get("type", "code").capitalize()
            st = item.get("status", "claimed").lower()
            if st == "success":
                st_badge = "[bold green]✓ SUCCESS[/bold green]"
            elif st == "expired":
                st_badge = "[yellow]Expired[/yellow]"
            elif st == "already_claimed":
                st_badge = "[dim yellow]Already Claimed[/dim yellow]"
            elif st == "invalid":
                st_badge = "[red]Invalid[/red]"
            else:
                st_badge = f"[cyan]{st}[/cyan]"

            table.add_row(str(i), t_str, ident, ch, itype, st_badge)

        console.print(table)
    console.print()


def format_duration_short(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    m = seconds // 60
    if m < 60:
        return f"{m}m {seconds % 60}s"
    h = m // 60
    return f"{h}h {m % 60}m"


def tail_log_file(lines_to_show: int = 25):
    """Prints recent log entries and streams live logs until user cancels."""
    if not os.path.exists(LOG_FILE):
        console.print("[dim yellow]No log file found yet (claimer.log).[/dim yellow]")
        return

    console.print(f"[bold cyan]Tailing claimer.log (last {lines_to_show} lines). Press Ctrl+C to stop...[/bold cyan]\n")
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()
            for line in all_lines[-lines_to_show:]:
                sys.stdout.write(line)
            sys.stdout.flush()

            # Follow mode
            while True:
                line = f.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped log streaming.[/dim]")


async def test_live_code_redemption(test_code: str):
    """Executes a live test claim on Binance using BinanceRedeemer to verify browser engine."""
    from redemption import BinanceRedeemer
    console.print(f"\n[bold cyan][+] Initializing browser to test claim for code: [bold white]{test_code}[/bold white]...[/bold cyan]")
    redeemer = BinanceRedeemer(headless=True)
    try:
        await redeemer.initialize()
        console.print("[bold green][✓] Browser session launched successfully![/bold green]")
        res = await redeemer.claim_crypto_box_code(test_code)
        console.print(f"\n[bold gold1]Test Claim Result:[/bold gold1] [bold white]{res}[/bold white]")
        status = res.get("status", "")
        if status in ["success", "expired", "already_claimed", "invalid"]:
            console.print("[bold green][✓] TEST PASSED: Background browser engine is fully responsive and communicating with Binance![/bold green]")
        else:
            console.print(f"[yellow][!] Response returned status: '{status}' ({res.get('message')})[/yellow]")
    except Exception as e:
        console.print(f"[bold red][!] Test encountered error: {e}[/bold red]")
    finally:
        try:
            await redeemer.close()
        except Exception:
            pass


def interactive_menu():
    """Interactive CLI menu for testing and managing background worker."""
    while True:
        show_worker_dashboard()
        console.print("────────────────────────────────────────────────────────────────────────────────", style="dim")
        console.print("  [bold cyan]1[/bold cyan] - Test Claim a Code Live (verifies Binance browser redemption)")
        console.print("  [bold cyan]2[/bold cyan] - Stream Live Logs (real-time claimer.log)")
        console.print("  [bold cyan]3[/bold cyan] - Restart Background Worker (clean launch)")
        console.print("  [bold cyan]4[/bold cyan] - Stop Background Worker")
        console.print("  [bold cyan]R[/bold cyan] - Refresh Dashboard")
        console.print("  [bold cyan]Q[/bold cyan] - Exit")
        console.print("────────────────────────────────────────────────────────────────────────────────", style="dim")
        
        try:
            choice = input("\nEnter choice [1-4 / R / Q]: ").strip().upper()
        except (KeyboardInterrupt, EOFError):
            break

        if choice == "1":
            code = input("Enter code to test (e.g. BBQAG5R8 or press Enter for sample test): ").strip().upper()
            if not code:
                code = "BINANCETEST"
            import asyncio
            asyncio.run(test_live_code_redemption(code))
            input("\nPress Enter to return to dashboard...")
        elif choice == "2":
            tail_log_file(30)
            input("\nPress Enter to return to dashboard...")
        elif choice == "3":
            console.print("[yellow]Restarting background claimer...[/yellow]")
            subprocess.run(["cmd.exe", "/c", os.path.join(BASE_DIR, "stop.bat")], cwd=BASE_DIR)
            time.sleep(1)
            subprocess.run(["cscript", "//nologo", os.path.join(BASE_DIR, "start_hidden.vbs"), "/silent"], cwd=BASE_DIR)
            time.sleep(2)
            console.print("[bold green][✓] Background worker triggered![/bold green]")
            time.sleep(1)
        elif choice == "4":
            console.print("[yellow]Stopping background claimer...[/yellow]")
            subprocess.run(["cmd.exe", "/c", os.path.join(BASE_DIR, "stop.bat")], cwd=BASE_DIR)
            input("\nPress Enter to refresh...")
        elif choice == "Q":
            break
        elif choice == "R" or choice == "":
            continue


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ["--non-interactive", "-n", "--check", "--quiet"]:
        show_worker_dashboard()
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
