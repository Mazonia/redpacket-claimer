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
TARGET_CHANNEL_RAW = os.getenv("TARGET_CHANNEL", "").strip()
HEADLESS_MODE = os.getenv("HEADLESS", "false").lower() == "true"

TARGET_CHANNELS = [c.strip() for c in TARGET_CHANNEL_RAW.split(",") if c.strip()]

if not API_ID or not API_HASH or not TARGET_CHANNELS:
    console.print("[bold red][!] ERROR: TELEGRAM_API_ID, TELEGRAM_API_HASH, and TARGET_CHANNEL must be set in your .env file.[/bold red]")
    input("\nPress Enter to exit...")
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

def determine_sweep_limits(channel_name: str) -> tuple[int, int]:
    ch_lower = channel_name.lower()
    if "cryptobox" in ch_lower or "parser" in ch_lower:
        return 15, 0
    elif "freereward" in ch_lower:
        return 10, 5
    else:
        return 10, 5

async def scan_and_claim_history(channel_entities: List[Any]):
    console.print(Panel(
        "[bold cyan]🔍 Starting Per-Channel Historical Sweep...[/bold cyan]\n"
        "[bold white]• Cryptobox Parser:[/bold white] Recent 15 codes\n"
        "[bold white]• Freerewardes:[/bold white] Recent 10 codes & 5 questions",
        title="[bold yellow]Targeted Catch-Up Mode[/bold yellow]"
    ))

    all_recent_codes: List[str] = []
    all_recent_questions: List[Dict[str, str]] = []

    for entity in channel_entities:
        chat_name = str(entity)
        try:
            chat = await client.get_entity(entity)
            chat_name = getattr(chat, 'title', getattr(chat, 'username', str(entity)))
        except Exception:
            pass

        code_limit, question_limit = determine_sweep_limits(chat_name)
        console.print(f"[cyan][+] Scanning recent history from '[bold white]{chat_name}[/bold white]' (Target: {code_limit} codes, {question_limit} questions)...[/cyan]")

        ch_codes: List[str] = []
        ch_questions: List[Dict[str, str]] = []

        try:
            async for msg in client.iter_messages(entity, limit=200):
                if not msg.raw_text:
                    continue
                parsed = parse_telegram_message(msg.raw_text)

                for c in parsed.get("codes", []):
                    if c not in ch_codes and len(ch_codes) < code_limit:
                        ch_codes.append(c)

                sq_urls = parsed.get("square_urls", [])
                answers = parsed.get("answers", [])
                if sq_urls and answers and question_limit > 0:
                    url = sq_urls[0]
                    ans = answers[0]
                    if not any(q["url"] == url for q in ch_questions) and len(ch_questions) < question_limit:
                        ch_questions.append({"url": url, "answer": ans})

                if len(ch_codes) >= code_limit and (question_limit == 0 or len(ch_questions) >= question_limit):
                    break
        except Exception as e:
            console.print(f"[yellow][!] Notice while scanning history from {chat_name}: {e}[/yellow]")

        for c in ch_codes:
            if c not in all_recent_codes:
                all_recent_codes.append(c)

        for q in ch_questions:
            if not any(item["url"] == q["url"] for item in all_recent_questions):
                all_recent_questions.append(q)

    uncached_codes = [c for c in all_recent_codes if c not in claimed_items]
    history_table = Table(title=f"📋 Sweep Summary ({len(all_recent_codes)} Total Codes Found, {len(uncached_codes)} New To Claim)", show_header=True, header_style="bold magenta")
    history_table.add_column("#", style="dim", width=4)
    history_table.add_column("Type", style="cyan", width=12)
    history_table.add_column("Item / Code / URL", style="bold white")
    history_table.add_column("Detail", style="bold yellow")
    history_table.add_column("Status", style="bold")

    idx = 1
    for c in all_recent_codes:
        status = "[dim]Cached (Skipped)[/dim]" if c in claimed_items else "[bold green]Ready To Claim[/bold green]"
        history_table.add_row(str(idx), "Crypto Box", c, "-", status)
        idx += 1

    for q in all_recent_questions:
        status = "[dim]Cached (Skipped)[/dim]" if q["url"] in claimed_items else "[bold green]Ready To Claim[/bold green]"
        history_table.add_row(str(idx), "Square Post", q["url"], q["answer"], status)
        idx += 1

    console.print(history_table)

    if all_recent_codes:
        console.print(f"\n[bold cyan]▶ Attempting to claim {len(all_recent_codes)} historical codes...[/bold cyan]")
        for c in all_recent_codes:
            await process_single_item("code", c)

    if all_recent_questions:
        console.print(f"\n[bold cyan]▶ Attempting to claim {len(all_recent_questions)} historical questions...[/bold cyan]")
        for q in all_recent_questions:
            await process_single_item("square", q["url"], q["answer"])

    console.print("\n[bold green][✓] Targeted historical sweep completed![/bold green]\n")

@client.on(events.NewMessage(chats=TARGET_CHANNELS))
async def live_message_handler(event):
    try:
        chat = await event.get_chat()
        chat_name = getattr(chat, 'title', getattr(chat, 'username', 'Channel'))
    except Exception:
        chat_name = "Channel"

    message_text = event.raw_text
    console.print(Panel(message_text, title=f"[bold green]📩 New Drop from {chat_name}[/bold green]", border_style="green"))
    
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
    table = Table(title="🚀 Binance Red Packet & Feed Auto-Claimer", show_header=True, header_style="bold magenta")
    table.add_column("Setting", style="dim", width=25)
    table.add_column("Value", style="bold green")
    table.add_row("Target Channels", ", ".join(TARGET_CHANNELS))
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

    resolved_entities = []
    for ch in TARGET_CHANNELS:
        try:
            entity = await client.get_entity(ch)
            resolved_entities.append(entity)
        except Exception as e:
            console.print(f"[yellow][!] Notice: Could not resolve channel '{ch}' directly, using raw handle: {e}[/yellow]")
            resolved_entities.append(ch)

    await scan_and_claim_history(resolved_entities)

    console.print(f"[bold gold1]📡 Bot is actively listening for live drops on: {', '.join(TARGET_CHANNELS)}... (Press Ctrl+C to stop)[/bold gold1]\n")
    await client.run_until_disconnected()

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
