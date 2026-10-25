import os
import time
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from parser import (
    extract_red_packet_codes,
    extract_urls_from_entities,
    extract_square_urls,
    extract_red_packet_urls,
    extract_quiz_answers,
    parse_telegram_message,
)
from redemption import (
    parse_lockout_duration,
    format_duration,
    BinanceRedeemer,
)
from main import (
    get_backoff_delay,
    format_delay_text,
    format_phone_number,
    RETRY_DELAYS,
)


class TestParser(unittest.TestCase):
    def test_extract_emoji_codes(self):
        text = "New drop alert! 🎁 I8C23DTN claim now fast!"
        codes = extract_red_packet_codes(text)
        self.assertIn("I8C23DTN", codes)

    def test_extract_bp_codes(self):
        text = "Binance Pay code: BP7XY89Z claim it"
        codes = extract_red_packet_codes(text)
        self.assertIn("BP7XY89Z", codes)

    def test_extract_generic_codes(self):
        text = "Crypto Box code: 029G7T77 and DDOD8UZ9"
        codes = extract_red_packet_codes(text)
        self.assertIn("029G7T77", codes)
        self.assertIn("DDOD8UZ9", codes)

    def test_strip_urls_from_code_extraction(self):
        # Prevent URL parameters like ?ref=YNGX16JK from being extracted as codes
        text = "Check out https://www.binance.com/activity?ref=YNGX16JK for details"
        codes = extract_red_packet_codes(text)
        self.assertNotIn("YNGX16JK", codes)

    def test_ignored_words_filtered(self):
        text = "BINANCE REWARDS ACTIVITY DOWNLOAD"
        codes = extract_red_packet_codes(text)
        self.assertEqual(len(codes), 0)

    def test_extract_square_urls(self):
        text = "Check this post: https://www.binance.com/en/square/post/371921171275162"
        urls = extract_square_urls(text)
        self.assertIn("https://www.binance.com/en/square/post/371921171275162", urls)

    def test_extract_red_packet_urls(self):
        text = "Claim direct link: https://s.binance.com/abcdef12"
        urls = extract_red_packet_urls(text)
        self.assertIn("https://s.binance.com/abcdef12", urls)

    def test_extract_square_answers(self):
        text = "Binance Square Quiz Answer: 𝑨𝒏𝒔𝒘𝒆𝒓 :❕20.8k❕"
        answers = extract_quiz_answers(text)
        self.assertIn("20.8k", answers)

    def test_parse_telegram_message(self):
        text = "🎁 DDOD8UZ9 https://s.binance.com/abcdef12"
        parsed = parse_telegram_message(text)
        self.assertIn("DDOD8UZ9", parsed["codes"])
        self.assertIn("https://s.binance.com/abcdef12", parsed["red_packet_urls"])


class TestRedemptionHelpers(unittest.TestCase):
    def test_parse_lockout_duration_hours_minutes(self):
        text = "You have exceeded the maximum attempts. Please try again in 04 hour(s) and 19 minute(s)."
        seconds = parse_lockout_duration(text)
        expected = 4 * 3600 + 19 * 60
        self.assertEqual(seconds, expected)

    def test_parse_lockout_duration_minutes_seconds(self):
        text = "Too many attempts. Try again in 15 minute(s) and 30 second(s)."
        seconds = parse_lockout_duration(text)
        expected = 15 * 60 + 30
        self.assertEqual(seconds, expected)

    def test_parse_lockout_duration_fallback(self):
        text = "Rate limit reached. Please try later."
        seconds = parse_lockout_duration(text)
        self.assertEqual(seconds, 300)

    def test_format_duration(self):
        self.assertEqual(format_duration(3665), "01 hour(s) and 01 minute(s)")
        self.assertEqual(format_duration(125), "02 minute(s) and 05 second(s)")
        self.assertEqual(format_duration(45), "45 second(s)")

    def test_lockout_state_management(self):
        redeemer = BinanceRedeemer(headless=True)
        redeemer.clear_lockout()
        is_locked, rem_s, rem_str = redeemer.is_locked_out()
        self.assertFalse(is_locked)

        redeemer.set_lockout(60, "Testing lockout")
        is_locked, rem_s, rem_str = redeemer.is_locked_out()
        self.assertTrue(is_locked)
        self.assertGreater(rem_s, 0)

        redeemer.clear_lockout()
        is_locked, _, _ = redeemer.is_locked_out()
        self.assertFalse(is_locked)

    def test_circuit_breaker(self):
        redeemer = BinanceRedeemer(headless=True)
        redeemer._reset_circuit_breaker()
        self.assertEqual(redeemer.consecutive_failures, 0)


