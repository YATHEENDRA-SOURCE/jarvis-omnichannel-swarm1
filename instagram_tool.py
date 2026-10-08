import os
import asyncio
import logging
from typing import Optional, Dict, Any, List
from playwright.async_api import async_playwright, BrowserContext, Page

logger = logging.getLogger("instagram_tool")


class InstagramWebController:
    """Controls Instagram Web direct messages using Playwright with persistent session."""

    def __init__(self, session_dir: str = ".instagram_session"):
        self.session_dir = os.path.abspath(session_dir)
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._is_ready = False

    async def initialize(self, headless: bool = False):
        os.makedirs(self.session_dir, exist_ok=True)
        if not self.playwright:
            self.playwright = await async_playwright().start()

        logger.info(f"Starting Instagram browser with session at {self.session_dir}...")
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.session_dir,
            headless=headless,
            channel="chrome" if os.path.exists("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe") else None,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        )

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.page.goto("https://www.instagram.com/", timeout=60000)
        self._is_ready = True
        logger.info("Instagram Web loaded.")

    async def is_logged_in(self) -> bool:
        if not self.page:
            return False
        try:
            # Check for Instagram Home icon or Direct icon or search bar
            direct_icon = await self.page.wait_for_selector(
                "svg[aria-label='Direct'], svg[aria-label='Messenger'], a[href*='/direct/inbox/']",
                timeout=4000
            )
            return direct_icon is not None
        except Exception:
            return False

    async def send_dm(self, username: str, message: str) -> Dict[str, Any]:
        """Navigates to Direct Messages and sends a message to an Instagram username."""
        if not self.page:
            await self.initialize(headless=False)

        clean_username = username.lstrip("@").strip()
        logger.info(f"Sending Instagram DM to @{clean_username}...")

        try:
            # Direct compose URL
            await self.page.goto("https://www.instagram.com/direct/new/", timeout=45000)
            await asyncio.sleep(2)

            # Search recipient input box
            search_input = self.page.locator("input[placeholder*='Search'], input[name*='queryBox']").first
            await search_input.fill(clean_username)
            await asyncio.sleep(2)

            # Select the matching user from search results list
            user_checkbox = self.page.locator(f"span:has-text('{clean_username}')").first
            if await user_checkbox.is_visible():
                await user_checkbox.click()
                await asyncio.sleep(1)
            else:
                # Fallback: click first search result item
                first_result = self.page.locator("div[role='button']:has(span)").first
                await first_result.click()
                await asyncio.sleep(1)

            # Click Chat / Next button
            chat_btn = self.page.locator("div[role='button']:has-text('Chat'), div:has-text('Next')").last
            if await chat_btn.is_visible():
                await chat_btn.click()
                await asyncio.sleep(2)

            # Focus message input box and type message
            msg_box = self.page.locator(
                "div[contenteditable='true'][role='textbox'], div[aria-label*='Message'], p.selectable-text"
            ).first
            await msg_box.click()
            await msg_box.fill(message)
            await asyncio.sleep(0.5)
            await self.page.keyboard.press("Enter")
            await asyncio.sleep(2)

            logger.info(f"Instagram DM sent to @{clean_username} successfully!")
            return {"success": True, "recipient": f"@{clean_username}", "message": message}

        except Exception as e:
            logger.error(f"Failed to send Instagram DM to @{clean_username}: {e}")
            return {"success": False, "recipient": f"@{clean_username}", "error": str(e)}

    async def read_unread_dms(self) -> List[Dict[str, Any]]:
        """Checks for latest direct messages on Instagram."""
        if not self.page:
            await self.initialize(headless=False)

        try:
            await self.page.goto("https://www.instagram.com/direct/inbox/", timeout=45000)
            await asyncio.sleep(2)

            threads = []
            chat_elements = await self.page.locator("div[role='listitem'], div[aria-label='Chats'] a").all()
            for chat in chat_elements[:5]:
                text = await chat.inner_text()
                if text.strip():
                    threads.append({"chat": text.replace("\n", " | ")})

            return threads
        except Exception as e:
            return [{"error": f"Could not read Instagram DMs: {e}"}]

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
