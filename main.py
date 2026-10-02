import os
import sys
import json
import asyncio
from datetime import datetime, timezone
from typing import Set, Dict, Any, List
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

load_dotenv()

console = Console()

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


async def process_single_item(item_type: str, identifier: str, extra: str = ""):
    if identifier in claimed_items:
        console.print(f"[dim]↷ Skipping already cached {item_type}: {identifier}[/dim]")
        return

    # Check if account is on active Binance cooldown
    is_locked, remaining_s, remaining_str = redeemer.is_locked_out()
    if is_locked:
        console.print(f"[bold red]⏳ Account on Binance Lockout! Cannot claim '{identifier}'. Time remaining: {remaining_str}. (Skipped)[/bold red]")
        return

    if item_type == "code":
        console.print(f"[bold gold1]⚡ Claiming Crypto Box Code: [bold white]{identifier}[/bold white][/bold gold1]")
        res = await redeemer.claim_crypto_box_code(identifier)
        status = res.get("status", "")

        if status in ["success", "expired", "already_claimed", "invalid"]:
            claimed_items.add(identifier)
            save_claimed_cache(claimed_items)
        elif status == "rate_limited":
            rem_str = redeemer.get_lockout_remaining_str()
            console.print(Panel(
                f"[bold red]🚫 BINANCE RATE LIMIT / LOCKOUT ACTIVATED[/bold red]\n"
                f"[bold white]Code '[bold yellow]{identifier}[/bold yellow]' was not claimed and will NOT be cached.[/bold white]\n"
                f"[bold yellow]Bot is pausing claims for {rem_str} to protect your account.[/bold yellow]",
                title="[bold red]Rate Limit Alert[/bold red]",
                border_style="red"
            ))
        else:
            console.print(f"[bold yellow][!] Code '{identifier}' returned status '{status}' ({res.get('message')}). Not cached.[/bold yellow]")

    elif item_type == "square":
        console.print(f"[bold gold1]⚡ Claiming Binance Square Post: [bold white]{identifier}[/bold white] (Answer: [bold yellow]{extra}[/bold yellow])[/bold gold1]")
        res = await redeemer.claim_binance_square_red_packet(identifier, extra)
        status = res.get("status", "")

        if status in ["success", "submitted", "opened", "expired", "already_claimed", "invalid"]:
            claimed_items.add(identifier)
            save_claimed_cache(claimed_items)
        elif status == "rate_limited":
            rem_str = redeemer.get_lockout_remaining_str()
            console.print(f"[bold red]🚫 Lockout active ({rem_str} remaining). Square post '{identifier}' held.[/bold red]")
        else:
            console.print(f"[bold yellow][!] Square post '{identifier}' returned '{status}'. Not cached.[/bold yellow]")

    elif item_type == "url":
        console.print(f"[bold gold1]⚡ Opening Red Packet Link: [bold white]{identifier}[/bold white][/bold gold1]")
        res = await redeemer.claim_red_packet_url(identifier)
        status = res.get("status", "")

        if status in ["success", "opened", "expired", "already_claimed", "invalid"]:
            claimed_items.add(identifier)
            save_claimed_cache(claimed_items)
        elif status == "rate_limited":
            rem_str = redeemer.get_lockout_remaining_str()
            console.print(f"[bold red]🚫 Lockout active ({rem_str} remaining). Link '{identifier}' held.[/bold red]")
        else:
            console.print(f"[bold yellow][!] Link '{identifier}' returned '{status}'. Not cached.[/bold yellow]")


def determine_sweep_limits(channel_name: str) -> tuple[int, int]:
    ch_lower = channel_name.lower()
    if "cryptobox" in ch_lower or "parser" in ch_lower:
        return 20, 0
    elif "freereward" in ch_lower:
        return 15, 5
    else:
        return 15, 5