class TestPageFeedbackNoiseFiltering(unittest.IsolatedAsyncioTestCase):
    async def test_locale_noise_ignored(self):
        """Verify that 'English English USD-$ USD-$' is recognized as noise and filtered out."""
        redeemer = BinanceRedeemer(headless=True)
        mock_page = AsyncMock()
        mock_page.evaluate.return_value = "English\nEnglish\nUSD-$ USD-$"
        redeemer.page = mock_page

        fb = await redeemer._extract_page_feedback()
        self.assertEqual(fb.get("status"), "no_response")
        self.assertNotEqual(fb.get("status"), "unknown")

    async def test_genuine_expired_classified(self):
        redeemer = BinanceRedeemer(headless=True)
        mock_page = AsyncMock()
        mock_page.evaluate.return_value = "All rewards have been claimed"
        redeemer.page = mock_page

        fb = await redeemer._extract_page_feedback()
        self.assertEqual(fb.get("status"), "expired")

    async def test_genuine_rate_limit_classified(self):
        redeemer = BinanceRedeemer(headless=True)
        mock_page = AsyncMock()
        mock_page.evaluate.return_value = "You have exceeded the maximum attempts. Please try again in 01 hour(s)."
        redeemer.page = mock_page

        fb = await redeemer._extract_page_feedback()
        self.assertEqual(fb.get("status"), "rate_limited")
        self.assertEqual(fb.get("retry_after"), 3600)

    async def test_genuine_already_claimed_classified(self):
        redeemer = BinanceRedeemer(headless=True)
        mock_page = AsyncMock()
        mock_page.evaluate.return_value = "You have already claimed this Crypto Box"
        redeemer.page = mock_page

        fb = await redeemer._extract_page_feedback()
        self.assertEqual(fb.get("status"), "already_claimed")

    async def test_error_page_detection_server_errors(self):
        redeemer = BinanceRedeemer(headless=True)
        mock_page = AsyncMock()
        mock_page.url = "https://www.binance.com/en/my/wallet/account/payment/cryptobox"
        mock_page.query_selector.return_value = None
        mock_page.evaluate.return_value = "500 Internal Server Error. Something went wrong."
        redeemer.page = mock_page

        is_error = await redeemer._is_error_page()
        self.assertTrue(is_error)

    async def test_error_page_detection_network_offline(self):
        redeemer = BinanceRedeemer(headless=True)
        mock_page = AsyncMock()
        mock_page.url = "chrome-error://chromewebdata/"
        mock_page.query_selector.return_value = None
        mock_page.evaluate.return_value = "This site can't be reached. ERR_INTERNET_DISCONNECTED"
        redeemer.page = mock_page

        is_error = await redeemer._is_error_page()
        self.assertTrue(is_error)

    async def test_wait_for_claim_outcome_open_success(self):
        redeemer = BinanceRedeemer(headless=True)
        mock_page = AsyncMock()
        mock_page.url = "https://www.binance.com/en/my/wallet/account/payment/cryptobox"
        mock_open_btn = AsyncMock()
        mock_open_btn.is_visible.return_value = True

        async def mock_query(sel):
            if "Open" in sel:
                return mock_open_btn
            return None

        mock_page.query_selector = mock_query
        mock_page.evaluate.return_value = ""
        redeemer.page = mock_page

        outcome = await redeemer._wait_for_claim_outcome("TESTCODE", timeout_seconds=2.0)
        self.assertEqual(outcome.get("status"), "success")
        mock_open_btn.click.assert_called()

    async def test_wait_for_claim_outcome_network_timeout(self):
        redeemer = BinanceRedeemer(headless=True)
        mock_page = AsyncMock()
        mock_page.url = "https://www.binance.com/en/my/wallet/account/payment/cryptobox"
        mock_page.query_selector.return_value = None
        
        async def mock_eval(script):
            if "claimBtn" in script or "spin" in script:
                return True
            return ""

        mock_page.evaluate = mock_eval
        redeemer.page = mock_page

        outcome = await redeemer._wait_for_claim_outcome("TESTCODE", timeout_seconds=0.8)
        self.assertEqual(outcome.get("status"), "network_timeout")

    async def test_wait_for_claim_outcome_server_error(self):
        redeemer = BinanceRedeemer(headless=True)
        mock_page = AsyncMock()
        mock_page.url = "https://www.binance.com/en/my/wallet/account/payment/cryptobox"
        mock_page.query_selector.return_value = None
        mock_page.evaluate.return_value = "500 Internal Server Error"
        redeemer.page = mock_page

        outcome = await redeemer._wait_for_claim_outcome("TESTCODE", timeout_seconds=1.0)
        self.assertEqual(outcome.get("status"), "server_error")


