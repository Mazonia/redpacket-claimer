import os
import sys
import re
import json
import time
import asyncio
import random
from typing import Optional, List, Dict, Any, Tuple
from playwright.async_api import async_playwright, BrowserContext, Page
from rich.console import Console

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console()
USER_DATA_DIR = os.path.abspath("./user_data")
LOCKOUT_STATE_FILE = os.path.abspath("./user_data/lockout_state.json")

# Binance Official Crypto Box Redemption URL
CRYPTO_BOX_URL = "https://www.binance.com/en/my/wallet/account/payment/cryptobox"


def parse_lockout_duration(text: str) -> int:
    """
    Extracts hours, minutes, and seconds from Binance rate limit / lockout text.
    E.g. 'Please try again in 04 hour(s) and 19 minute(s).' -> 15540 seconds
    """
    hours = 0
    minutes = 0
    seconds = 0

    h_match = re.search(r'(\d+)\s*hour', text, re.IGNORECASE)
    m_match = re.search(r'(\d+)\s*(?:minute|min)', text, re.IGNORECASE)
    s_match = re.search(r'(\d+)\s*(?:second|sec)', text, re.IGNORECASE)

    if h_match:
        hours = int(h_match.group(1))
    if m_match:
        minutes = int(m_match.group(1))
    if s_match:
        seconds = int(s_match.group(1))

    total = hours * 3600 + minutes * 60 + seconds
    # Default to 5 minutes (300s) if a lockout is triggered without explicit numbers (avoiding excessive 4hr bans)
    return total if total > 0 else 300


