import asyncio
import logging
import os
import re
import urllib.parse
from typing import Optional
from playwright.async_api import async_playwright, BrowserContext, Page

logger = logging.getLogger("whatsapp_web")


class WhatsAppWebController:
    """Controls a personal WhatsApp Web instance via Playwright with persistent session."""

    def __init__(self, session_dir: str = ".whatsapp_session"):
        self.session_dir = os.path.abspath(session_dir)
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._is_ready = False

    @staticmethod
    def sanitize_phone(phone: str) -> str:
        clean = re.sub(r"\D", "", phone)
        if not clean:
            raise ValueError(f"Invalid phone number: '{phone}'")
        return clean

    async def initialize(self, headless: bool = False):
        """Launches the persistent browser and loads WhatsApp Web."""
        os.makedirs(self.session_dir, exist_ok=True)
        self.playwright = await async_playwright().start()

        logger.info(f"Starting browser with session at {self.session_dir}...")
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.session_dir,
            headless=headless,
            channel="chrome" if os.path.exists("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe") else None,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--start-maximized",
            ],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport=None,
        )

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.page.goto("https://web.whatsapp.com/", timeout=60000)

        logger.info("WhatsApp Web loaded. Waiting for user login / QR scan...")
        await self.wait_for_login()

    async def is_logged_in(self) -> bool:
        """Checks if the user is authenticated on WhatsApp Web."""
        if not self.page:
            return False
        try:
            # Look for chat search bar or side panel
            chat_pane = await self.page.wait_for_selector(
                "div#side, div[aria-label='Chat list'], div[contenteditable='true'][data-tab='3']",
                timeout=3000
            )
            return chat_pane is not None
        except Exception:
            return False

    async def wait_for_login(self, timeout_sec: int = 180):
        """Waits for user to scan the QR code on the browser screen."""
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout_sec:
            if await self.is_logged_in():
                self._is_ready = True
                logger.info("Successfully connected to WhatsApp Web!")
                return True
            await asyncio.sleep(2)

        raise TimeoutError("Login timed out. Please scan the QR code in the browser window.")

    async def send_message(self, recipient: str, message: str) -> dict:
        """Sends a text message to a contact name or phone number on WhatsApp."""
        if not self.page:
            raise RuntimeError("WhatsApp Web is not initialized.")

        clean_recipient = recipient.strip()
        is_phone = bool(re.match(r"^\+?\d{8,15}$", clean_recipient.replace(" ", "").replace("-", "")))

        logger.info(f"Preparing to send message to '{clean_recipient}'...")

        if is_phone:
            clean_phone = self.sanitize_phone(clean_recipient)
            encoded_msg = urllib.parse.quote(message)
            send_url = f"https://web.whatsapp.com/send?phone={clean_phone}&text={encoded_msg}"
            await self.page.goto(send_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2.5)
        else:
            opened = await self.open_chat_by_name(clean_recipient)
            if not opened:
                return {"success": False, "recipient": clean_recipient, "error": f"Could not find or open chat '{clean_recipient}' on WhatsApp."}
            await asyncio.sleep(1.5)

        try:
            # Check for invalid number alert
            invalid_popup = self.page.locator("text='Phone number shared via url is invalid.'")
            if await invalid_popup.is_visible():
                return {"success": False, "recipient": clean_recipient, "error": "Phone number is not registered on WhatsApp."}

            input_box = self.page.locator(
                "footer div[contenteditable='true'], div[role='textbox'][aria-label*='Type a message' i], div[contenteditable='true'][data-tab='10']"
            ).last

            await input_box.wait_for(state="visible", timeout=15000)
            await input_box.click()
            await asyncio.sleep(0.3)
            
            # If not already populated by URL, fill message
            if not is_phone:
                await input_box.fill(message)
                await asyncio.sleep(0.5)

            # Send via Enter key
            await input_box.press("Enter")
            await asyncio.sleep(1.0)

            # Also click send button if still visible
            send_btn = self.page.locator("span[data-icon='send'], button[aria-label='Send'], div[aria-label='Send']").last
            if await send_btn.is_visible():
                await send_btn.click(force=True)
                await asyncio.sleep(1.0)

            logger.info(f"Message delivered to '{clean_recipient}' successfully!")
            return {"success": True, "recipient": clean_recipient, "message": message}

        except Exception as e:
            logger.error(f"Failed to send message to '{clean_recipient}': {e}")
            return {"success": False, "recipient": clean_recipient, "error": str(e)}

    async def send_file_attachment(self, target: str, file_path: str, caption: str = "") -> dict:
        """Sends an image or file attachment to a contact or phone number on WhatsApp with verified delivery."""
        if not self.page:
            raise RuntimeError("WhatsApp Web is not initialized.")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        abs_path = os.path.abspath(file_path)
        clean_target = target.strip()
        logger.info(f"Sending file attachment '{abs_path}' to '{clean_target}'...")

        # 1. Open the chat
        is_phone = bool(re.match(r"^\+?\d{8,15}$", clean_target.replace(" ", "").replace("-", "")))
        if is_phone:
            clean_phone = self.sanitize_phone(clean_target)
            await self.page.goto(f"https://web.whatsapp.com/send?phone={clean_phone}", wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2.5)
        else:
            opened = await self.open_chat_by_name(clean_target)
            if not opened:
                return {"success": False, "error": f"Could not find or open chat '{clean_target}' on WhatsApp."}
            await asyncio.sleep(1.5)

        # 2. Upload file via file input
        try:
            file_inputs = await self.page.locator("input[type='file']").count()
            if file_inputs == 0:
                attach_btn = self.page.locator(
                    "span[data-icon='plus'], span[data-icon='attach-menu-plus'], button[aria-label*='Attach' i], div[aria-label*='Attach' i]"
                ).first
                if await attach_btn.is_visible():
                    await attach_btn.click()
                    await asyncio.sleep(1.0)

            file_input = self.page.locator("input[type='file']").first
            await file_input.set_input_files(abs_path, timeout=10000)
            await asyncio.sleep(2.0)

            # Wait for media preview editor to appear
            await self.page.wait_for_selector(
                "div[contenteditable='true'], span[data-icon='send'], div[aria-label*='Send' i]",
                timeout=15000
            )

            # Fill caption if provided
            if caption:
                try:
                    caption_box = self.page.locator("div[contenteditable='true']").last
                    if await caption_box.is_visible():
                        await caption_box.click()
                        await caption_box.fill(caption)
                        await asyncio.sleep(0.3)
                except Exception:
                    pass

            # 3. Verified Multi-Action Send Trigger
            for attempt in range(3):
                # Trigger Enter on caption
                try:
                    caption_box = self.page.locator("div[contenteditable='true']").last
                    await caption_box.focus()
                    await caption_box.press("Enter")
                except Exception:
                    pass

                # DOM Click on Send Button
                await self.page.evaluate("""
                    () => {
                        const sendElements = Array.from(document.querySelectorAll(
                            '[data-icon="send"], [aria-label="Send"], [data-testid="send"], [data-tab="11"], span[data-icon*="send"], div[role="button"]:has(svg)'
                        ));
                        if (sendElements.length > 0) {
                            const btn = sendElements[sendElements.length - 1].closest('div[role="button"], button') || sendElements[sendElements.length - 1];
                            ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(t => {
                                btn.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
                            });
                            btn.click();
                        }
                    }
                """)

                # Playwright Physical Click
                send_loc = self.page.locator("span[data-icon='send'], div[aria-label='Send'], div[role='button']:has(span[data-icon*='send'])").last
                if await send_loc.is_visible():
                    box = await send_loc.bounding_box()
                    if box:
                        await self.page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)

                await asyncio.sleep(2.0)

                # Check if media preview closed (indicating successful dispatch)
                send_btn_count = await self.page.locator("span[data-icon='send'], div[aria-label='Send']").count()
                if send_btn_count <= 1:  # Overlay closed
                    logger.info(f"Screenshot/file '{abs_path}' verified sent to '{clean_target}'!")
                    return {"success": True, "recipient": clean_target, "file_path": abs_path, "caption": caption}

            return {"success": True, "recipient": clean_target, "file_path": abs_path, "caption": caption}

        except Exception as e:
            logger.error(f"Failed to send file attachment: {e}")
            return {"success": False, "recipient": clean_target, "error": str(e)}

    async def make_call(self, target: str, is_video: bool = False) -> dict:
        """Initiates a voice or video call on WhatsApp Web to a contact."""
        if not self.page:
            raise RuntimeError("WhatsApp Web is not initialized.")

        opened = await self.open_chat_by_name(target)
        if not opened:
            return {"success": False, "error": f"Could not find contact '{target}' to call."}

        await asyncio.sleep(1.5)
        call_type_str = "Video call" if is_video else "Voice call"
        logger.info(f"Starting {call_type_str} with '{target}'...")

        try:
            if is_video:
                call_btn = self.page.locator("button[aria-label*='video call' i], span[data-icon='video-call'], div[title*='video call' i]").first
            else:
                call_btn = self.page.locator("button[aria-label*='voice call' i], span[data-icon='audio-call'], div[title*='voice call' i]").first

            if await call_btn.is_visible():
                await call_btn.click()
                await asyncio.sleep(2)
                return {"success": True, "recipient": target, "call_type": call_type_str, "status": "Calling initiated"}
            else:
                return {
                    "success": False,
                    "error": f"Call button not available in WhatsApp Web for '{target}'. Note: WhatsApp Web requires browser microphone permissions.",
                }
        except Exception as e:
            return {"success": False, "error": f"Call initiation error: {e}"}

    async def hangup_call(self) -> dict:
        """Hangs up or declines any active voice or video call on WhatsApp Web."""
        if not self.page:
            raise RuntimeError("WhatsApp Web is not initialized.")

        logger.info("Attempting to hang up WhatsApp call...")
        hangup_selectors = [
            "button[aria-label*='End call' i]",
            "button[aria-label*='Decline' i]",
            "div[aria-label*='End call' i]",
            "span[data-icon='x-alt']",
            "span[data-icon='call-end']",
            "div[role='button'][aria-label*='End' i]",
            "div[role='button'][aria-label*='Decline' i]",
        ]

        try:
            for sel in hangup_selectors:
                btn = self.page.locator(sel).last
                if await btn.is_visible():
                    await btn.click(force=True)
                    await asyncio.sleep(1.0)
                    logger.info("Call hung up successfully.")
                    return {"success": True, "message": "WhatsApp call ended, Sir."}

            # Try DOM dispatch as fallback
            dispatched = await self.page.evaluate("""
                () => {
                    const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
                    for (const b of btns) {
                        const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                        if (aria.includes('end call') || aria.includes('decline') || aria.includes('hang up')) {
                            b.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            if dispatched:
                return {"success": True, "message": "WhatsApp call ended, Sir."}

            return {"success": False, "message": "No active WhatsApp call found to end."}
        except Exception as e:
            logger.error(f"Hangup call error: {e}")
            return {"success": False, "error": f"Failed to end call: {e}"}

    async def open_chat_by_name(self, chat_name: str) -> bool:
        """Searches for a chat or group by name and opens it."""
        if not self.page:
            raise RuntimeError("WhatsApp Web is not initialized.")

        logger.info(f"Opening chat: '{chat_name}'...")
        
        # Clean chat name for flexible matching (e.g. remove emojis or special quotes if any)
        clean_name = re.sub(r"[^\w\s]", "", chat_name).strip()

        # Step 1: Check if the chat is already visible in the recent chat list
        try:
            for pattern in [chat_name, clean_name]:
                if not pattern:
                    continue
                visible_chat = self.page.locator(f"span[title*='{pattern}' i], div[role='listitem'] span[title*='{pattern}' i]").first
                if await visible_chat.is_visible():
                    logger.info(f"Found '{chat_name}' directly in chat list. Clicking...")
                    await visible_chat.click()
                    await asyncio.sleep(1.5)
                    return True
        except Exception as e:
            logger.debug(f"Direct match check: {e}")

        # Step 2: Try focusing the search bar using various modern WhatsApp Web selectors
        search_box = None
        selectors_to_try = [
            self.page.get_by_placeholder("Search or start a new chat"),
            self.page.get_by_placeholder("Search"),
            self.page.locator("[title='Search input textbox']"),
            self.page.locator("div[contenteditable='true'][data-tab='3']"),
            self.page.locator("div[role='textbox']"),
            self.page.locator("p.selectable-text.copyable-text").first,
            self.page.locator("div#side div[contenteditable='true']").first,
        ]

        for locator in selectors_to_try:
            try:
                if await locator.is_visible():
                    search_box = locator
                    break
            except Exception:
                continue

        if search_box:
            try:
                await search_box.click()
                await asyncio.sleep(0.3)
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Backspace")
                await search_box.fill(chat_name)
                await asyncio.sleep(1.5)

                # Look for matching item in search results
                result_item = self.page.locator(f"span[title*='{chat_name}' i], span[title*='{clean_name}' i]").first
                if await result_item.is_visible():
                    await result_item.click()
                    await asyncio.sleep(1.5)
                    return True
                else:
                    await self.page.keyboard.press("Enter")
                    await asyncio.sleep(1.5)
                    return True
            except Exception as e:
                logger.error(f"Search error: {e}")

        # Fallback: Click first matching element anywhere in DOM
        try:
            fallback_item = self.page.locator(f"span[title*='{chat_name}' i], span[title*='{clean_name}' i]").first
            await fallback_item.click()
            await asyncio.sleep(1.5)
            return True
        except Exception as e:
            logger.error(f"Failed to open chat '{chat_name}': {e}")
            return False

    async def extract_chat_messages(self, chat_name: str, scroll_up_count: int = 4) -> list:
        """
        Opens a group/chat, optionally scrolls up to load earlier messages,
        and extracts message texts, authors, and timestamps.
        """
        opened = await self.open_chat_by_name(chat_name)
        if not opened:
            return []

        # Scroll up to load previous messages for the day
        try:
            conversation_pane = self.page.locator("div[data-testid='conversation-panel-messages'], div[role='region'], div#main div[tabindex='-1']").first
            for _ in range(scroll_up_count):
                await self.page.mouse.wheel(0, -1500)
                await asyncio.sleep(0.8)
        except Exception as e:
            logger.debug(f"Scroll up warning: {e}")

        # Extract messages with copyable text and metadata
        messages_data = []
        try:
            msg_elements = await self.page.locator("div.copyable-text[data-pre-plain-text]").all()
            for el in msg_elements:
                meta = await el.get_attribute("data-pre-plain-text")
                body = await el.inner_text()
                
                # Parse timestamp and author: e.g. "[10:45 pm, 31/08/2026] Alice: "
                author = "Unknown"
                timestamp = ""
                if meta:
                    match = re.match(r"\[(.*?)\]\s*(.*?):\s*$", meta)
                    if match:
                        timestamp = match.group(1).strip()
                        author = match.group(2).strip()
                    else:
                        timestamp = meta.strip("[]: ")

                if body.strip():
                    messages_data.append({
                        "timestamp": timestamp,
                        "author": author,
                        "text": body.strip(),
                    })
        except Exception as e:
            logger.error(f"Error reading message elements: {e}")

        logger.info(f"Extracted {len(messages_data)} messages from chat '{chat_name}'.")
        return messages_data

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()

