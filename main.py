import os
import sys
import json
import time
import asyncio
import argparse
from datetime import datetime, timezone
from typing import Set, Dict, Any, List, Optional
from dotenv import load_dotenv
from telethon import TelegramClient, events
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from parser import parse_telegram_message
from redemption import BinanceRedeemer

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("RedPacket-Auto-Claimer")
    except Exception:
        pass

load_dotenv()

console = Console()

def parse_cli_args():
    parser = argparse.ArgumentParser(description="Binance Red Packet & Feed Auto-Claimer")
    parser.add_argument("--catchup", type=int, default=35, help="Number of recent channel drops to sweep and claim on startup (default: 35)")
    parser.add_argument("--clear-lockout", action="store_true", help="Clear saved Binance lockout state immediately")
    parser.add_argument("--clear-cache", action="store_true", help="Clear claimed codes cache")
    parser.add_argument("--headless", action="store_true", help="Force headless browser mode")
    parser.add_argument("--headful", action="store_true", help="Force visible browser mode")
    args, _ = parser.parse_known_args()
    return args

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
PHONE = os.getenv("TELEGRAM_PHONE", "").strip()
TARGET_CHANNEL_RAW = os.getenv("TARGET_CHANNEL", "").strip()
HEADLESS_MODE = os.getenv("HEADLESS", "false").lower() == "true"

TARGET_CHANNELS = [c.strip() for c in TARGET_CHANNEL_RAW.split(",") if c.strip()]

if not API_ID or not API_HASH or not TARGET_CHANNELS:
    console.print("[bold red][!] ERROR: TELEGRAM_API_ID, TELEGRAM_API_HASH, and TARGET_CHANNEL must be set in your .env file.[/bold red]")
    input("\nPress Enter to exit...")
    exit(1)

CACHE_FILE = os.path.abspath("./claimed_cache.json")
HELD_DROPS_FILE = os.path.abspath("./held_drops.json")
MAX_FRESH_CODE_AGE_SECONDS = 180  # Codes older than 3 minutes are dead in public channels

# Stepped reconnection backoff schedule for internet disconnections / Telegram unreachability
# Ladder: 30s -> 1m -> 3m -> 5m -> 10m -> 20m -> 30m -> 45m
RETRY_DELAYS = [30, 60, 180, 300, 600, 1200, 1800, 2700]


def get_backoff_delay(attempt: int) -> int:
    """Returns backoff delay in seconds for the given failed retry attempt (0-indexed)."""
    if attempt < len(RETRY_DELAYS):
        return RETRY_DELAYS[attempt]
    return RETRY_DELAYS[-1]