async def scan_and_claim_history(channel_entities: List[Any]):
    console.print(Panel(
        "[bold cyan]🔍 Starting Intelligent Channel History Sweep...[/bold cyan]\n"
        f"[bold white]• Freshness Policy:[/bold white] Only drops < {MAX_FRESH_CODE_AGE_SECONDS // 60} minutes old are claimed.\n"
        "[bold white]• Anti-Ban Protection:[/bold white] Stale historical codes are auto-cached (skipped) to prevent Binance bruteforce lockouts.",
        title="[bold yellow]Targeted Catch-Up Mode[/bold yellow]"
    ))

    now = datetime.now(timezone.utc)
    fresh_codes: List[str] = []
    fresh_questions: List[Dict[str, str]] = []
    stale_codes_indexed = 0

    for entity in channel_entities:
        chat_name = str(entity)
        try:
            chat = await client.get_entity(entity)
            chat_name = getattr(chat, 'title', getattr(chat, 'username', str(entity)))
        except Exception:
            pass

        code_limit, question_limit = determine_sweep_limits(chat_name)
        console.print(f"[cyan][+] Scanning recent messages from '[bold white]{chat_name}[/bold white]'...[/cyan]")

        try:
            async for msg in client.iter_messages(entity, limit=100):
                if not msg.raw_text or not msg.date:
                    continue

                msg_age_seconds = (now - msg.date).total_seconds()
                is_fresh = msg_age_seconds <= MAX_FRESH_CODE_AGE_SECONDS

                parsed = parse_telegram_message(msg.raw_text)

                for c in parsed.get("codes", []):
                    if is_fresh:
                        if c not in fresh_codes and c not in claimed_items and len(fresh_codes) < code_limit:
                            fresh_codes.append(c)
                    else:
                        if c not in claimed_items:
                            claimed_items.add(c)
                            stale_codes_indexed += 1

                sq_urls = parsed.get("square_urls", [])
                answers = parsed.get("answers", [])
                if sq_urls and answers and question_limit > 0:
                    url = sq_urls[0]
                    ans = answers[0]
                    if is_fresh:
                        if not any(q["url"] == url for q in fresh_questions) and url not in claimed_items and len(fresh_questions) < question_limit:
                            fresh_questions.append({"url": url, "answer": ans})
                    else:
                        if url not in claimed_items:
                            claimed_items.add(url)
                            stale_codes_indexed += 1

        except Exception as e:
            console.print(f"[yellow][!] Notice while scanning history from {chat_name}: {e}[/yellow]")

    # Persist the newly pre-cached stale items to protect the session
    if stale_codes_indexed > 0:
        save_claimed_cache(claimed_items)
        console.print(f"[dim green][✓] Pre-cached {stale_codes_indexed} expired historical drops to prevent dead-code attempts.[/dim green]")

    history_table = Table(title=f"📋 History Sweep Summary ({len(fresh_codes)} Fresh Codes, {len(fresh_questions)} Fresh Questions)", show_header=True, header_style="bold magenta")
    history_table.add_column("#", style="dim", width=4)
    history_table.add_column("Type", style="cyan", width=12)
    history_table.add_column("Item / Code / URL", style="bold white")
    history_table.add_column("Detail", style="bold yellow")
    history_table.add_column("Status", style="bold")

    idx = 1
    for c in fresh_codes:
        history_table.add_row(str(idx), "Crypto Box", c, "< 3 mins old", "[bold green]Ready To Claim[/bold green]")
        idx += 1

    for q in fresh_questions:
        history_table.add_row(str(idx), "Square Post", q["url"], q["answer"], "[bold green]Ready To Claim[/bold green]")
        idx += 1

    if idx == 1:
        history_table.add_row("-", "All Clear", "No unhandled fresh drops in channel history", "-", "[dim]Up to date[/dim]")

    console.print(history_table)

    # Process only verified fresh items
    if fresh_codes:
        console.print(f"\n[bold cyan]▶ Attempting to claim {len(fresh_codes)} fresh historical codes...[/bold cyan]")
        for c in fresh_codes:
            await process_single_item("code", c)

    if fresh_questions:
        console.print(f"\n[bold cyan]▶ Attempting to claim {len(fresh_questions)} fresh historical questions...[/bold cyan]")
        for q in fresh_questions:
            await process_single_item("square", q["url"], q["answer"])

    console.print("\n[bold green][✓] History scan completed smoothly![/bold green]\n")


@client.on(events.NewMessage(chats=TARGET_CHANNELS))
async def live_message_handler(event):
    try:
        chat = await event.get_chat()
        chat_name = getattr(chat, 'title', getattr(chat, 'username', 'Channel'))
    except Exception:
        chat_name = "Channel"

    message_text = event.raw_text
    console.print(Panel(message_text, title=f"[bold green]📩 New Drop from {chat_name}[/bold green]", border_style="green"))

    # Freshness verification
    if event.message and event.message.date:
        now = datetime.now(timezone.utc)
        age = (now - event.message.date).total_seconds()
        if age > MAX_FRESH_CODE_AGE_SECONDS:
            console.print(f"[dim yellow]↷ Skipping stale live drop ({int(age)}s old) to protect account against dead-code bans.[/dim yellow]\n")
            parsed = parse_telegram_message(message_text)
            for c in parsed.get("codes", []):
                claimed_items.add(c)
            save_claimed_cache(claimed_items)
            return

    parsed = parse_telegram_message(message_text)
    codes = parsed.get("codes", [])
    square_urls = parsed.get("square_urls", [])
    red_packet_urls = parsed.get("red_packet_urls", [])
    answers = parsed.get("answers", [])

    if not codes and not square_urls and not red_packet_urls:
        console.print("[dim][i] Post received, but no red packet codes or reward links found.[/dim]\n")
        return

    # Check lockout before dispatching
    is_locked, remaining_s, remaining_str = redeemer.is_locked_out()
    if is_locked:
        console.print(f"[bold red]⏳ Account currently in Binance lockout ({remaining_str} remaining). Holding live drops.[/bold red]\n")
        return

    for sq_url in square_urls:
        ans = answers[0] if answers else ""
        await process_single_item("square", sq_url, ans)

    for code in codes:
        await process_single_item("code", code)

    for rp_url in red_packet_urls:
        await process_single_item("url", rp_url)


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


async def connect_and_listen():
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
            await scan_and_claim_history(resolved_entities)

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


async def main():
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
    table.add_row("Lockout Status", lockout_status)
    table.add_row("Auto-Reconnect Ladder", "30s → 1m → 3m → 5m → 10m → 20m → 30m → 45m")
    console.print(table)

    if is_locked:
        console.print(Panel(
            f"[bold red]⚠️ ACTIVE BINANCE RATE LIMIT DETECTED[/bold red]\n"
            f"[bold white]Your Binance account is on cooldown ({remaining_str} remaining).[/bold white]\n"
            f"[bold yellow]The bot is running in stealth listener mode. Claims will automatically resume once the lockout expires.[/bold yellow]",
            title="[bold yellow]Protection Mode Active[/bold yellow]",
            border_style="yellow"
        ))

    try:
        await redeemer.initialize()
        await redeemer.check_login_status()
        await connect_and_listen()
    finally:
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
