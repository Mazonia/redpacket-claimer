import os
import sys
import json
import asyncio
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
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "").strip()
HEADLESS_MODE = os.getenv("HEADLESS", "false").lower() == "true"

if not API_ID or not API_HASH or not TARGET_CHANNEL:
    console.print("[bold red][!] ERROR: TELEGRAM_API_ID, TELEGRAM_API_HASH, and TARGET_CHANNEL must be set in your .env file.[/bold red]")
    exit(1)

CACHE_FILE = os.path.abspath("./claimed_cache.json")

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

client = TelegramClient('binance_session', int(API_ID), API_HASH)
redeemer = BinanceRedeemer(headless=HEADLESS_MODE)
claimed_items: Set[str] = load_claimed_cache()

async def process_single_item(item_type: str, identifier: str, extra: str = ""):
    if identifier in claimed_items:
        console.print(f"[dim]↷ Skipping already processed {item_type}: {identifier}[/dim]")
        return

    if item_type == "code":
        console.print(f"[bold gold1]⚡ Claiming Crypto Box Code: [bold white]{identifier}[/bold white][/bold gold1]")
        res = await redeemer.claim_crypto_box_code(identifier)
        claimed_items.add(identifier)
        save_claimed_cache(claimed_items)

    elif item_type == "square":
        console.print(f"[bold gold1]⚡ Claiming Binance Square Post: [bold white]{identifier}[/bold white] (Answer: [bold yellow]{extra}[/bold yellow])[/bold gold1]")
        res = await redeemer.claim_binance_square_red_packet(identifier, extra)
        claimed_items.add(identifier)
        save_claimed_cache(claimed_items)

    elif item_type == "url":
        console.print(f"[bold gold1]⚡ Opening Red Packet Link: [bold white]{identifier}[/bold white][/bold gold1]")
        res = await redeemer.claim_red_packet_url(identifier)
        claimed_items.add(identifier)
        save_claimed_cache(claimed_items)

async def scan_and_claim_history(channel_entity, code_limit: int = 100, question_limit: int = 5):
    console.print(Panel(
        f"[bold cyan]🔍 Scanning channel history ({TARGET_CHANNEL}) for the last {code_limit} Red Packet codes and {question_limit} questions...[/bold cyan]",
        title="[bold yellow]100-Code Historical Sweep Mode[/bold yellow]"
    ))

    recent_codes: List[str] = []
    recent_questions: List[Dict[str, str]] = []

    async for msg in client.iter_messages(channel_entity, limit=800):
        if not msg.raw_text:
            continue
        parsed = parse_telegram_message(msg.raw_text)

        for c in parsed.get("codes", []):
            if c not in recent_codes and len(recent_codes) < code_limit:
                recent_codes.append(c)

        sq_urls = parsed.get("square_urls", [])
        answers = parsed.get("answers", [])
        if sq_urls and answers:
            url = sq_urls[0]
            ans = answers[0]
            if not any(q["url"] == url for q in recent_questions) and len(recent_questions) < question_limit:
                recent_questions.append({"url": url, "answer": ans})

        if len(recent_codes) >= code_limit and len(recent_questions) >= question_limit:
            break

    uncached_codes = [c for c in recent_codes if c not in claimed_items]
    history_table = Table(title=f"📋 Channel History Summary ({len(recent_codes)} Codes Found, {len(uncached_codes)} New To Claim)", show_header=True, header_style="bold magenta")
    history_table.add_column("#", style="dim", width=4)
    history_table.add_column("Type", style="cyan", width=12)
    history_table.add_column("Item / Code / URL", style="bold white")
    history_table.add_column("Detail", style="bold yellow")
    history_table.add_column("Status", style="bold")

    idx = 1
    for c in recent_codes:
        status = "[dim]Cached (Skipped)[/dim]" if c in claimed_items else "[bold green]Ready To Claim[/bold green]"
        history_table.add_row(str(idx), "Crypto Box", c, "-", status)
        idx += 1

    for q in recent_questions:
        status = "[dim]Cached (Skipped)[/dim]" if q["url"] in claimed_items else "[bold green]Ready To Claim[/bold green]"
        history_table.add_row(str(idx), "Square Post", q["url"], q["answer"], status)
        idx += 1

    console.print(history_table)

    if recent_codes:
        console.print(f"\n[bold cyan]▶ Sweeping {len(recent_codes)} historical codes...[/bold cyan]")
        for c in recent_codes:
            await process_single_item("code", c)

    if recent_questions:
        console.print(f"\n[bold cyan]▶ Sweeping {len(recent_questions)} historical questions...[/bold cyan]")
        for q in recent_questions:
            await process_single_item("square", q["url"], q["answer"])

    console.print("\n[bold green][✓] Historical 100-code sweep completed![/bold green]\n")

@client.on(events.NewMessage(chats=TARGET_CHANNEL))
async def live_message_handler(event):
    message_text = event.raw_text
    console.print(Panel(message_text, title=f"[bold green]📩 New Telegram Drop from {TARGET_CHANNEL}[/bold green]", border_style="green"))
    
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
        await process_single_item("square", sq_url, ans)

    for code in codes:
        await process_single_item("code", code)

    for rp_url in red_packet_urls:
        await process_single_item("url", rp_url)

async def main():
    table = Table(title="🚀 Binance Red Packet & Feed Auto-Claimer (100-Code Sweep Mode)", show_header=True, header_style="bold magenta")
    table.add_column("Setting", style="dim", width=25)
    table.add_column("Value", style="bold green")
    table.add_row("Target Channel", TARGET_CHANNEL)
    table.add_row("Browser Mode", "Headless" if HEADLESS_MODE else "Visible (Headful)")
    table.add_row("Redemption URL", "https://www.binance.com/en/my/wallet/account/payment/cryptobox")
    table.add_row("Session Directory", "./user_data")
    table.add_row("Cached Items", str(len(claimed_items)))
    console.print(table)

    await redeemer.initialize()
    await redeemer.check_login_status()

    console.print(f"\n[bold cyan][+] Connecting to Telegram...[/bold cyan]")
    await client.start(phone=phone_callback)
    console.print(f"[bold green][✓] Telegram connected successfully![/bold green]")

    try:
        channel_entity = await client.get_entity(TARGET_CHANNEL)
    except Exception as e:
        console.print(f"[bold red][!] Error resolving channel {TARGET_CHANNEL}: {e}[/bold red]")
        channel_entity = TARGET_CHANNEL

    await scan_and_claim_history(channel_entity, code_limit=100, question_limit=5)

    console.print(f"[bold gold1]📡 100-code sweep finished! Bot is now actively listening for live drops from {TARGET_CHANNEL}... (Press Ctrl+C to stop)[/bold gold1]\n")
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[bold yellow][!] Bot stopped by user.[/bold yellow]")