class TestMainNetworkManagement(unittest.TestCase):
    def test_backoff_delays(self):
        self.assertEqual(get_backoff_delay(0), 5)
        self.assertEqual(get_backoff_delay(1), 10)
        self.assertEqual(get_backoff_delay(2), 20)
        self.assertEqual(get_backoff_delay(3), 30)
        self.assertEqual(get_backoff_delay(4), 60)
        self.assertEqual(get_backoff_delay(99), RETRY_DELAYS[-1])

    def test_format_delay_text(self):
        self.assertEqual(format_delay_text(5), "5s")
        self.assertEqual(format_delay_text(30), "30s")
        self.assertEqual(format_delay_text(60), "1 min")
        self.assertEqual(format_delay_text(90), "1 min 30s")
        self.assertEqual(format_delay_text(300), "5 min")

    def test_format_phone_number(self):
        self.assertEqual(format_phone_number("+1234567890"), "+1234567890")
        self.assertEqual(format_phone_number(" +1 234-567-890 "), "+1234567890")

class TestProcessIsolation(unittest.TestCase):
    def test_cleanup_stale_locks_protects_other_processes(self):
        """Verify _cleanup_stale_locks strictly isolates and never interferes with external browsers or trading bots."""
        from redemption import BinanceRedeemer, USER_DATA_DIR
        redeemer = BinanceRedeemer(headless=True)

        # 1. User's personal Google Chrome
        chrome_proc = MagicMock()
        chrome_proc.pid = 1001
        chrome_proc.info = {
            "pid": 1001,
            "name": "chrome.exe",
            "cmdline": ["chrome.exe", r"--user-data-dir=C:\Users\User\AppData\Local\Google\Chrome\User Data"],
        }

        # 2. XAUUSD-AI-Trading-Bot or other Python process
        trading_bot_proc = MagicMock()
        trading_bot_proc.pid = 2002
        trading_bot_proc.info = {
            "pid": 2002,
            "name": "python.exe",
            "cmdline": ["python.exe", r"C:\Users\Mazonia\Desktop\XAUUSD-AI-Trading-Bot\notifications\telegram_bot.py"],
        }

        # 3. Another tool using Playwright with its own data dir
        other_playwright_proc = MagicMock()
        other_playwright_proc.pid = 3003
        other_playwright_proc.info = {
            "pid": 3003,
            "name": "chrome.exe",
            "cmdline": [r"C:\Users\User\AppData\Local\ms-playwright\chromium\chrome.exe", r"--user-data-dir=C:\Temp\other_agent_data"],
        }

        # 4. Stale browser strictly belonging to THIS claimer bot
        stale_claimer_proc = MagicMock()
        stale_claimer_proc.pid = 4004
        stale_claimer_proc.info = {
            "pid": 4004,
            "name": "chrome.exe",
            "cmdline": ["chrome.exe", f"--user-data-dir={USER_DATA_DIR}", "--headless=new"],
        }

        mock_procs = [chrome_proc, trading_bot_proc, other_playwright_proc, stale_claimer_proc]

        with patch("psutil.process_iter", return_value=mock_procs):
            redeemer._cleanup_stale_locks()

            # Personal Chrome MUST NOT be terminated
            self.assertFalse(chrome_proc.terminate.called)
            # Trading bot MUST NOT be terminated
            self.assertFalse(trading_bot_proc.terminate.called)
            # Other Playwright session MUST NOT be terminated
            self.assertFalse(other_playwright_proc.terminate.called)
            # Only this claimer's browser should be terminated
            self.assertTrue(stale_claimer_proc.terminate.called)