def format_duration(seconds: int) -> str:
    """Formats seconds into human-readable duration string."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d} hour(s) and {m:02d} minute(s)"
    elif m > 0:
        return f"{m:02d} minute(s) and {s:02d} second(s)"
    else:
        return f"{s:02d} second(s)"


class BinanceRedeemer:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._pw = None
        self._lock = asyncio.Lock()
        self.consecutive_failures = 0
        self.lockout_until = self._load_lockout()

    def _load_lockout(self) -> float:
        """Loads saved lockout expiration timestamp from disk if active."""
        if os.path.exists(LOCKOUT_STATE_FILE):
            try:
                with open(LOCKOUT_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    until = data.get("lockout_until", 0.0)
                    if until > time.time():
                        return float(until)
            except Exception:
                pass
        return 0.0

    def _save_lockout(self, until: float, reason: str = ""):
        """Persists lockout expiration timestamp to disk."""
        try:
            os.makedirs(os.path.dirname(LOCKOUT_STATE_FILE), exist_ok=True)
            with open(LOCKOUT_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "lockout_until": until,
                    "reason": reason,
                    "updated_at": time.time()
                }, f, indent=2)
        except Exception:
            pass

    def set_lockout(self, duration_seconds: float, reason: str = ""):
        """Activates lockout cooldown timer and saves state."""
        self.lockout_until = time.time() + duration_seconds + 30  # Add 30s buffer
        self._save_lockout(self.lockout_until, reason)

    def is_locked_out(self) -> Tuple[bool, int, str]:
        """
        Checks if the account is currently on Binance lockout / rate limit cooldown.
        Returns (is_locked, remaining_seconds, human_readable_time).
        """
        if self.lockout_until > time.time():
            remaining = int(self.lockout_until - time.time())
            return True, remaining, format_duration(remaining)
        return False, 0, ""

    def get_lockout_remaining_str(self) -> str:
        """Returns remaining lockout duration string or empty string if not locked out."""
        is_locked, _, rem_str = self.is_locked_out()
        return rem_str if is_locked else ""

    def clear_lockout(self):
        """Clears active lockout state."""
        self.lockout_until = 0.0
        try:
            if os.path.exists(LOCKOUT_STATE_FILE):
                os.remove(LOCKOUT_STATE_FILE)
        except Exception:
            pass

    async def _handle_circuit_breaker(self):
        """
        Increments failure counter. If 4 consecutive expired/invalid codes occur,
        triggers a 75-second protective pause to prevent Binance bruteforce lockouts.
        """
        self.consecutive_failures += 1
        if self.consecutive_failures >= 4:
            cooldown_time = 75
            console.print(f"\n[bold yellow]🛡️ [CIRCUIT BREAKER] {self.consecutive_failures} consecutive dead/invalid codes detected![/bold yellow]")
            console.print(f"[bold yellow]🛡️ Pausing claims for {cooldown_time}s to protect your account against Binance anti-bruteforce lockouts...[/bold yellow]\n")
            await asyncio.sleep(cooldown_time)
            self.consecutive_failures = 0
        else:
            await self._human_delay(2.5, 4.0)

    def _reset_circuit_breaker(self):
        """Resets consecutive failures counter upon any successful claim."""
        self.consecutive_failures = 0

    async def _human_delay(self, min_s: float = 0.5, max_s: float = 1.5):
        """Randomized delay to emulate natural human interaction."""
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def _human_type(self, element, text: str):
        """Types text character by character with humanized random pauses, ensuring field is completely cleared first."""
        try:
            try:
                await element.click(timeout=1500)
            except Exception:
                pass
            
            if self.page:
                try:
                    await self.page.keyboard.press("Control+A")
                    await self.page.keyboard.press("Backspace")
                except Exception:
                    pass

            await element.fill("")
            await asyncio.sleep(0.05)

            for char in text:
                await element.type(char, delay=random.uniform(50, 120))
                await asyncio.sleep(random.uniform(0.01, 0.03))
        except Exception:
            # Fallback direct fill if typing encounters any issue
            await element.fill(text)

    async def _random_mouse_jitter(self):
        """Emulates subtle human mouse movements."""
        if not self.page:
            return
        try:
            x = random.randint(300, 700)
            y = random.randint(300, 500)
            await self.page.mouse.move(x, y, steps=random.randint(2, 5))
        except Exception:
            pass

    async def _is_500_error_page(self) -> bool:
        """Detects if Binance is displaying a 500 error / 'something went wrong' page."""
        if not self.page:
            return False
        try:
            home_btn = await self.page.query_selector('button:has-text("Go to Home"), a:has-text("Go to Home"), div[role="button"]:has-text("Go to Home")')
            if home_btn and await home_btn.is_visible():
                return True

            body_text = await self.page.evaluate("() => document.body ? document.body.innerText : ''")
            text_lower = body_text.lower()

            if "500" in body_text and ("something went wrong" in text_lower or "we're sorry" in text_lower or "go to home" in text_lower):
                return True
            if "internal server error" in text_lower or "502 bad gateway" in text_lower or "503 service unavailable" in text_lower or "504 gateway time-out" in text_lower:
                return True
        except Exception:
            pass
        return False

    async def _recover_from_500_error(self, target_url: str = CRYPTO_BOX_URL, max_retries: int = 4) -> bool:
        """
        If a 500 error page is detected, automatically refreshes and re-navigates
        until the page loads cleanly or max_retries is reached.
        """
        if not await self._is_500_error_page():
            return True

        for attempt in range(1, max_retries + 1):
            console.print(f"[bold yellow][!] Binance 500 Error detected! Auto-recovering session (Attempt {attempt}/{max_retries})...[/bold yellow]")
            await asyncio.sleep(1.5 * attempt)
            try:
                response = await self.page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1.5)
                
                if response and response.status >= 500:
                    continue

                if not await self._is_500_error_page():
                    console.print(f"[bold green][✓] Successfully recovered from Binance 500 error page![/bold green]")
                    return True
            except Exception as e:
                console.print(f"[dim yellow][!] Recovery attempt {attempt} notice: {e}[/dim yellow]")

        is_still_error = await self._is_500_error_page()
        if is_still_error:
            console.print("[bold red][!] Could not clear Binance 500 error screen after multiple retries.[/bold red]")
        return not is_still_error

    async def _dismiss_modals(self):
        """
        Thoroughly closes any modal, openbox, expired banner, or backdrop.
        Uses button clicking, Escape key, and DOM cleanup if needed.
        Also clears 500 error pages automatically.
        """
        if not self.page:
            return
        
        # Check and recover from 500 error page if currently active
        if await self._is_500_error_page():
            await self._recover_from_500_error(CRYPTO_BOX_URL)
            
        try:
            # 1. Look for close / dismiss buttons
            close_selectors = [
                '.openbox button',
                '.openbox [class*="close"]',
                '.openbox svg',
                'button:has-text("OK")',
                'button:has-text("Confirm")',
                'button:has-text("Got it")',
                'button:has-text("Close")',
                'button:has-text("Cancel")',
                'button[aria-label="Close"]',
                '.bn-modal-close',
                'svg[class*="close"]',
                'div[class*="close"]'
            ]
            for sel in close_selectors:
                try:
                    btns = await self.page.query_selector_all(sel)
                    for btn in btns:
                        if btn and await btn.is_visible():
                            await btn.click(timeout=1000)
                            await asyncio.sleep(0.2)
                except Exception:
                    pass

            # 2. Press Escape key
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.2)

            # 3. If modal, mask, or toast is still present in DOM, forcefully remove it so it cannot block clicks or pollute feedback
            await self.page.evaluate("""() => {
                const lingering = document.querySelectorAll('.bn-mask, .bn-modal, .openbox, [role="presentation"].bn-mask, .toast, .bn-toast, .bn-feedback');
                lingering.forEach(el => el.remove());
            }""")
            await asyncio.sleep(0.2)
        except Exception:
            pass

    def _cleanup_stale_locks(self):
        """Removes orphaned lock files and terminates lingering Chromium processes using USER_DATA_DIR."""
        for lock_name in ["lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"]:
            lock_path = os.path.join(USER_DATA_DIR, lock_name)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except Exception:
                    pass

        if sys.platform == "win32":
            try:
                import subprocess
                ps_script = """
                Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'chrome' -or $_.Name -match 'msedge' } | ForEach-Object {
                    if ($_.CommandLine -and ($_.CommandLine -match 'user_data' -or $_.CommandLine -match 'ms-playwright')) {
                        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                    }
                }
                """
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, timeout=5)
                for lock_name in ["lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"]:
                    lock_path = os.path.join(USER_DATA_DIR, lock_name)
                    if os.path.exists(lock_path):
                        try:
                            os.remove(lock_path)
                        except Exception:
                            pass
            except Exception:
                pass

    async def initialize(self):
        """Starts Playwright with persistent context so login session and cookies persist."""
        if self.context:
            return

        self._cleanup_stale_locks()
        self._pw = await async_playwright().start()
        console.print(f"[bold cyan][+] Launching Playwright browser (Headless: {self.headless})...[/bold cyan]")
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        
        try:
            self.context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR,
                headless=self.headless,
                viewport={"width": 1280, "height": 850},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--window-size=1280,850"
                ]
            )
        except Exception as e:
            if "existing browser session" in str(e).lower() or "process cannot access" in str(e).lower():
                console.print("[dim yellow][!] Stale browser session detected. Auto-recovering profile...[/dim yellow]")
                self._cleanup_stale_locks()
                await asyncio.sleep(1.0)
                self.context = await self._pw.chromium.launch_persistent_context(
                    user_data_dir=USER_DATA_DIR,
                    headless=self.headless,
                    viewport={"width": 1280, "height": 850},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-infobars",
                        "--window-size=1280,850"
                    ]
                )
            else:
                raise e

        self.page = await self.context.new_page()
        # Set default action timeout to 6 seconds instead of 30 seconds to never freeze
        self.page.set_default_timeout(6000)
        console.print("[bold green][✓] Persistent browser session ready![/bold green]")

    async def check_login_status(self):
        """Navigates to Binance and verifies active login session."""
        if not self.page:
            await self.initialize()
            
        console.print(f"[cyan][+] Checking session at {CRYPTO_BOX_URL}...[/cyan]")
        try:
            await self.page.goto(CRYPTO_BOX_URL, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2.5)
            
            if await self._is_500_error_page():
                await self._recover_from_500_error(CRYPTO_BOX_URL)

            current_url = self.page.url.lower()
            is_login_page = "login" in current_url or "accounts.binance" in current_url
            login_btn = await self.page.query_selector('a:has-text("Log In"), button:has-text("Log In")')

            if is_login_page or login_btn:
                console.print("\n[bold yellow]===========================================================[/bold yellow]")
                console.print("[bold yellow][!] ACTION REQUIRED: Please log into Binance in the opened window.[/bold yellow]")
                console.print("[bold yellow][!] Complete 2FA/login. Your session will be saved permanently![/bold yellow]")
                console.print("[bold yellow]===========================================================[/bold yellow]\n")
                if not self.headless:
                    while True:
                        await asyncio.sleep(3)
                        cur_url = self.page.url.lower()
                        if "login" not in cur_url and "accounts.binance" not in cur_url:
                            has_login = await self.page.query_selector('a:has-text("Log In"), button:has-text("Log In")')
                            if not has_login:
                                console.print("[bold green][✓] Login detected successfully![/bold green]")
                                break
            else:
                console.print("[bold green][✓] Active Binance session detected! Ready to auto-claim.[/bold green]")
        except Exception as e:
            console.print(f"[yellow][!] Initial navigation notice: {e}[/yellow]")
            if await self._is_500_error_page():
                await self._recover_from_500_error(CRYPTO_BOX_URL)

    async def _find_crypto_box_input(self):
        """Attempts to find the Crypto Box code input field with tab check."""
        if await self._is_500_error_page():
            await self._recover_from_500_error(CRYPTO_BOX_URL)

        input_selectors = [
            'input[placeholder*="Red Packet" i]',
            'input[placeholder*="Crypto Box" i]',
            'input[placeholder*="code" i]',
            'input[placeholder*="Box" i]',
            'input[name="code"]',
            'input[type="text"]'
        ]

        # Ensure "Receive" tab is active if present
        receive_selectors = [
            'div[role="tab"]:has-text("Receive")',
            'button:has-text("Receive")',
            'div:has-text("Receive")'
        ]
        for r_sel in receive_selectors:
            try:
                tab = await self.page.query_selector(r_sel)
                if tab and await tab.is_visible():
                    await tab.click(timeout=1000)
                    await asyncio.sleep(0.3)
                    break
            except Exception:
                pass

        for sel in input_selectors:
            try:
                el = await self.page.wait_for_selector(sel, state="visible", timeout=2000)
                if el:
                    return el
            except Exception:
                continue

        return None

    async def _extract_page_feedback(self) -> Dict[str, Any]:
        """
        Examines inline form error messages, dialogs, modals, toasts, and DOM text
        to accurately classify the result of a redemption attempt.
        Only inspects VISIBLE elements to prevent false positives from stale DOM nodes.
        """
        if not self.page:
            return {"status": "no_page", "message": "No active browser page"}

        try:
            raw_feedback = await self.page.evaluate("""() => {
                const texts = [];
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none' && 
                           style.visibility !== 'hidden' && 
                           style.opacity !== '0' && 
                           (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
                };

                // 1. Check known feedback / form error selector containers
                const selectors = [
                    '.bn-form-item-explain',
                    '.bn-form-item-error',
                    '.bn-feedback',
                    '.toast',
                    '.bn-toast',
                    '.bn-modal',
                    '.openbox',
                    '[role="alert"]',
                    '[role="dialog"]',
                    'div[class*="error" i]',
                    'div[class*="feedback" i]',
                    'div[class*="tip" i]',
                    'div[class*="notice" i]',
                    'div[class*="message" i]',
                    'div[class*="warning" i]',
                    'div[class*="Toast" i]'
                ];

                for (const sel of selectors) {
                    try {
                        const elements = document.querySelectorAll(sel);
                        elements.forEach(el => {
                            if (isVisible(el) && el.innerText && el.innerText.trim()) {
                                texts.push(el.innerText.trim());
                            }
                        });
                    } catch (e) {}
                }

                // 2. Check input container and its parents (captures inline form validation errors)
                const input = document.querySelector('input[type="text"], input[name="code"], input[placeholder*="code" i], input[placeholder*="Crypto" i]');
                if (input) {
                    let parent = input.parentElement;
                    for (let i = 0; i < 5 && parent; i++) {
                        if (isVisible(parent)) {
                            const pText = (parent.innerText || '').trim();
                            if (pText && (
                                pText.includes('exceeded') || 
                                pText.includes('attempt') || 
                                pText.includes('try again') || 
                                pText.includes('invalid') || 
                                pText.includes('expired') || 
                                pText.includes('claimed') || 
                                pText.includes('exist')
                            )) {
                                texts.push(pText);
                            }
                        }
                        parent = parent.parentElement;
                    }
                }

                return texts.join('\\n');
            }""")
        except Exception:
            raw_feedback = ""

        text_lower = raw_feedback.lower()

        # 1. Rate Limit / Maximum Attempts Lockout
        if (
            "exceeded the maximum attempts" in text_lower or
            "maximum attempts" in text_lower or
            "try again in" in text_lower or
            "too many attempts" in text_lower or
            "frequency limit" in text_lower or
            "temporarily restricted" in text_lower or
            "rate limit" in text_lower
        ):
            lockout_msg = ""
            for line in raw_feedback.split("\n"):
                l_low = line.lower()
                if "exceeded" in l_low or "attempts" in l_low or "try again" in l_low or "limit" in l_low:
                    lockout_msg = line.strip()
                    break
            if not lockout_msg:
                lockout_msg = raw_feedback[:120].strip()

            duration = parse_lockout_duration(raw_feedback)

            return {
                "status": "rate_limited",
                "message": lockout_msg,
                "retry_after": duration
            }

        # 2. Expired / Fully Claimed
        if (
            "expired" in text_lower or
            "fully claimed" in text_lower or
            "has been claimed" in text_lower or
            "all rewards have been claimed" in text_lower or
            "this crypto box has ended" in text_lower or
            "crypto box has ended" in text_lower or
            "the crypto box is empty" in text_lower or
            "box is empty" in text_lower or
            "already ended" in text_lower
        ):
            return {
                "status": "expired",
                "message": "Expired or fully claimed"
            }

        # 3. Already Claimed
        if (
            "already claimed" in text_lower or
            "claimed it already" in text_lower or
            "cannot claim twice" in text_lower or
            "you have already" in text_lower
        ):
            return {
                "status": "already_claimed",
                "message": "Already claimed"
            }

        # 4. Invalid Code
        if (
            "invalid" in text_lower or
            "does not exist" in text_lower or
            "incorrect code" in text_lower or
            "please enter a valid code" in text_lower or
            "code not found" in text_lower
        ):
            return {
                "status": "invalid",
                "message": "Invalid code"
            }

        # 5. Server Error
        if (
            "something went wrong" in text_lower or
            "500" in text_lower or
            "internal server error" in text_lower or
            "service unavailable" in text_lower
        ):
            return {
                "status": "server_error",
                "message": "Binance server error"
            }

        # 6. Unrecognized / Unknown text
        if raw_feedback.strip():
            clean_snippet = raw_feedback.replace('\n', ' ').strip()
            return {
                "status": "unknown",
                "message": clean_snippet[:100]
            }

        return {
            "status": "no_response",
            "message": "No response text detected"
        }

    async def claim_crypto_box_code(self, code: str, max_attempts: int = 3) -> Dict[str, Any]:
        """
        Navigates to Binance Crypto Box page and claims the 8-character code.
        Guaranteed single-threaded execution using asyncio.Lock to prevent typing collisions.
        Includes full rate-limit lockout detection, circuit breaker, and automatic 500 error recovery.
        """
        async with self._lock:
            # Check lockout before making any browser calls
            is_locked, remaining_s, remaining_str = self.is_locked_out()
            if is_locked:
                console.print(f"[bold red]⏳ Account on Binance Lockout! Cannot claim '{code}'. Time remaining: {remaining_str}. (Skipping)[/bold red]")
                return {
                    "code": code,
                    "status": "rate_limited",
                    "message": f"Binance lockout active: {remaining_str} remaining",
                    "retry_after": remaining_s
                }

            if not self.page:
                await self.initialize()

            result = {"code": code, "status": "failed", "message": ""}

            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        console.print(f"[bold cyan]🔄 Retrying code '{code}' (Attempt {attempt}/{max_attempts})...[/bold cyan]")

                    # 1. Check & Recover from any existing 500 Error
                    if await self._is_500_error_page():
                        recovered = await self._recover_from_500_error(CRYPTO_BOX_URL)
                        if not recovered:
                            result["status"] = "server_error"
                            result["message"] = "Binance 500 Server Error"
                            if attempt < max_attempts:
                                await asyncio.sleep(2.0)
                                continue
                            else:
                                return result

                    console.print(f"[bold magenta][➔] Opening Crypto Box page to claim code: [bold yellow]{code}[/bold yellow]...[/bold magenta]")
                    
                    # Dismiss any lingering popups from previous codes
                    await self._dismiss_modals()

                    # If not on target page or if an unclosable modal was lingering, reload cleanly
                    needs_reload = False
                    if CRYPTO_BOX_URL not in self.page.url:
                        res = await self.page.goto(CRYPTO_BOX_URL, wait_until="domcontentloaded", timeout=12000)
                        if res and res.status >= 500:
                            needs_reload = True
                        await self._human_delay(1.0, 1.8)
                    else:
                        lingering = await self.page.query_selector('.openbox, .bn-mask')
                        if lingering:
                            needs_reload = True

                    if needs_reload or await self._is_500_error_page():
                        await self._recover_from_500_error(CRYPTO_BOX_URL)

                    # Locate input field
                    input_field = await self._find_crypto_box_input()

                    # If still not found, do a quick clean reload or 500 recovery
                    if not input_field:
                        if await self._is_500_error_page():
                            await self._recover_from_500_error(CRYPTO_BOX_URL)
                            input_field = await self._find_crypto_box_input()
                        else:
                            console.print("[dim yellow][i] Refreshing page to load Crypto Box form...[/dim yellow]")
                            await self.page.goto(CRYPTO_BOX_URL, wait_until="domcontentloaded", timeout=12000)
                            await self._human_delay(1.2, 2.0)
                            input_field = await self._find_crypto_box_input()

                    if not input_field:
                        if await self._is_500_error_page():
                            result["status"] = "server_error"
                            result["message"] = "Binance 500 Server Error"
                        else:
                            console.print("[bold red][!] Code input field not found on page.[/bold red]")
                            result["message"] = "Input field not found"

                        if attempt < max_attempts:
                            await asyncio.sleep(2.0)
                            continue

                        await self._dismiss_modals()
                        return result

                    # Click & enter code (use force=True fallback if anything attempts to intercept)
                    try:
                        await input_field.click(timeout=2500)
                    except Exception:
                        await self._dismiss_modals()
                        await input_field.click(timeout=2000, force=True)

                    await self._human_delay(0.2, 0.4)
                    await self._human_type(input_field, code)
                    await self._human_delay(0.3, 0.6)

                    # Find & click Claim button
                    claim_selectors = [
                        'button:has-text("Claim Now")',
                        'button:has-text("Claim")',
                        'button:has-text("Redeem")',
                        'button[type="submit"]',
                        'div[role="button"]:has-text("Claim")'
                    ]
                    
                    claim_btn = None
                    for c_sel in claim_selectors:
                        try:
                            btn = await self.page.wait_for_selector(c_sel, state="visible", timeout=1500)
                            if btn:
                                claim_btn = btn
                                break
                        except Exception:
                            continue

                    if not claim_btn:
                        if await self._is_500_error_page():
                            result["status"] = "server_error"
                            result["message"] = "Binance 500 Server Error"
                        else:
                            console.print("[bold red][!] Claim button not found on page.[/bold red]")
                            result["message"] = "Claim button not found"

                        if attempt < max_attempts:
                            await asyncio.sleep(2.0)
                            continue

                        await self._dismiss_modals()
                        return result

                    try:
                        await claim_btn.click(timeout=2500)
                    except Exception:
                        await claim_btn.click(timeout=2000, force=True)

                    console.print(f"[bold green][✓] Clicked Claim for code '{code}'. Awaiting response...[/bold green]")
                    await self._human_delay(1.5, 2.5)

                    # Check if clicking Claim triggered a 500 Error page
                    if await self._is_500_error_page():
                        console.print(f"[bold yellow][!] Claiming code '{code}' triggered a 500 error page! Recovering...[/bold yellow]")
                        await self._recover_from_500_error(CRYPTO_BOX_URL)
                        result["status"] = "server_error"
                        result["message"] = "Binance 500 Server Error on submission"
                        if attempt < max_attempts:
                            await asyncio.sleep(2.0)
                            continue
                        return result

                    # 1. Check for "Open" modal button (valid un-claimed packet)
                    open_selectors = [
                        'button:has-text("Open")',
                        '.openbox button:has-text("Open")',
                        '.openbox div[role="button"]:has-text("Open")',
                        'div[role="button"]:has-text("Open")'
                    ]
                    opened = False
                    for o_sel in open_selectors:
                        try:
                            open_btn = await self.page.wait_for_selector(o_sel, state="visible", timeout=2000)
                            if open_btn:
                                try:
                                    await open_btn.click(timeout=2000)
                                except Exception:
                                    await open_btn.click(timeout=1500, force=True)
                                await self._human_delay(1.2, 2.0)
                                console.print(f"[bold gold1]🎉 [SUCCESS] Successfully opened Red Packet '{code}'![/bold gold1]")
                                result["status"] = "success"
                                result["message"] = "Red Packet opened"
                                self.clear_lockout()
                                self._reset_circuit_breaker()
                                opened = True
                                break
                        except Exception:
                            pass

                    if not opened:
                        # 2. Check for feedback (Rate limit / Expired / Already Claimed / Invalid)
                        fb = await self._extract_page_feedback()
                        status = fb.get("status", "unknown")
                        fb_msg = fb.get("message", "")

                        if status == "rate_limited":
                            duration = fb.get("retry_after") or parse_lockout_duration(fb_msg)
                            self.set_lockout(duration, fb_msg)
                            rem_str = self.get_lockout_remaining_str()
                            console.print(f"[bold red]🚫 BINANCE RATE LIMIT DETECTED: {fb_msg}[/bold red]")
                            console.print(f"[bold red]⏳ Auto-claimer is paused. Cooldown expires in: {rem_str}[/bold red]")
                            result["status"] = "rate_limited"
                            result["message"] = fb_msg
                            result["retry_after"] = duration
                            await self._dismiss_modals()
                            return result

                        elif status == "expired":
                            self.clear_lockout()
                            console.print(f"[yellow][i] Code '{code}' is EXPIRED or fully claimed by others.[/yellow]")
                            result["status"] = "expired"
                            result["message"] = "Expired or fully claimed"
                            await self._handle_circuit_breaker()

                        elif status == "already_claimed":
                            self.clear_lockout()
                            console.print(f"[yellow][i] You have already claimed code '{code}'.[/yellow]")
                            result["status"] = "already_claimed"
                            result["message"] = "Already claimed"
                            await self._human_delay(1.0, 2.0)

                        elif status == "invalid":
                            self.clear_lockout()
                            console.print(f"[red][!] Code '{code}' is invalid.[/red]")
                            result["status"] = "invalid"
                            result["message"] = "Invalid code"
                            await self._handle_circuit_breaker()

                        elif status == "server_error":
                            console.print(f"[bold yellow][!] Server error response for code '{code}'.[/bold yellow]")
                            result["status"] = "server_error"
                            result["message"] = fb_msg

                        else:
                            console.print(f"[bold dim][i] Code '{code}' response: {fb_msg if fb_msg else 'Done'}.[/bold dim]")
                            result["status"] = "unknown"
                            result["message"] = fb_msg or "Done"

                    # Dismiss popup dialogs immediately so the next code has a clean canvas
                    await self._dismiss_modals()

                    # Ensure page is NOT left on a 500 error screen
                    if await self._is_500_error_page():
                        await self._recover_from_500_error(CRYPTO_BOX_URL)

                    # Natural stealth pause before next code
                    if result["status"] == "success":
                        await self._human_delay(1.5, 3.0)
                    return result

                except Exception as e:
                    console.print(f"[bold red][!] Error while claiming code {code} (Attempt {attempt}/{max_attempts}): {e}[/bold red]")
                    result["message"] = str(e)
                    if await self._is_500_error_page():
                        result["status"] = "server_error"
                        await self._recover_from_500_error(CRYPTO_BOX_URL)

                    await self._dismiss_modals()
                    if attempt < max_attempts:
                        await asyncio.sleep(2.0)
                    else:
                        return result

            # Final cleanup check
            if await self._is_500_error_page():
                await self._recover_from_500_error(CRYPTO_BOX_URL)

            return result

    async def claim_binance_square_red_packet(self, post_url: str, answer: str, max_attempts: int = 3) -> Dict[str, Any]:
        """
        Automates claiming a Binance Square Question/Answer Red Packet post.
        Navigates to post, fills the extracted answer into the answer/comment box, and claims.
        Guaranteed single-threaded execution using asyncio.Lock.
        """
        async with self._lock:
            is_locked, remaining_s, remaining_str = self.is_locked_out()
            if is_locked:
                console.print(f"[bold red]⏳ Account on Binance Lockout! Cannot claim Square post. Time remaining: {remaining_str}. (Skipping)[/bold red]")
                return {
                    "url": post_url,
                    "answer": answer,
                    "status": "rate_limited",
                    "message": f"Binance lockout active: {remaining_str} remaining",
                    "retry_after": remaining_s
                }

            if not self.page:
                await self.initialize()

            result = {"url": post_url, "answer": answer, "status": "failed", "message": ""}

            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        console.print(f"[bold cyan]🔄 Retrying Square post '{post_url}' (Attempt {attempt}/{max_attempts})...[/bold cyan]")

                    if await self._is_500_error_page():
                        await self._recover_from_500_error(post_url)

                    console.print(f"[bold magenta][➔] Opening Binance Square Post: {post_url}[/bold magenta]")
                    console.print(f"[bold gold1]🔑 Submitting Answer: '{answer}'[/bold gold1]")

                    await self._dismiss_modals()
                    response = await self.page.goto(post_url, wait_until="domcontentloaded", timeout=20000)
                    await self._human_delay(2.0, 3.5)

                    if (response and response.status >= 500) or await self._is_500_error_page():
                        console.print("[yellow][!] 500 Error encountered loading Binance Square post. Recovering...[/yellow]")
                        recovered = await self._recover_from_500_error(post_url)
                        if not recovered:
                            result["status"] = "server_error"
                            result["message"] = "Binance 500 Server Error"
                            if attempt < max_attempts:
                                await asyncio.sleep(2.0)
                                continue
                            return result

                    input_selectors = [
                        'input[placeholder*="answer" i]',
                        'input[placeholder*="Red Packet" i]',
                        'input[placeholder*="Code" i]',
                        'textarea[placeholder*="comment" i]',
                        'textarea[placeholder*="Write a comment" i]',
                        'div[contenteditable="true"]',
                        'textarea',
                        'input[type="text"]'
                    ]

                    input_field = None
                    for sel in input_selectors:
                        try:
                            el = await self.page.wait_for_selector(sel, state="visible", timeout=3000)
                            if el:
                                input_field = el
                                break
                        except Exception:
                            continue

                    if not input_field:
                        console.print("[yellow][!] Answer/Comment input field not found on post page.[/yellow]")
                        result["message"] = "Input not found"
                        if attempt < max_attempts:
                            await asyncio.sleep(2.0)
                            continue
                        await self._dismiss_modals()
                        return result

                    try:
                        await input_field.click(timeout=2500)
                    except Exception:
                        await input_field.click(timeout=2000, force=True)

                    await self._human_delay(0.3, 0.6)

                    tag_name = await input_field.evaluate("el => el.tagName.toLowerCase()")
                    if tag_name == "div":
                        await input_field.evaluate(f"el => el.innerText = '{answer}'")
                    else:
                        await self._human_type(input_field, answer)

                    await self._human_delay(0.5, 1.0)

                    submit_selectors = [
                        'button:has-text("Claim")',
                        'button:has-text("Claim Now")',
                        'button:has-text("Submit")',
                        'button:has-text("Comment")',
                        'button:has-text("Send")',
                        'div[role="button"]:has-text("Claim")'
                    ]

                    submit_btn = None
                    for s_sel in submit_selectors:
                        try:
                            btn = await self.page.wait_for_selector(s_sel, state="visible", timeout=2500)
                            if btn:
                                submit_btn = btn
                                break
                        except Exception:
                            continue

                    if submit_btn:
                        try:
                            await submit_btn.click(timeout=2500)
                        except Exception:
                            await submit_btn.click(timeout=2000, force=True)

                        console.print(f"[bold green][✓] Answer '{answer}' submitted to post.[/bold green]")
                        await self._human_delay(1.5, 2.5)

                        if await self._is_500_error_page():
                            console.print("[yellow][!] 500 Error after submitting answer. Recovering...[/yellow]")
                            await self._recover_from_500_error(post_url)
                            result["status"] = "server_error"
                            result["message"] = "Binance 500 Server Error"
                            if attempt < max_attempts:
                                await asyncio.sleep(2.0)
                                continue
                            return result

                        try:
                            open_btn = await self.page.wait_for_selector('button:has-text("Open"), div[role="button"]:has-text("Open")', state="visible", timeout=3000)
                            if open_btn:
                                await open_btn.click(timeout=2000, force=True)
                                console.print(f"[bold gold1]🎉 [SUCCESS] Red Packet Opened for post {post_url}![/bold gold1]")
                                result["status"] = "success"
                                result["message"] = "Red Packet opened"
                                self.clear_lockout()
                                self._reset_circuit_breaker()
                                await self._dismiss_modals()
                                await self._human_delay(1.8, 3.5)
                                return result
                        except Exception:
                            pass

                        self.clear_lockout()
                        result["status"] = "submitted"
                        result["message"] = "Answer submitted"
                    else:
                        console.print("[yellow][!] Could not find Submit/Claim button.[/yellow]")
                        result["message"] = "Submit button not found"

                    await self._dismiss_modals()
                    await self._human_delay(1.8, 3.5)
                    return result

                except Exception as e:
                    console.print(f"[bold red][!] Error on Binance Square post (Attempt {attempt}/{max_attempts}): {e}[/bold red]")
                    result["message"] = str(e)
                    if await self._is_500_error_page():
                        result["status"] = "server_error"
                        await self._recover_from_500_error(post_url)
                    await self._dismiss_modals()
                    if attempt < max_attempts:
                        await asyncio.sleep(2.0)
                    else:
                        return result

            return result

    async def claim_red_packet_url(self, url: str, max_attempts: int = 3) -> Dict[str, Any]:
        """Navigates to direct s.binance.com red packet links and auto-clicks Open. Single-threaded via asyncio.Lock."""
        async with self._lock:
            is_locked, remaining_s, remaining_str = self.is_locked_out()
            if is_locked:
                console.print(f"[bold red]⏳ Account on Binance Lockout! Cannot open link. Time remaining: {remaining_str}. (Skipping)[/bold red]")
                return {
                    "url": url,
                    "status": "rate_limited",
                    "message": f"Binance lockout active: {remaining_str} remaining",
                    "retry_after": remaining_s
                }

            if not self.page:
                await self.initialize()

            result = {"url": url, "status": "failed", "message": ""}
            for attempt in range(1, max_attempts + 1):
                try:
                    if await self._is_500_error_page():
                        await self._recover_from_500_error(url)

                    console.print(f"[bold magenta][➔] Opening Direct Red Packet Link: {url}[/bold magenta]")
                    await self._dismiss_modals()
                    response = await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    await self._human_delay(1.5, 2.5)

                    if (response and response.status >= 500) or await self._is_500_error_page():
                        console.print("[yellow][!] 500 Error loading Red Packet link. Recovering...[/yellow]")
                        await self._recover_from_500_error(url)
                        result["status"] = "server_error"
                        if attempt < max_attempts:
                            await asyncio.sleep(2.0)
                            continue
                        return result

                    try:
                        open_btn = await self.page.wait_for_selector('button:has-text("Open"), button:has-text("Claim"), div[role="button"]:has-text("Open")', state="visible", timeout=3000)
                        if open_btn:
                            await open_btn.click(timeout=2000, force=True)
                            console.print(f"[bold gold1]🎉 [SUCCESS] Clicked Open on Red Packet link![/bold gold1]")
                            result["status"] = "success"
                            self.clear_lockout()
                            self._reset_circuit_breaker()
                            await self._dismiss_modals()
                        else:
                            self.clear_lockout()
                            result["status"] = "opened"
                    except Exception:
                        self.clear_lockout()
                        result["status"] = "opened"

                    return result
                except Exception as e:
                    console.print(f"[bold red][!] Error opening Red Packet link (Attempt {attempt}/{max_attempts}): {e}[/bold red]")
                    result["message"] = str(e)
                    if attempt < max_attempts:
                        await asyncio.sleep(2.0)
                    else:
                        return result

            return result

    async def close(self):
        if self.context:
            await self.context.close()
        if self._pw:
            await self._pw.stop()
