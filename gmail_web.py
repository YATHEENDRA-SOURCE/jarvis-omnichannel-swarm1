import os
import asyncio
import logging
from typing import List, Dict, Any, Optional
from playwright.async_api import async_playwright, BrowserContext, Page

logger = logging.getLogger("gmail_web")


class GmailWebController:
    """Automates Gmail directly in the browser with persistent session - NO App Passwords needed."""

    def __init__(self, session_dir: str = ".gmail_session"):
        self.session_dir = os.path.abspath(session_dir)
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._is_ready = False

    async def initialize(self, headless: bool = False):
        """Initializes Gmail Web with persistent cookies."""
        os.makedirs(self.session_dir, exist_ok=True)
        logger.info(f"Opening Gmail Web session from {self.session_dir}...")
        
        playwright = await async_playwright().start()
        self.context = await playwright.chromium.launch_persistent_context(
            user_data_dir=self.session_dir,
            headless=headless,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.page.goto("https://mail.google.com/", wait_until="domcontentloaded", timeout=60000)
        self._is_ready = True
        logger.info("Gmail Web initialized!")

    async def read_unread_emails(self, max_count: int = 5) -> List[Dict[str, str]]:
        """Reads recent unread emails from Gmail Web."""
        if not self.page:
            await self.initialize(headless=False)

        await self.page.goto("https://mail.google.com/mail/u/0/#inbox", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2.0)

        # In Gmail, unread rows have class 'zE'
        unread_rows = await self.page.locator("tr.zE").all()
        results = []
        
        for row in unread_rows[:max_count]:
            try:
                sender = await row.locator("span.zF, span.bA4").first.inner_text()
                subject_el = row.locator("span.bog").first
                subject = await subject_el.inner_text() if await subject_el.count() > 0 else "No Subject"
                snippet_el = row.locator("span.y2").first
                snippet = await snippet_el.inner_text() if await snippet_el.count() > 0 else ""
                
                results.append({
                    "from": sender,
                    "subject": subject,
                    "snippet": snippet.strip(" -"),
                    "date": "Recent"
                })
            except Exception as e:
                logger.debug(f"Row read note: {e}")
                continue

        return results

    async def send_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Composes and sends an email via Gmail Web."""
        if not self.page:
            await self.initialize(headless=False)

        await self.page.goto("https://mail.google.com/mail/u/0/#inbox", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1.5)

        # Click Compose button
        compose_btn = self.page.locator("div[role='button'][gh='cm'], div.T-I-KE, div[role='button']:has-text('Compose')").first
        await compose_btn.click()
        await asyncio.sleep(1.0)

        # Fill recipient 'To'
        to_box = self.page.locator("input[aria-label*='To' i], input.agP, textarea[name='to']").first
        await to_box.fill(to)
        await self.page.keyboard.press("Enter")
        await asyncio.sleep(0.5)

        # Fill Subject
        subject_box = self.page.locator("input[name='subjectbox'], input[aria-label*='Subject' i]").first
        if await subject_box.is_visible():
            await subject_box.fill(subject)

        # Fill Body
        body_box = self.page.locator("div[aria-label*='Message Body' i], div[role='textbox']").first
        if await body_box.is_visible():
            await body_box.click()
            await body_box.fill(body)

        await asyncio.sleep(0.5)

        # Click Send (or Ctrl+Enter)
        await self.page.keyboard.press("Control+Enter")
        await asyncio.sleep(2.0)

        logger.info(f"Email dispatched to {to} via Gmail Web!")
        return {"success": True, "to": to, "subject": subject}
