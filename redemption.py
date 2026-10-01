import os
import asyncio
import random
from typing import Optional, List, Dict, Any
from playwright.async_api import async_playwright, BrowserContext, Page
from rich.console import Console

console = Console()
USER_DATA_DIR = os.path.abspath("./user_data")

# Binance Official Crypto Box Redemption URL
CRYPTO_BOX_URL = "https://www.binance.com/en/my/wallet/account/payment/cryptobox"

class BinanceRedeemer:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._pw = None

    async def _human_delay(self, min_s: float = 0.5, max_s: float = 1.5):
        """Randomized delay to emulate natural human interaction."""
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def _human_type(self, element, text: str):
        """Types text character by character with humanized random pauses."""
        try:
            await element.fill("")
            for char in text:
                await element.type(char, delay=random.uniform(60, 150))
                await asyncio.sleep(random.uniform(0.01, 0.05))
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

    async def _dismiss_modals(self):
        """
        Thoroughly closes any modal, openbox, expired banner, or backdrop.
        Uses button clicking, Escape key, and DOM cleanup if needed.
        """
        if not self.page:
            return
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

            # 3. If modal or mask is still present in DOM, forcefully remove it so it cannot block clicks
            await self.page.evaluate("""() => {
                const lingering = document.querySelectorAll('.bn-mask, .bn-modal, .openbox, [role="presentation"].bn-mask');
                lingering.forEach(el => el.remove());
            }""")
            await asyncio.sleep(0.2)
        except Exception:
            pass

    async def initialize(self):
        """Starts Playwright with persistent context so login session and cookies persist."""
        if self.context:
            return

        self._pw = await async_playwright().start()
        console.print(f"[bold cyan][+] Launching Playwright browser (Headless: {self.headless})...[/bold cyan]")
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        
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

    async def _find_crypto_box_input(self):
        """Attempts to find the Crypto Box code input field with tab check."""
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

    async def claim_crypto_box_code(self, code: str) -> Dict[str, Any]:
        """
        Navigates to Binance Crypto Box page and claims the 8-character code.
        Completely immune to modal blocking, overlay timeouts, and expired hangs.
        """
        if not self.page:
            await self.initialize()

        result = {"code": code, "status": "failed", "message": ""}
        try:
            console.print(f"[bold magenta][➔] Opening Crypto Box page to claim code: [bold yellow]{code}[/bold yellow]...[/bold magenta]")
            
            # Dismiss any lingering popups from previous codes
            await self._dismiss_modals()

            # If not on target page or if an unclosable modal was lingering, reload cleanly
            needs_reload = False
            if CRYPTO_BOX_URL not in self.page.url:
                await self.page.goto(CRYPTO_BOX_URL, wait_until="domcontentloaded", timeout=12000)
                await self._human_delay(1.0, 1.8)
            else:
                # Check if openbox/modal is still in DOM
                lingering = await self.page.query_selector('.openbox, .bn-mask')
                if lingering:
                    needs_reload = True

            if needs_reload:
                await self.page.goto(CRYPTO_BOX_URL, wait_until="domcontentloaded", timeout=12000)
                await self._human_delay(1.0, 1.8)

            # Locate input field
            input_field = await self._find_crypto_box_input()

            # If still not found, do a quick clean reload
            if not input_field:
                console.print("[dim yellow][i] Refreshing page to load Crypto Box form...[/dim yellow]")
                await self.page.goto(CRYPTO_BOX_URL, wait_until="domcontentloaded", timeout=12000)
                await self._human_delay(1.2, 2.0)
                input_field = await self._find_crypto_box_input()

            if not input_field:
                console.print("[bold red][!] Code input field not found on page.[/bold red]")
                result["message"] = "Input field not found"
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
                console.print("[bold red][!] Claim button not found on page.[/bold red]")
                result["message"] = "Claim button not found"
                await self._dismiss_modals()
                return result

            try:
                await claim_btn.click(timeout=2500)
            except Exception:
                await claim_btn.click(timeout=2000, force=True)

            console.print(f"[bold green][✓] Clicked Claim for code '{code}'. Awaiting response...[/bold green]")
            await self._human_delay(1.5, 2.5)

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
                        opened = True
                        break
                except Exception:
                    pass

            if not opened:
                # 2. Check for Expired / Fully Claimed / Invalid status dialogs
                status_text = ""
                try:
                    modal = await self.page.query_selector('.bn-modal, .openbox, [role="dialog"], .toast, div[class*="tip"], div[class*="message"]')
                    if modal:
                        status_text = await modal.inner_text()
                except Exception:
                    pass

                low_text = status_text.lower()
                if "expired" in low_text or "fully claimed" in low_text or "has been claimed" in low_text:
                    console.print(f"[yellow][i] Code '{code}' is EXPIRED or fully claimed by others.[/yellow]")
                    result["status"] = "expired"
                    result["message"] = "Expired or fully claimed"
                elif "already claimed" in low_text or "claimed it already" in low_text:
                    console.print(f"[yellow][i] You have already claimed code '{code}'.[/yellow]")
                    result["status"] = "already_claimed"
                    result["message"] = "Already claimed"
                elif "invalid" in low_text:
                    console.print(f"[red][!] Code '{code}' is invalid.[/red]")
                    result["status"] = "invalid"
                    result["message"] = "Invalid code"
                else:
                    console.print(f"[bold dim][i] Code '{code}' processed ({status_text[:60] if status_text else 'Done'}).[/bold dim]")
                    result["status"] = "done"
                    result["message"] = status_text or "Done"

            # Always dismiss popup dialogs immediately so the next code has a clean canvas
            await self._dismiss_modals()

            # Human pause before next code
            await self._human_delay(1.5, 3.0)

        except Exception as e:
            console.print(f"[bold red][!] Error while claiming code {code}: {e}[/bold red]")
            result["message"] = str(e)
            await self._dismiss_modals()

        return result

    async def claim_binance_square_red_packet(self, post_url: str, answer: str) -> Dict[str, Any]:
        """
        Automates claiming a Binance Square Question/Answer Red Packet post.
        Navigates to post, fills the extracted answer into the answer/comment box, and claims.
        """
        if not self.page:
            await self.initialize()

        result = {"url": post_url, "answer": answer, "status": "failed", "message": ""}
        try:
            console.print(f"[bold magenta][➔] Opening Binance Square Post: {post_url}[/bold magenta]")
            console.print(f"[bold gold1]🔑 Submitting Answer: '{answer}'[/bold gold1]")

            await self._dismiss_modals()
            await self.page.goto(post_url, wait_until="domcontentloaded", timeout=20000)
            await self._human_delay(2.0, 3.5)

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

                try:
                    open_btn = await self.page.wait_for_selector('button:has-text("Open"), div[role="button"]:has-text("Open")', state="visible", timeout=3000)
                    if open_btn:
                        await open_btn.click(timeout=2000, force=True)
                        console.print(f"[bold gold1]🎉 [SUCCESS] Red Packet Opened for post {post_url}![/bold gold1]")
                        result["status"] = "success"
                        result["message"] = "Red Packet opened"
                        await self._dismiss_modals()
                        await self._human_delay(1.8, 3.5)
                        return result
                except Exception:
                    pass

                result["status"] = "submitted"
                result["message"] = "Answer submitted"
            else:
                console.print("[yellow][!] Could not find Submit/Claim button.[/yellow]")
                result["message"] = "Submit button not found"

            await self._dismiss_modals()
            await self._human_delay(1.8, 3.5)

        except Exception as e:
            console.print(f"[bold red][!] Error on Binance Square post: {e}[/bold red]")
            result["message"] = str(e)
            await self._dismiss_modals()

        return result

    async def claim_red_packet_url(self, url: str) -> Dict[str, Any]:
        """Navigates to direct s.binance.com red packet links and auto-clicks Open."""
        if not self.page:
            await self.initialize()

        result = {"url": url, "status": "failed", "message": ""}
        try:
            console.print(f"[bold magenta][➔] Opening Direct Red Packet Link: {url}[/bold magenta]")
            await self._dismiss_modals()
            await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await self._human_delay(1.5, 2.5)

            try:
                open_btn = await self.page.wait_for_selector('button:has-text("Open"), button:has-text("Claim"), div[role="button"]:has-text("Open")', state="visible", timeout=3000)
                if open_btn:
                    await open_btn.click(timeout=2000, force=True)
                    console.print(f"[bold gold1]🎉 [SUCCESS] Clicked Open on Red Packet link![/bold gold1]")
                    result["status"] = "success"
                    await self._dismiss_modals()
                else:
                    result["status"] = "opened"
            except Exception:
                result["status"] = "opened"
        except Exception as e:
            console.print(f"[bold red][!] Error opening Red Packet link: {e}[/bold red]")
            result["message"] = str(e)

        return result

    async def close(self):
        if self.context:
            await self.context.close()
        if self._pw:
            await self._pw.stop()
