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

    async def _is_error_page(self) -> bool:
        """
        Detects if Binance or Chromium is displaying an error screen:
        - HTTP 500, 502, 503, 504 server error
        - "Something went wrong" / "Go to Home"
        - Chrome offline / connection errors (ERR_INTERNET_DISCONNECTED, ERR_NAME_NOT_RESOLVED,
          ERR_CONNECTION_RESET, ERR_CONNECTION_TIMED_OUT, etc.)
        - chrome-error:// pages
        """
        if not self.page:
            return False
        try:
            url = (self.page.url or "").lower()
            if "chrome-error://" in url or "chromewebdata" in url:
                return True

            home_btn = await self.page.query_selector('button:has-text("Go to Home"), a:has-text("Go to Home"), div[role="button"]:has-text("Go to Home")')
            if home_btn and await home_btn.is_visible():
                return True

            body_text = await self.page.evaluate("() => document.body ? document.body.innerText : ''")
            text_lower = body_text.lower()

            # Network disconnection & offline signatures
            network_errors = [
                "no internet",
                "this site can’t be reached",
                "this site cannot be reached",
                "err_internet_disconnected",
                "err_connection_reset",
                "err_name_not_resolved",
                "err_connection_timed_out",
                "err_connection_refused",
                "err_network_changed",
                "err_empty_response",
                "dns_probe_finished_no_internet",
                "check your internet connection",
                "check your network",
            ]
            for err in network_errors:
                if err in text_lower:
                    return True

            # Server error signatures
            server_errors = [
                "internal server error",
                "502 bad gateway",
                "503 service unavailable",
                "504 gateway time-out",
                "504 gateway timeout",
                "something went wrong",
                "we're sorry",
            ]
            for err in server_errors:
                if err in text_lower:
                    return True

            if "500" in body_text and ("something went wrong" in text_lower or "we're sorry" in text_lower or "go to home" in text_lower or "error" in text_lower):
                return True
        except Exception:
            pass
        return False

    async def _is_500_error_page(self) -> bool:
        """Backward compatibility alias for _is_error_page."""
        return await self._is_error_page()

    async def _recover_from_error(self, target_url: str = CRYPTO_BOX_URL, max_retries: int = 4) -> bool:
        """
        If a 500 or network error page is detected, automatically refreshes and re-navigates
        with progressive backoff until the page loads cleanly or max_retries is reached.
        """
        if not await self._is_error_page():
            return True

        for attempt in range(1, max_retries + 1):
            console.print(f"[bold yellow][!] Binance Network/Server Error detected! Auto-recovering session (Attempt {attempt}/{max_retries})...[/bold yellow]")
            await asyncio.sleep(2.0 * attempt)
            try:
                response = await self.page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(1.5)
                
                if response and response.status >= 500:
                    continue

                if not await self._is_error_page():
                    console.print(f"[bold green][✓] Successfully recovered from error page![/bold green]")
                    return True
            except Exception as e:
                console.print(f"[dim yellow][!] Recovery attempt {attempt} notice: {e}[/dim yellow]")

        is_still_error = await self._is_error_page()
        if is_still_error:
            console.print("[bold red][!] Could not clear Binance error screen after multiple retries. Waiting for connection...[/bold red]")
        return not is_still_error

    async def _recover_from_500_error(self, target_url: str = CRYPTO_BOX_URL, max_retries: int = 4) -> bool:
        """Backward compatibility alias for _recover_from_error."""
        return await self._recover_from_error(target_url, max_retries)

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
        """Removes orphaned lock files and terminates ONLY lingering Chromium processes explicitly bound to OUR USER_DATA_DIR."""
        for lock_name in ["lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"]:
            lock_path = os.path.join(USER_DATA_DIR, lock_name)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except Exception:
                    pass

        # Strictly terminate ONLY processes that have our exact USER_DATA_DIR in their commandline.
        # This guarantees zero interference with the user's personal Chrome/Edge, trading bots,
        # or other Playwright instances running on the system.
        target_dir = os.path.abspath(USER_DATA_DIR).lower()
        try:
            import psutil
            for p in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = p.info.get('cmdline') or []
                    cmd_str = " ".join(cmdline).lower()
                    if target_dir in cmd_str:
                        p.terminate()
                        try:
                            p.wait(timeout=1.0)
                        except Exception:
                            p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                except Exception:
                    pass
        except Exception:
            pass

        for lock_name in ["lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"]:
            lock_path = os.path.join(USER_DATA_DIR, lock_name)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
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
        # Set default action timeout to 10 seconds to give unstable/laggy connections enough buffer
        self.page.set_default_timeout(10000)
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
        if await self._is_error_page():
            await self._recover_from_error(CRYPTO_BOX_URL)

        input_selectors = [
            'input[placeholder*="Red Packet" i]',
            'input[placeholder*="Crypto Box" i]',
            'input[placeholder*="code" i]',
            'input[placeholder*="Box" i]',
            'input[name="code"]',
            'main input[type="text"]',
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
                el = await self.page.wait_for_selector(sel, state="visible", timeout=3500)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue

        return None

    async def _extract_page_feedback(self) -> Dict[str, Any]:
        """
        Examines inline form error messages, dialogs, modals, toasts, and DOM text
        to accurately classify the result of a redemption attempt.
        Filters out page chrome, headers, footers, and language/currency noise (e.g. 'English English USD-$').
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

                const isInsideHeaderOrNav = (el) => {
                    let cur = el;
                    while (cur && cur !== document.body) {
                        const tag = (cur.tagName || '').toLowerCase();
                        const cls = (cur.className || '').toString().toLowerCase();
                        const role = (cur.getAttribute('role') || '').toLowerCase();
                        if (tag === 'header' || tag === 'nav' || tag === 'footer' || 
                            cls.includes('header') || cls.includes('navbar') || cls.includes('footer') ||
                            role === 'navigation') {
                            return true;
                        }
                        cur = cur.parentElement;
                    }
                    return false;
                };

                const IGNORED_WORDS = ['english', 'usd', 'theme', 'dark', 'light', 'download', 'app', 'cookie', 'preferences', 'terms', 'privacy'];
                const isNoise = (str) => {
                    if (!str || str.length < 2) return true;
                    const words = str.toLowerCase().replace(/[^a-z0-9 ]/g, ' ').split(/\\s+/).filter(Boolean);
                    if (words.length === 0) return true;
                    return words.every(w => IGNORED_WORDS.includes(w) || !isNaN(w));
                };

                // 1. Check known feedback / form error selector containers (excluding header/nav/footer)
                const selectors = [
                    '.bn-form-item-explain',
                    '.bn-form-item-error',
                    '.bn-feedback',
                    '.toast',
                    '.bn-toast',
                    '.openbox',
                    '.bn-modal',
                    '[role="alert"]',
                    'div[class*="error" i]',
                    'div[class*="feedback" i]',
                    'div[class*="Toast" i]'
                ];

                for (const sel of selectors) {
                    try {
                        const elements = document.querySelectorAll(sel);
                        elements.forEach(el => {
                            if (isVisible(el) && !isInsideHeaderOrNav(el) && el.innerText && el.innerText.trim()) {
                                const clean = el.innerText.trim();
                                if (!isNoise(clean)) {
                                    texts.push(clean);
                                }
                            }
                        });
                    } catch (e) {}
                }

                // 2. Check input container and its parents (captures inline form validation errors)
                const input = document.querySelector('input[type="text"], input[name="code"], input[placeholder*="code" i], input[placeholder*="Crypto" i]');
                if (input) {
                    let parent = input.parentElement;
                    for (let i = 0; i < 5 && parent; i++) {
                        if (isVisible(parent) && !isInsideHeaderOrNav(parent)) {
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
                                if (!isNoise(pText)) {
                                    texts.push(pText);
                                }
                            }
                        }
                        parent = parent.parentElement;
                    }
                }

                return texts.join('\\n');
            }""")
        except Exception:
            raw_feedback = ""

        if not isinstance(raw_feedback, str):
            raw_feedback = str(raw_feedback or "")

        # Filter out noise in Python as second-level defense
        lower_words = re.findall(r'[a-zA-Z]+', raw_feedback.lower())
        noise_dict = {"english", "usd", "theme", "dark", "light", "download", "app", "cookie", "preferences", "terms", "privacy", "copyright"}
        if lower_words and all(w in noise_dict for w in lower_words):
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

        # 6. Unrecognized / Unknown text (only if meaningful)
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

    async def _wait_for_claim_outcome(self, code: str, timeout_seconds: float = 12.0) -> Dict[str, Any]:
        """
        Intelligently awaits the outcome of clicking 'Claim' over unstable/slow internet.
        Polls actively up to timeout_seconds:
        1. Checks for 'Open' button (packet ready to open).
        2. Checks for genuine Binance feedback (expired, claimed, invalid, rate limited).
        3. Checks for 500 error / offline page.
        4. Detects in-flight / loading spinner states and continues waiting.
        """
        start_time = time.time()
        open_selectors = [
            'button:has-text("Open")',
            '.openbox button:has-text("Open")',
            '.openbox div[role="button"]:has-text("Open")',
            'div[role="button"]:has-text("Open")',
            '.openbox button',
        ]

        while time.time() - start_time < timeout_seconds:
            # 1. Check if an error screen appeared
            if await self._is_error_page():
                return {"status": "server_error", "message": "Binance Error Screen detected"}

            # 2. Check for "Open" modal button (valid un-claimed packet)
            for o_sel in open_selectors:
                try:
                    open_btn = await self.page.query_selector(o_sel)
                    if open_btn and await open_btn.is_visible():
                        try:
                            await open_btn.click(timeout=2500)
                        except Exception:
                            await open_btn.click(timeout=2000, force=True)
                        await self._human_delay(1.2, 2.0)
                        console.print(f"[bold gold1]🎉 [SUCCESS] Successfully opened Red Packet '{code}'![/bold gold1]")
                        return {"status": "success", "message": "Red Packet opened"}
                except Exception:
                    pass

            # 3. Check for genuine Crypto Box feedback
            fb = await self._extract_page_feedback()
            status = fb.get("status", "unknown")

            if status in ["rate_limited", "expired", "already_claimed", "invalid", "server_error"]:
                return fb

            # 4. Check if claim button is still in a loading / spinning / disabled state
            is_loading = False
            try:
                is_loading = await self.page.evaluate("""() => {
                    const claimBtn = document.querySelector('button[type="submit"]') ||
                                     Array.from(document.querySelectorAll('button')).find(b => (b.innerText || '').includes('Claim'));
                    if (!claimBtn) return false;
                    const hasSpin = claimBtn.querySelector('svg, .bn-loading, [class*="spin" i], [class*="loading" i]');
                    const isDisabled = claimBtn.disabled || claimBtn.getAttribute('aria-disabled') === 'true' || claimBtn.classList.contains('is-loading');
                    return !!(hasSpin || isDisabled);
                }""")
            except Exception:
                pass

            if is_loading:
                # Request is still traveling across slow internet, keep waiting
                await asyncio.sleep(0.35)
                continue

            # 5. If feedback is unknown with text, give it a moment to stabilize
            if status == "unknown" and fb.get("message") and (time.time() - start_time >= 3.0):
                return fb

            await asyncio.sleep(0.35)

        # Timeout reached with no conclusive result
        return {
            "status": "network_timeout",
            "message": f"Binance response timed out after {int(timeout_seconds)}s (poor/unstable internet)"
        }

    async def claim_crypto_box_code(self, code: str, max_attempts: int = 3) -> Dict[str, Any]:
        """
        Navigates to Binance Crypto Box page and claims the 8-character code.
        Guaranteed single-threaded execution using asyncio.Lock to prevent typing collisions.
        Includes full rate-limit lockout detection, circuit breaker, and automatic network/500 recovery.
        Avoids redundant page reloads to operate reliably over poor and high-latency internet.
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

                    # 1. Check & Recover from any existing Error page
                    if await self._is_error_page():
                        recovered = await self._recover_from_error(CRYPTO_BOX_URL)
                        if not recovered:
                            result["status"] = "server_error"
                            result["message"] = "Binance Network/Server Error"
                            if attempt < max_attempts:
                                await asyncio.sleep(2.0)
                                continue
                            return result

                    console.print(f"[bold magenta][➔] Opening Crypto Box page to claim code: [bold yellow]{code}[/bold yellow]...[/bold magenta]")
                    
                    # Dismiss any lingering popups from previous codes
                    await self._dismiss_modals()

                    # Optimize page navigation: if already on CRYPTO_BOX_URL and input field is ready, DO NOT reload!
                    input_field = None
                    is_err = await self._is_error_page()

                    if not is_err and self.page and CRYPTO_BOX_URL in self.page.url:
                        input_field = await self._find_crypto_box_input()

                    if not input_field or is_err:
                        if is_err:
                            await self._recover_from_error(CRYPTO_BOX_URL)
                        else:
                            try:
                                await self.page.goto(CRYPTO_BOX_URL, wait_until="domcontentloaded", timeout=25000)
                                await self._human_delay(0.8, 1.5)
                            except Exception as e:
                                console.print(f"[dim yellow][!] Navigation notice ({e}), attempting error recovery...[/dim yellow]")
                                await self._recover_from_error(CRYPTO_BOX_URL)

                        input_field = await self._find_crypto_box_input()

                    if not input_field:
                        if await self._is_error_page():
                            await self._recover_from_error(CRYPTO_BOX_URL)
                            input_field = await self._find_crypto_box_input()

                    if not input_field:
                        console.print("[bold red][!] Code input field not found on page.[/bold red]")
                        result["status"] = "input_not_found"
                        result["message"] = "Input field not found"
                        if attempt < max_attempts:
                            await asyncio.sleep(2.0)
                            continue
                        await self._dismiss_modals()
                        return result

                    # Click & enter code (use force=True fallback if anything attempts to intercept)
                    try:
                        await input_field.click(timeout=3000)
                    except Exception:
                        await self._dismiss_modals()
                        await input_field.click(timeout=2500, force=True)

                    await self._human_delay(0.2, 0.4)
                    await self._human_type(input_field, code)
                    await self._human_delay(0.2, 0.4)

                    # Find & click Claim button (with generous timeout for slow JS hydration)
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
                            btn = await self.page.wait_for_selector(c_sel, state="visible", timeout=3500)
                            if btn and await btn.is_visible():
                                claim_btn = btn
                                break
                        except Exception:
                            continue

                    if not claim_btn:
                        if await self._is_error_page():
                            result["status"] = "server_error"
                            result["message"] = "Binance Error on page"
                        else:
                            console.print("[bold red][!] Claim button not found on page.[/bold red]")
                            result["status"] = "button_not_found"
                            result["message"] = "Claim button not found"

                        if attempt < max_attempts:
                            await asyncio.sleep(2.0)
                            continue

                        await self._dismiss_modals()
                        return result

                    try:
                        await claim_btn.click(timeout=3000)
                    except Exception:
                        await claim_btn.click(timeout=2500, force=True)

                    console.print(f"[bold green][✓] Clicked Claim for code '{code}'. Awaiting response...[/bold green]")

                    # Intelligent outcome awaiter designed for bad internet
                    outcome = await self._wait_for_claim_outcome(code, timeout_seconds=12.0)
                    status = outcome.get("status", "unknown")
                    fb_msg = outcome.get("message", "")

                    if status == "success":
                        result["status"] = "success"
                        result["message"] = "Red Packet opened"
                        self.clear_lockout()
                        self._reset_circuit_breaker()
                        await self._dismiss_modals()
                        await self._human_delay(1.5, 3.0)
                        return result

                    elif status == "rate_limited":
                        duration = outcome.get("retry_after") or parse_lockout_duration(fb_msg)
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
                        await self._dismiss_modals()
                        return result

                    elif status == "already_claimed":
                        self.clear_lockout()
                        console.print(f"[yellow][i] You have already claimed code '{code}'.[/yellow]")
                        result["status"] = "already_claimed"
                        result["message"] = "Already claimed"
                        await self._dismiss_modals()
                        await self._human_delay(1.0, 2.0)
                        return result

                    elif status == "invalid":
                        self.clear_lockout()
                        console.print(f"[red][!] Code '{code}' is invalid.[/red]")
                        result["status"] = "invalid"
                        result["message"] = "Invalid code"
                        await self._handle_circuit_breaker()
                        await self._dismiss_modals()
                        return result

                    elif status == "server_error":
                        console.print(f"[bold yellow][!] Server/Network error response for code '{code}'.[/bold yellow]")
                        result["status"] = "server_error"
                        result["message"] = fb_msg
                        if await self._is_error_page():
                            await self._recover_from_error(CRYPTO_BOX_URL)
                        if attempt < max_attempts:
                            console.print(f"[bold cyan]🔄 Retrying code '{code}' after error recovery (Attempt {attempt + 1}/{max_attempts})...[/bold cyan]")
                            await asyncio.sleep(2.0)
                            continue
                        await self._dismiss_modals()
                        return result

                    elif status == "network_timeout":
                        console.print(f"[bold yellow][!] Network timeout waiting for response on code '{code}' (poor internet).[/bold yellow]")
                        result["status"] = "network_timeout"
                        result["message"] = fb_msg
                        if await self._is_error_page():
                            await self._recover_from_error(CRYPTO_BOX_URL)
                        if attempt < max_attempts:
                            console.print(f"[bold cyan]🔄 Retrying code '{code}' (Attempt {attempt + 1}/{max_attempts})...[/bold cyan]")
                            await asyncio.sleep(2.0)
                            continue
                        await self._dismiss_modals()
                        return result

                    else:
                        console.print(f"[bold dim][i] Code '{code}' response: {fb_msg if fb_msg else 'No clear response'}.[/bold dim]")
                        result["status"] = "unknown"
                        result["message"] = fb_msg or "Unknown response"
                        if attempt < max_attempts:
                            console.print(f"[bold cyan]🔄 Retrying code '{code}' (Attempt {attempt + 1}/{max_attempts})...[/bold cyan]")
                            await self._dismiss_modals()
                            await asyncio.sleep(2.0)
                            continue
                        await self._dismiss_modals()
                        return result

                except Exception as e:
                    console.print(f"[bold red][!] Error while claiming code {code} (Attempt {attempt}/{max_attempts}): {e}[/bold red]")
                    result["message"] = str(e)
                    if await self._is_error_page():
                        result["status"] = "server_error"
                        await self._recover_from_error(CRYPTO_BOX_URL)

                    await self._dismiss_modals()
                    if attempt < max_attempts:
                        await asyncio.sleep(2.0)
                        continue
                    else:
                        return result

            # Final cleanup check
            if await self._is_error_page():
                await self._recover_from_error(CRYPTO_BOX_URL)

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

                    if await self._is_error_page():
                        await self._recover_from_error(post_url)

                    console.print(f"[bold magenta][➔] Opening Binance Square Post: {post_url}[/bold magenta]")
                    console.print(f"[bold gold1]🔑 Submitting Answer: '{answer}'[/bold gold1]")

                    await self._dismiss_modals()
                    response = await self.page.goto(post_url, wait_until="domcontentloaded", timeout=25000)
                    await self._human_delay(2.0, 3.5)

                    if (response and response.status >= 500) or await self._is_error_page():
                        console.print("[yellow][!] Error encountered loading Binance Square post. Recovering...[/yellow]")
                        recovered = await self._recover_from_error(post_url)
                        if not recovered:
                            result["status"] = "server_error"
                            result["message"] = "Binance Network/Server Error"
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
                            el = await self.page.wait_for_selector(sel, state="visible", timeout=3500)
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
                        await input_field.click(timeout=3000)
                    except Exception:
                        await input_field.click(timeout=2500, force=True)

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
                            btn = await self.page.wait_for_selector(s_sel, state="visible", timeout=3500)
                            if btn:
                                submit_btn = btn
                                break
                        except Exception:
                            continue

                    if submit_btn:
                        try:
                            await submit_btn.click(timeout=3000)
                        except Exception:
                            await submit_btn.click(timeout=2500, force=True)

                        console.print(f"[bold green][✓] Answer '{answer}' submitted to post.[/bold green]")
                        await self._human_delay(1.5, 2.5)

                        if await self._is_error_page():
                            console.print("[yellow][!] Error after submitting answer. Recovering...[/yellow]")
                            await self._recover_from_error(post_url)
                            result["status"] = "server_error"
                            result["message"] = "Binance Network/Server Error"
                            if attempt < max_attempts:
                                await asyncio.sleep(2.0)
                                continue
                            return result

                        try:
                            open_btn = await self.page.wait_for_selector('button:has-text("Open"), div[role="button"]:has-text("Open")', state="visible", timeout=3500)
                            if open_btn:
                                await open_btn.click(timeout=2500, force=True)
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
                    if await self._is_error_page():
                        result["status"] = "server_error"
                        await self._recover_from_error(post_url)
                    await self._dismiss_modals()
                    if attempt < max_attempts:
                        await asyncio.sleep(2.0)
                        continue
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
                    if await self._is_error_page():
                        await self._recover_from_error(url)

                    console.print(f"[bold magenta][➔] Opening Direct Red Packet Link: {url}[/bold magenta]")
                    await self._dismiss_modals()
                    response = await self.page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    await self._human_delay(1.5, 2.5)

                    if (response and response.status >= 500) or await self._is_error_page():
                        console.print("[yellow][!] Error loading Red Packet link. Recovering...[/yellow]")
                        await self._recover_from_error(url)
                        result["status"] = "server_error"
                        if attempt < max_attempts:
                            await asyncio.sleep(2.0)
                            continue
                        return result

                    try:
                        open_btn = await self.page.wait_for_selector('button:has-text("Open"), button:has-text("Claim"), div[role="button"]:has-text("Open")', state="visible", timeout=3500)
                        if open_btn:
                            await open_btn.click(timeout=2500, force=True)
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
                        continue
                    else:
                        return result

            return result

    async def close(self):
        if self.context:
            await self.context.close()
        if self._pw:
            await self._pw.stop()