def format_delay_text(seconds: int) -> str:
    """Formats delay in seconds into a human-friendly string (e.g. '30s', '1 min', '3 min')."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    rem = seconds % 60
    if rem == 0:
        return f"{minutes} min"
    return f"{minutes} min {rem}s"


def load_claimed_cache() -> Set[str]:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data)
        except Exception:
            return set()
    return set()


def save_claimed_cache(cache: Set[str]):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(cache), f, indent=2)
    except Exception as e:
        console.print(f"[dim yellow][!] Warning: Could not save cache: {e}[/dim yellow]")


def load_held_drops() -> List[Dict[str, Any]]:
    if os.path.exists(HELD_DROPS_FILE):
        try:
            with open(HELD_DROPS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            return []
    return []


def save_held_drops():
    try:
        with open(HELD_DROPS_FILE, "w", encoding="utf-8") as f:
            json.dump(held_drops, f, indent=2)
    except Exception as e:
        console.print(f"[dim yellow][!] Warning: Could not save held drops cache: {e}[/dim yellow]")


held_drops: List[Dict[str, Any]] = load_held_drops()


def enqueue_held_drop(item_type: str, identifier: str, extra: str = "", timestamp: Optional[float] = None):
    if identifier in claimed_items:
        return
    if any(item.get("identifier") == identifier for item in held_drops):
        return

    ts = timestamp if timestamp is not None else time.time()
    drop = {
        "type": item_type,
        "identifier": identifier,
        "extra": extra,
        "timestamp": ts
    }
    held_drops.append(drop)
    save_held_drops()
    console.print(f"[bold yellow]📥 Held drop queued for auto-redemption post-lockout: {item_type.upper()} '{identifier}'[/bold yellow]")


def format_phone_number(phone_input: str) -> str:
    phone_input = phone_input.strip().replace(" ", "").replace("-", "")
    if not phone_input.startswith("+"):
        console.print(f"[bold yellow][!] Notice: Telegram requires your phone number in international format (e.g. +1234567890).[/bold yellow]")
        if phone_input.startswith("0"):
            country_code = console.input("[bold cyan]Enter your Country Code (e.g. 1 for USA, 44 for UK, 233 for Ghana, 234 for Nigeria): [/bold cyan]").strip().lstrip("+")
            formatted = f"+{country_code}{phone_input[1:]}"
            console.print(f"[bold green][✓] Formatted phone number to: {formatted}[/bold green]")
            return formatted
        else:
            return f"+{phone_input}"
    return phone_input


def phone_callback():
    if PHONE:
        return format_phone_number(PHONE)
    raw_phone = console.input("[bold cyan]Enter your Telegram phone number (with country code, e.g. +1234567890): [/bold cyan]")
    return format_phone_number(raw_phone)


client = TelegramClient(
    'binance_session',
    int(API_ID),
    API_HASH,
    connection_retries=3,
    retry_delay=1,
    auto_reconnect=True
)
redeemer = BinanceRedeemer(headless=HEADLESS_MODE)
claimed_items: Set[str] = load_claimed_cache()


async def process_single_item(item_type: str, identifier: str, extra: str = "", timestamp: Optional[float] = None):
    if identifier in claimed_items:
        console.print(f"[dim]↷ Skipping already cached {item_type}: {identifier}[/dim]")
        return

    # Check if account is on active Binance cooldown
    is_locked, remaining_s, remaining_str = redeemer.is_locked_out()
    if is_locked:
        console.print(f"[bold red]⏳ Account on Binance Lockout ({remaining_str} remaining). Cannot claim '{identifier}' now — holding in queue.[/bold red]")
        enqueue_held_drop(item_type, identifier, extra, timestamp=timestamp)
        return

    ts = timestamp if timestamp is not None else time.time()

    if item_type == "code":
        console.print(f"[bold gold1]⚡ Claiming Crypto Box Code: [bold white]{identifier}[/bold white][/bold gold1]")
        res = await redeemer.claim_crypto_box_code(identifier)
        status = res.get("status", "")

        if status in ["success", "expired", "already_claimed", "invalid"]:
            claimed_items.add(identifier)
            save_claimed_cache(claimed_items)
            redeemer.clear_lockout()
        elif status == "rate_limited":
            rem_str = redeemer.get_lockout_remaining_str()
            console.print(Panel(
                f"[bold red]🚫 BINANCE RATE LIMIT / LOCKOUT ACTIVATED[/bold red]\n"
                f"[bold white]Code '[bold yellow]{identifier}[/bold yellow]' was queued for auto-redemption when lockout expires.[/bold white]\n"
                f"[bold yellow]Bot is pausing claims for {rem_str} to protect your account.[/bold yellow]",
                title="[bold red]Rate Limit Alert[/bold red]",
                border_style="red"
            ))
            enqueue_held_drop(item_type, identifier, extra, timestamp=ts)
        else:
            console.print(f"[bold yellow][!] Code '{identifier}' returned status '{status}' ({res.get('message')}). Not cached.[/bold yellow]")

    elif item_type == "square":
        console.print(f"[bold gold1]⚡ Claiming Binance Square Post: [bold white]{identifier}[/bold white] (Answer: [bold yellow]{extra}[/bold yellow])[/bold gold1]")
        res = await redeemer.claim_binance_square_red_packet(identifier, extra)
        status = res.get("status", "")

        if status in ["success", "submitted", "opened", "expired", "already_claimed", "invalid"]:
            claimed_items.add(identifier)
            save_claimed_cache(claimed_items)
            redeemer.clear_lockout()
        elif status == "rate_limited":
            rem_str = redeemer.get_lockout_remaining_str()
            console.print(f"[bold red]🚫 Lockout active ({rem_str} remaining). Square post '{identifier}' held in queue.[/bold red]")
            enqueue_held_drop(item_type, identifier, extra, timestamp=ts)
        else:
            console.print(f"[bold yellow][!] Square post '{identifier}' returned '{status}'. Not cached.[/bold yellow]")

    elif item_type == "url":
        console.print(f"[bold gold1]⚡ Opening Red Packet Link: [bold white]{identifier}[/bold white][/bold gold1]")
        res = await redeemer.claim_red_packet_url(identifier)
        status = res.get("status", "")

        if status in ["success", "opened", "expired", "already_claimed", "invalid"]:
            claimed_items.add(identifier)
            save_claimed_cache(claimed_items)
            redeemer.clear_lockout()
        elif status == "rate_limited":
            rem_str = redeemer.get_lockout_remaining_str()
            console.print(f"[bold red]🚫 Lockout active ({rem_str} remaining). Link '{identifier}' held in queue.[/bold red]")
            enqueue_held_drop(item_type, identifier, extra, timestamp=ts)
        else:
            console.print(f"[bold yellow][!] Link '{identifier}' returned '{status}'. Not cached.[/bold yellow]")


async def scan_and_claim_history(channel_entities: List[Any], catchup_limit: int = 35):
    console.print(Panel(
        "[bold cyan]🔍 Starting Intelligent Channel History Sweep...[/bold cyan]\n"
        f"[bold white]• Catch-Up Target:[/bold white] Up to {catchup_limit} recent drops from channel history.\n"
        "[bold white]• Circuit Breaker:[/bold white] Safe pauses between dead drops to protect account from Binance lockouts.",
        title="[bold yellow]Catch-Up & History Sweep Mode[/bold yellow]"
    ))

    now = datetime.now(timezone.utc)
    pending_items: List[Dict[str, Any]] = []
    ancient_codes_indexed = 0

    for entity in channel_entities:
        chat_name = str(entity)
        try:
            chat = await client.get_entity(entity)
            chat_name = getattr(chat, 'title', getattr(chat, 'username', str(entity)))
        except Exception:
            pass

        console.print(f"[cyan][+] Scanning recent messages from '[bold white]{chat_name}[/bold white]'...[/cyan]")

        try:
            channel_items = []
            async for msg in client.iter_messages(entity, limit=80):
                if not msg.raw_text or not msg.date:
                    continue

                msg_age_seconds = (now - msg.date).total_seconds()
                parsed = parse_telegram_message(msg.raw_text)

                for c in parsed.get("codes", []):
                    if c in claimed_items:
                        continue
                    if msg_age_seconds > 86400:  # Older than 24 hours
                        claimed_items.add(c)
                        ancient_codes_indexed += 1
                    else:
                        channel_items.append({
                            "type": "code",
                            "identifier": c,
                            "extra": "",
                            "date": msg.date,
                            "age_s": int(msg_age_seconds),
                            "channel": chat_name
                        })

                sq_urls = parsed.get("square_urls", [])
                answers = parsed.get("answers", [])
                if sq_urls and answers:
                    url = sq_urls[0]
                    ans = answers[0]
                    if url not in claimed_items:
                        if msg_age_seconds > 86400:
                            claimed_items.add(url)
                            ancient_codes_indexed += 1
                        else:
                            channel_items.append({
                                "type": "square",
                                "identifier": url,
                                "extra": ans,
                                "date": msg.date,
                                "age_s": int(msg_age_seconds),
                                "channel": chat_name
                            })

            # Sort channel drops chronologically (oldest in the recent window first)
            channel_items.sort(key=lambda x: x["date"])
            # Take up to catchup_limit for this channel
            pending_items.extend(channel_items[-catchup_limit:] if len(channel_items) > catchup_limit else channel_items)

        except Exception as e:
            console.print(f"[yellow][!] Notice while scanning history from {chat_name}: {e}[/yellow]")

    if ancient_codes_indexed > 0:
        save_claimed_cache(claimed_items)
        console.print(f"[dim green][✓] Pre-cached {ancient_codes_indexed} ancient (>24h) drops.[/dim green]")

    history_table = Table(title=f"📋 History Sweep Summary ({len(pending_items)} Recent Drops Found)", show_header=True, header_style="bold magenta")
    history_table.add_column("#", style="dim", width=4)
    history_table.add_column("Type", style="cyan", width=12)
    history_table.add_column("Item / Code / URL", style="bold white")
    history_table.add_column("Age", style="bold yellow")
    history_table.add_column("Status", style="bold")

    idx = 1
    for item in pending_items:
        age_str = f"{item['age_s'] // 60}m ago" if item['age_s'] >= 60 else f"{item['age_s']}s ago"
        history_table.add_row(str(idx), item["type"].capitalize(), item["identifier"], age_str, "[bold green]Ready To Claim[/bold green]")
        idx += 1

    if not pending_items:
        history_table.add_row("-", "All Clear", "No unhandled recent drops in channel history", "-", "[dim]Up to date[/dim]")

    console.print(history_table)

    # Process catch-up items
    if pending_items:
        console.print(f"\n[bold cyan]▶ Attempting to redeem {len(pending_items)} missed / recent drops...[/bold cyan]")
        for item in pending_items:
            is_locked, _, _ = redeemer.is_locked_out()
            if is_locked:
                console.print("[bold red]⏳ Cooldown encountered during catch-up sweep. Remaining items placed in held queue.[/bold red]")
                enqueue_held_drop(item["type"], item["identifier"], item["extra"], timestamp=item["date"].timestamp())
                continue
            await process_single_item(item["type"], item["identifier"], item["extra"], timestamp=item["date"].timestamp())

    console.print("\n[bold green][✓] Channel history sweep completed smoothly![/bold green]\n")


@client.on(events.NewMessage(chats=TARGET_CHANNELS))
async def live_message_handler(event):
    try:
        chat = await event.get_chat()
        chat_name = getattr(chat, 'title', getattr(chat, 'username', 'Channel'))
    except Exception:
        chat_name = "Channel"

    message_text = event.raw_text
    console.print(Panel(message_text, title=f"[bold green]📩 New Drop from {chat_name}[/bold green]", border_style="green"))

    msg_timestamp = time.time()
    if event.message and event.message.date:
        msg_timestamp = event.message.date.timestamp()

    parsed = parse_telegram_message(message_text)
    codes = parsed.get("codes", [])
    square_urls = parsed.get("square_urls", [])
    red_packet_urls = parsed.get("red_packet_urls", [])
    answers = parsed.get("answers", [])

    if not codes and not square_urls and not red_packet_urls:
        console.print("[dim][i] Post received, but no red packet codes or reward links found.[/dim]\n")
        return

    for sq_url in square_urls:
        ans = answers[0] if answers else ""
        await process_single_item("square", sq_url, ans, timestamp=msg_timestamp)

    for code in codes:
        await process_single_item("code", code, timestamp=msg_timestamp)

    for rp_url in red_packet_urls:
        await process_single_item("url", rp_url, timestamp=msg_timestamp)


async def keepalive_watchdog():
    """
    Periodically checks MTProto connectivity to Telegram servers.
    If the connection drops silently, disconnects client to trigger the stepped backoff ladder quickly.
    """
    from telethon.tl.functions import PingRequest
    while True:
        try:
            await asyncio.sleep(25)
            if client.is_connected():
                try:
                    await asyncio.wait_for(client(PingRequest(ping_id=0)), timeout=10.0)
                except Exception as e:
                    console.print(f"[dim yellow][!] Telegram keepalive ping timed out ({e}). Triggering reconnection ladder...[/dim yellow]")
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
        except asyncio.CancelledError:
            break
        except Exception:
            pass


async def connect_and_listen(catchup_limit: int = 35):
    """
    Manages Telegram client connection and live listening with stepped exponential backoff:
    30s -> 1m -> 3m -> 5m -> 10m -> 20m -> 30m -> 45m
    """
    attempt = 0
    resolved_entities = []

    while True:
        try:
            if not client.is_connected():
                console.print(f"\n[bold cyan][+] Connecting to Telegram...[/bold cyan]")
                if not os.path.exists("binance_session.session"):
                    await client.start(phone=phone_callback)
                else:
                    try:
                        await client.connect()
                        if not await client.is_user_authorized():
                            await client.start(phone=phone_callback)
                    except Exception:
                        await client.start(phone=phone_callback)

            try:
                me = await client.get_me()
                user_display = getattr(me, 'first_name', 'Authorized User') if me else 'Telegram User'
            except Exception:
                user_display = 'Telegram User'

            if attempt > 0:
                console.print(f"[bold green]🌐 [✓] Internet Restored! Reconnected to Telegram as [bold white]{user_display}[/bold white]![/bold green]\n")
            else:
                console.print(f"[bold green][✓] Telegram connected successfully as [bold white]{user_display}[/bold white]![/bold green]\n")

            # Reset backoff attempt counter on successful connection
            attempt = 0

            # Resolve target channels
            resolved_entities = []
            for ch in TARGET_CHANNELS:
                try:
                    entity = await client.get_entity(ch)
                    resolved_entities.append(entity)
                except Exception as e:
                    console.print(f"[yellow][!] Notice: Could not resolve channel '{ch}' directly, using raw handle: {e}[/yellow]")
                    resolved_entities.append(ch)

            # Catch-up history sweep for fresh drops received during downtime/start
            await scan_and_claim_history(resolved_entities, catchup_limit=catchup_limit)

            console.print(f"[bold gold1]📡 Bot is actively listening for live drops on: {', '.join(TARGET_CHANNELS)}... (Press Ctrl+C to stop)[/bold gold1]\n")

            # Start keepalive watchdog task alongside run_until_disconnected
            watchdog_task = asyncio.create_task(keepalive_watchdog())
            try:
                await client.run_until_disconnected()
            finally:
                watchdog_task.cancel()
                try:
                    await watchdog_task
                except (asyncio.CancelledError, Exception):
                    pass

            console.print("[bold yellow][!] Telegram connection disconnected.[/bold yellow]")

        except asyncio.CancelledError:
            break
        except KeyboardInterrupt:
            raise
        except Exception as e:
            console.print(f"[bold red][!] Telegram connection error: {e}[/bold red]")

        # Disconnection occurred - enter backoff ladder
        delay = get_backoff_delay(attempt)
        delay_formatted = format_delay_text(delay)
        attempt_num = attempt + 1
        ladder_summary = "30s → 1m → 3m → 5m → 10m → 20m → 30m → 45m"

        console.print(Panel(
            f"[bold red]🔌 TELEGRAM DISCONNECTED / UNREACHABLE[/bold red]\n"
            f"[bold white]Internet is disconnected or Telegram servers cannot be reached.[/bold white]\n"
            f"[bold yellow]Retrying in [bold cyan]{delay_formatted}[/bold cyan] (Attempt #{attempt_num}).[/bold yellow]\n"
            f"[dim]Backoff Sequence: {ladder_summary}[/dim]",
            title="[bold red]Network Reconnection Manager[/bold red]",
            border_style="red"
        ))

        # Perform interactive live countdown wait
        try:
            with console.status(f"[bold yellow]⏳ Reconnecting to Telegram in {delay_formatted} (Attempt #{attempt_num})...[/bold yellow]", spinner="dots") as status:
                for remaining in range(delay, 0, -1):
                    if remaining % 60 == 0 or remaining in [45, 30, 15, 10, 5, 4, 3, 2, 1]:
                        status.update(f"[bold yellow]⏳ Telegram offline. Reconnecting in {format_delay_text(remaining)} (Attempt #{attempt_num})...[/bold yellow]")
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            break
        except KeyboardInterrupt:
            raise

        attempt += 1


async def lockout_queue_monitor():
    """
    Background worker that continuously monitors Binance lockout status.
    Once lockout expires, automatically processes all queued held drops that are still fresh.
    """
    while True:
        try:
            await asyncio.sleep(2)
            if not held_drops:
                continue

            is_locked, remaining_s, remaining_str = redeemer.is_locked_out()
            if is_locked:
                continue

            # Lockout cleared and we have held drops!
            drops_to_process = list(held_drops)
            console.print(Panel(
                f"[bold green]🔓 BINANCE LOCKOUT EXPIRED / CLEARED![/bold green]\n"
                f"[bold white]Auto-entering {len(drops_to_process)} held drop(s) queued during lockout...[/bold white]",
                title="[bold green]Auto-Redeeming Held Drops[/bold green]",
                border_style="green"
            ))

            now_ts = time.time()
            for item in drops_to_process:
                # Remove from held_drops list and save state
                if item in held_drops:
                    held_drops.remove(item)
                    save_held_drops()

                item_type = item.get("type", "code")
                identifier = item.get("identifier", "")
                extra = item.get("extra", "")
                ts = item.get("timestamp", now_ts)

                if identifier in claimed_items:
                    continue

                age = now_ts - ts
                if age > 86400:  # Older than 24 hours
                    console.print(f"[dim yellow]↷ Skipping held {item_type} '{identifier}' ({int(age)}s old) — ancient drop to protect account.[/dim yellow]")
                    claimed_items.add(identifier)
                    save_claimed_cache(claimed_items)
                    continue

                console.print(f"[bold cyan]⚡ Auto-entering held drop ({int(age)}s old): [bold white]{identifier}[/bold white][/bold cyan]")
                await process_single_item(item_type, identifier, extra, timestamp=ts)

                # If processing this drop triggered lockout again, pause remaining
                is_locked_now, _, rem_str_now = redeemer.is_locked_out()
                if is_locked_now:
                    console.print(f"[bold red]⏳ Re-entered Binance lockout ({rem_str_now} remaining). Remaining held drops will stay queued.[/bold red]")
                    break

        except asyncio.CancelledError:
            break
        except Exception as e:
            console.print(f"[dim yellow][!] Notice in lockout queue monitor: {e}[/dim yellow]")
            await asyncio.sleep(5)


async def main():
    cli_args = parse_cli_args()

    global HEADLESS_MODE
    if cli_args.headless:
        HEADLESS_MODE = True
        redeemer.headless = True
    elif cli_args.headful:
        HEADLESS_MODE = False
        redeemer.headless = False

    if cli_args.clear_lockout:
        redeemer.clear_lockout()
        console.print("[bold green][✓] Manually cleared Binance lockout state on startup.[/bold green]")

    if cli_args.clear_cache:
        claimed_items.clear()
        save_claimed_cache(claimed_items)
        console.print("[bold green][✓] Cleared claimed codes cache.[/bold green]")

    is_locked, remaining_s, remaining_str = redeemer.is_locked_out()
    lockout_status = f"[bold red]Active ({remaining_str} remaining)[/bold red]" if is_locked else "[bold green]Clear (Ready to Claim)[/bold green]"

    table = Table(title="🚀 Binance Red Packet & Feed Auto-Claimer", show_header=True, header_style="bold magenta")
    table.add_column("Setting", style="dim", width=25)
    table.add_column("Value", style="bold green")
    table.add_row("Target Channels", ", ".join(TARGET_CHANNELS))
    table.add_row("Browser Mode", "Headless" if HEADLESS_MODE else "Visible (Headful)")
    table.add_row("Redemption URL", "https://www.binance.com/en/my/wallet/account/payment/cryptobox")
    table.add_row("Session Directory", "./user_data")
    table.add_row("Cached Items", str(len(claimed_items)))
    table.add_row("Queued Held Drops", f"{len(held_drops)} item(s)")
    table.add_row("Lockout Status", lockout_status)
    table.add_row("Catch-Up Sweep Limit", f"{cli_args.catchup} recent drops")
    table.add_row("Auto-Reconnect Ladder", "30s → 1m → 3m → 5m → 10m → 20m → 30m → 45m")
    console.print(table)

    if is_locked:
        console.print(Panel(
            f"[bold red]⚠️ ACTIVE BINANCE RATE LIMIT DETECTED[/bold red]\n"
            f"[bold white]Your Binance account is on cooldown ({remaining_str} remaining).[/bold white]\n"
            f"[bold yellow]The bot is running in stealth listener mode. Drops will be queued and auto-redeemed once lockout expires.[/bold yellow]\n"
            f"[dim cyan]Tip: If you tested a code manually and it worked, pass --clear-lockout flag to reset this timer.[/dim cyan]",
            title="[bold yellow]Protection Mode Active[/bold yellow]",
            border_style="yellow"
        ))

    lockout_task = asyncio.create_task(lockout_queue_monitor())

    try:
        await redeemer.initialize()
        await redeemer.check_login_status()
        await connect_and_listen(catchup_limit=cli_args.catchup)
    finally:
        lockout_task.cancel()
        try:
            await lockout_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:
            pass
        try:
            await redeemer.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[bold yellow][!] Bot stopped by user.[/bold yellow]")
    except Exception as e:
        console.print(f"\n[bold red][!] Unhandled Error: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        input("\nPress Enter to exit...")