class TestBrowserResilience(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_browser_alive_triggers_reinit_when_closed(self):
        redeemer = BinanceRedeemer(headless=True)
        mock_page = MagicMock()
        mock_page.is_closed.return_value = True
        redeemer.page = mock_page
        redeemer.context = MagicMock()

        with patch.object(redeemer, "reinitialize", new_callable=AsyncMock) as mock_reinit:
            await redeemer.ensure_browser_alive()
            mock_reinit.assert_called_once()

    async def test_ensure_browser_alive_passes_when_responsive(self):
        redeemer = BinanceRedeemer(headless=True)
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://www.binance.com/cryptobox"
        redeemer.page = mock_page
        redeemer.context = MagicMock()

        with patch.object(redeemer, "reinitialize", new_callable=AsyncMock) as mock_reinit:
            result = await redeemer.ensure_browser_alive()
            self.assertTrue(result)
            mock_reinit.assert_not_called()


class TestSingleInstanceProtection(unittest.TestCase):
    def test_ensure_single_claimer_instance_terminates_older_instance(self):
        from main import ensure_single_claimer_instance
        import os

        cur_dir = os.path.abspath(".").lower()
        older_proc = MagicMock()
        older_proc.pid = 99999
        older_proc.info = {
            "pid": 99999,
            "name": "redpacket-claimer.exe",
            "cmdline": ["redpacket-claimer.exe", "main.py"],
            "exe": os.path.join(cur_dir, "redpacket-claimer.exe"),
        }

        with patch("psutil.process_iter", return_value=[older_proc]):
            ensure_single_claimer_instance()
            self.assertTrue(older_proc.terminate.called)


class TestAutostartScripts(unittest.TestCase):
    def test_setup_autostart_task_scheduler_direct_execution(self):
        """Verify setup_autostart.bat configures direct 24/7 background execution with network delay."""
        setup_bat_path = os.path.join(os.path.dirname(__file__), "setup_autostart.bat")
        with open(setup_bat_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Must execute claimer directly with headless flag and boot delay
        self.assertIn('<Command>$claimerExe</Command>', content)
        self.assertIn('<Arguments>main.py --headless</Arguments>', content)
        self.assertIn('<Delay>PT15S</Delay>', content)
        self.assertIn('Binance-RedPacket-Claimer', content)

    def test_start_hidden_vbs_execution_and_lock(self):
        """Verify start_hidden.vbs includes atomic start.lock and reliable quoting."""
        vbs_path = os.path.join(os.path.dirname(__file__), "start_hidden.vbs")
        with open(vbs_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Must implement atomic startup lock
        self.assertIn("start.lock", content)
        # Must support direct executable launch
        self.assertIn("redpacket-claimer.exe", content)

    def test_run_bat_python_fallback(self):
        """Verify run.bat does not crash with infinite loop when python is missing."""
        run_bat_path = os.path.join(os.path.dirname(__file__), "run.bat")
        with open(run_bat_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Must have clean error exit if Python not found
        self.assertIn(":no_py", content)
        self.assertIn("exit /b 1", content)


class TestClaimTimestampingAndDiagnostics(unittest.TestCase):
    def setUp(self):
        self.test_cache = os.path.join(os.path.dirname(__file__), "test_cache_temp.json")
        self.test_status = os.path.join(os.path.dirname(__file__), "test_status_temp.json")

    def tearDown(self):
        for f in [self.test_cache, self.test_status]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def test_cache_backward_compatibility(self):
        """Verify cache loader seamlessly ingests legacy string arrays and modern rich dicts."""
        import json
        from main import load_claimed_cache, CACHE_FILE
        import main

        # Create mixed cache
        mixed_data = [
            "LEGACY123",
            "LEGACY456",
            {
                "identifier": "MODERN789",
                "type": "code",
                "claimed_at": "2026-10-23 12:00:00",
                "channel": "Cryptobox Parser",
                "status": "success"
            }
        ]
        with open(self.test_cache, "w", encoding="utf-8") as f:
            json.dump(mixed_data, f)

        orig_cache_file = main.CACHE_FILE
        try:
            main.CACHE_FILE = self.test_cache
            loaded = main.load_claimed_cache()
            self.assertIn("LEGACY123", loaded)
            self.assertIn("LEGACY456", loaded)
            self.assertIn("MODERN789", loaded)
            self.assertEqual(len(loaded), 3)
            self.assertEqual(main.claimed_details["MODERN789"]["channel"], "Cryptobox Parser")
        finally:
            main.CACHE_FILE = orig_cache_file

    def test_record_claimed_item_preserves_metadata(self):
        """Verify record_claimed_item saves timestamp, channel, and status."""
        import main

        orig_cache_file = main.CACHE_FILE
        orig_status_file = main.STATUS_FILE
        try:
            main.CACHE_FILE = self.test_cache
            main.STATUS_FILE = self.test_status
            main.claimed_items = set()
            main.claimed_details = {}

            main.record_claimed_item(
                item_type="code",
                identifier="TESTCODE1",
                channel="Crypto VIP Drops",
                status="success",
                message="Claimed 0.5 USDT",
                reward="0.5 USDT"
            )

            self.assertIn("TESTCODE1", main.claimed_items)
            detail = main.claimed_details.get("TESTCODE1")
            self.assertIsNotNone(detail)
            self.assertEqual(detail["channel"], "Crypto VIP Drops")
            self.assertEqual(detail["status"], "success")
            self.assertEqual(detail["reward"], "0.5 USDT")
            self.assertTrue(bool(detail["claimed_at"]))
        finally:
            main.CACHE_FILE = orig_cache_file
            main.STATUS_FILE = orig_status_file

    def test_check_worker_relative_time(self):
        """Verify check_worker format_relative_time and duration formatters."""
        from check_worker import format_relative_time, format_duration_short
        now = time.time()
        self.assertEqual(format_relative_time(now - 10), "10s ago")
        self.assertEqual(format_relative_time(now - 150), "2m ago")
        self.assertEqual(format_relative_time(now - 7200), "2h 0m ago")

        self.assertEqual(format_duration_short(45), "45s")
        self.assertEqual(format_duration_short(125), "2m 5s")
        self.assertEqual(format_duration_short(3665), "1h 1m")


class TestLogPrintAndNetworkResilience(unittest.TestCase):
    def setUp(self):
        self.test_log = os.path.join(os.path.dirname(__file__), "test_log_temp.log")
        self.test_status = os.path.join(os.path.dirname(__file__), "test_status_temp.json")

    def tearDown(self):
        for f in [self.test_log, self.test_status]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def test_log_print_supports_rich_panel_and_renderables(self):
        """Verify log_print handles Rich Panel, Text, and strings without TypeError."""
        from rich.panel import Panel
        from rich.text import Text
        import main

        orig_log = main.LOG_FILE
        try:
            main.LOG_FILE = self.test_log

            # 1. Plain string with Rich markup tags
            main.log_print("[bold green]Hello World[/bold green]")

            # 2. Rich Panel object with title (which previously caused TypeError in re.sub)
            panel = Panel("BPZ7U1K9QP\nGrab fast!", title="[bold green]📩 New Drop from Cryptobox Parser[/bold green]", border_style="green")
            main.log_print(panel)

            # 3. Rich Text object
            text_obj = Text("Custom Text Component")
            main.log_print(text_obj)

            # 4. Exception object
            main.log_print(ValueError("Testing error formatting"))

            # Verify contents written to test_log
            self.assertTrue(os.path.exists(self.test_log))
            with open(self.test_log, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("Hello World", content)
            self.assertNotIn("[bold green]", content)
            self.assertIn("📩 New Drop from Cryptobox Parser", content)
            self.assertIn("BPZ7U1K9QP", content)
            self.assertIn("Custom Text Component", content)
            self.assertIn("Testing error formatting", content)
        finally:
            main.LOG_FILE = orig_log

    def test_update_worker_status_includes_telegram_connected(self):
        """Verify update_worker_status includes telegram_connected field."""
        import json
        import main

        orig_status = main.STATUS_FILE
        try:
            main.STATUS_FILE = self.test_status
            main.update_worker_status()

            self.assertTrue(os.path.exists(self.test_status))
            with open(self.test_status, "r", encoding="utf-8") as f:
                sdata = json.load(f)

            self.assertIn("telegram_connected", sdata)
            self.assertIsInstance(sdata["telegram_connected"], bool)
        finally:
            main.STATUS_FILE = orig_status

    def test_live_message_handler_exception_safety(self):
        """Verify live_message_handler catches all internal errors without raising unhandled exceptions."""
        import main
        import asyncio

        mock_event = MagicMock()
        mock_event.get_chat = AsyncMock(side_effect=Exception("Simulated network timeout"))
        mock_event.raw_text = "BP12345678"
        mock_event.message = None

        with patch("main.process_single_item", new_callable=AsyncMock) as mock_process:
            try:
                asyncio.run(main.live_message_handler(mock_event))
                mock_process.assert_awaited()
            except Exception as e:
                self.fail(f"live_message_handler raised an unhandled exception: {e}")


if __name__ == "__main__":
    unittest.main()

