import os
import time
import base64
import logging
import subprocess
import re
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("VisionAgentTool")

SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


class VisionAgentTool:
    """AI-powered screen vision and GUI automation tool for J.A.R.V.I.S."""

    def _attach_input_desktop(self):
        """Attaches the current thread to the interactive Windows desktop so screen capture never fails."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            h_desk = user32.OpenInputDesktop(0, False, 0x01FF)
            if h_desk:
                user32.SetThreadDesktop(h_desk)
                user32.CloseDesktop(h_desk)
        except Exception as e:
            logger.debug(f"Desktop attach note: {e}")

    def capture_screen(self, region=None):
        """Captures the screen using mss (fast), falling back to PIL ImageGrab.

        Args:
            region: Optional (left, top, width, height) tuple. None = full screen.
        Returns:
            Absolute path to the saved screenshot PNG.
        """
        timestamp = int(time.time())
        filename = "screen_{}.png".format(timestamp)
        path = os.path.join(SCREENSHOTS_DIR, filename)

        self._attach_input_desktop()

        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=region)
            img.save(path, "PNG")
            logger.info("Screen captured via PIL ImageGrab: {}".format(path))
            return path
        except Exception as e:
            logger.warning("PIL ImageGrab note ({}), trying mss...".format(e))

        try:
            import mss
            import mss.tools
            with mss.mss() as sct:
                if region:
                    mon = {"left": region[0], "top": region[1], "width": region[2], "height": region[3]}
                else:
                    mon = sct.monitors[1]
                img = sct.grab(mon)
                mss.tools.to_png(img.rgb, img.size, output=path)
            logger.info("Screen captured via mss: {}".format(path))
            return path
        except Exception as e2:
            logger.error("mss also failed: {}".format(e2))
            raise RuntimeError("Screen capture failed: {}".format(e2))

    def image_to_base64(self, path):
        """Reads an image file and returns its base64-encoded string."""
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def analyze_screen(self, gemini_client, model, question="What is on the screen?"):
        """Captures the screen and asks Gemini Vision to analyze it.
        Supports single full-screen apps and split-screen multi-app layouts.
        Automatically retries across fallback vision models if one is busy or rate-limited.

        Args:
            gemini_client: Initialized google.genai Client instance.
            model: Gemini model name to use for vision.
            question: What to ask about the screen.
        Returns:
            Dict with keys: success, description, screenshot_path, message
        """
        try:
            screenshot_path = self.capture_screen()
            image_b64 = self.image_to_base64(screenshot_path)

            from google.genai import types as genai_types

            # Multi-app and split-screen enhanced prompt
            enhanced_question = (
                f"{question}\n\n"
                "Note: The user may have 2 or 3 apps split across the screen (e.g. browser, college portal, code editor, documents). "
                "Carefully inspect each visible application window, identify what is shown in each section, "
                "read any relevant text/fields, and describe specifically what is on the screen and what actions can be taken."
            )

            models_to_try = [
                model,
                "gemini-3.5-flash",
                "gemini-3.1-flash-lite",
                "gemini-3.7-flash",
                "gemini-3.5-flash-lite",
            ]
            # Deduplicate while preserving order
            seen = set()
            models_to_try = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

            description = None
            last_err = None
            for m in models_to_try:
                try:
                    response = gemini_client.models.generate_content(
                        model=m,
                        contents=[
                            genai_types.Part(
                                inline_data=genai_types.Blob(
                                    mime_type="image/png",
                                    data=image_b64,
                                )
                            ),
                            genai_types.Part(text=enhanced_question),
                        ],
                    )
                    description = response.text or "Screen inspected, Sir."
                    logger.info(f"Screen analyzed successfully using vision model: {m}")
                    break
                except Exception as m_err:
                    last_err = m_err
                    logger.warning(f"Vision model {m} attempt failed: {m_err}, trying next...")
                    continue

            if not description:
                raise last_err or RuntimeError("No vision model responded.")

            return {
                "success": True,
                "description": description,
                "screenshot_path": screenshot_path,
                "message": description,
            }
        except Exception as e:
            logger.error("analyze_screen error: {}".format(e))
            return {
                "success": False,
                "description": "",
                "screenshot_path": "",
                "message": "Screen analysis failed: {}".format(e),
            }

    def find_element_and_click(self, gemini_client, model, element_description):
        """Captures screen, asks Gemini to locate element coordinates, then clicks it.
        Supports multi-model fallback and locates elements across split-screen windows.

        Args:
            gemini_client: Initialized google.genai Client.
            model: Gemini model name.
            element_description: Natural-language description of UI element to find.
        Returns:
            Dict with keys: success, clicked_at, message
        """
        try:
            screenshot_path = self.capture_screen()
            image_b64 = self.image_to_base64(screenshot_path)

            from google.genai import types as genai_types

            prompt = (
                "Look at this screenshot carefully. Find the UI element described as: '{}'.\n"
                "The screen might be split into 2 or 3 open applications. Look across all visible windows, forms, and buttons.\n"
                "Return ONLY a JSON object in this exact format (no extra text, no markdown block):\n"
                "{{\"x\": <integer pixel x coordinate>, \"y\": <integer pixel y coordinate>, \"found\": true}}\n"
                "If the element is not found, return:\n"
                "{{\"found\": false, \"x\": 0, \"y\": 0}}\n"
                "Return only the JSON object, nothing else."
            ).format(element_description)

            models_to_try = [
                model,
                "gemini-3.5-flash",
                "gemini-3.1-flash-lite",
                "gemini-3.7-flash",
                "gemini-3.5-flash-lite",
            ]
            seen = set()
            models_to_try = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

            response_text = None
            last_err = None
            for m in models_to_try:
                try:
                    resp = gemini_client.models.generate_content(
                        model=m,
                        contents=[
                            genai_types.Part(
                                inline_data=genai_types.Blob(
                                    mime_type="image/png",
                                    data=image_b64,
                                )
                            ),
                            genai_types.Part(text=prompt),
                        ],
                    )
                    response_text = resp.text
                    break
                except Exception as m_err:
                    last_err = m_err
                    logger.warning(f"find_element_and_click model {m} note: {m_err}")
                    continue

            if not response_text:
                raise last_err or RuntimeError("No vision model responded.")

            text = response_text.strip()
            json_match = re.search(r'\{[^}]+\}', text, re.DOTALL)
            if not json_match:
                return {"success": False, "clicked_at": None, "message": "Gemini could not parse coords from: {}".format(text)}

            import json
            coords = json.loads(json_match.group())
            if not coords.get("found", False):
                return {"success": False, "clicked_at": None, "message": "Element '{}' not found on screen.".format(element_description)}

            x, y = int(coords["x"]), int(coords["y"])
            self.screen_click(x, y)
            return {
                "success": True,
                "clicked_at": {"x": x, "y": y},
                "message": "Found '{}' at ({}, {}) and clicked it.".format(element_description, x, y),
            }

        except Exception as e:
            logger.error("find_element_and_click error: {}".format(e))
            return {"success": False, "clicked_at": None, "message": "Click operation failed: {}".format(e)}

    def screen_click(self, x, y, double=False):
        """Clicks (or double-clicks) at specific screen coordinates.

        Args:
            x: Horizontal pixel coordinate.
            y: Vertical pixel coordinate.
            double: If True, performs a double-click.
        Returns:
            Dict with success and message.
        """
        try:
            import pyautogui
            pyautogui.moveTo(x, y, duration=0.15)
            if double:
                pyautogui.doubleClick(x, y)
            else:
                pyautogui.click(x, y)
            action = "double-clicked" if double else "clicked"
            logger.info("screen_click: {} at ({}, {})".format(action, x, y))
            return {"success": True, "message": "{} at ({}, {}).".format(action.capitalize(), x, y)}
        except Exception as e:
            logger.error("screen_click error: {}".format(e))
            return {"success": False, "message": "Click failed: {}".format(e)}

    def screen_type(self, text):
        """Types text into the currently focused screen element.

        Uses pyautogui.typewrite for standard ASCII; falls back to pyperclip paste
        for text with special or unicode characters.

        Args:
            text: Text string to type.
        Returns:
            Dict with success and message.
        """
        try:
            import pyautogui
            SPECIAL_CHARS = set('!@#$%^&*()_+-=[]{}|;\'",./<>?`~\\')
            has_special = any(ord(c) > 127 or c in SPECIAL_CHARS for c in text)
            if has_special:
                try:
                    import pyperclip
                    pyperclip.copy(text)
                    time.sleep(0.1)
                    pyautogui.hotkey('ctrl', 'v')
                    logger.info("screen_type: pasted via clipboard ({} chars)".format(len(text)))
                    return {"success": True, "message": "Typed (via clipboard paste): '{}'".format(text[:60])}
                except Exception:
                    pass
            pyautogui.typewrite(text, interval=0.04)
            logger.info("screen_type: typed '{}'".format(text[:60]))
            return {"success": True, "message": "Typed: '{}'".format(text[:60])}
        except Exception as e:
            logger.error("screen_type error: {}".format(e))
            return {"success": False, "message": "Type failed: {}".format(e)}

    def screen_key(self, key_combo):
        """Presses a keyboard key or combination (e.g. 'enter', 'ctrl+a', 'alt+tab').

        Args:
            key_combo: Key name or combo string separated by '+'.
        Returns:
            Dict with success and message.
        """
        try:
            import pyautogui
            keys = [k.strip().lower() for k in key_combo.split('+')]
            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys)
            logger.info("screen_key: pressed '{}'".format(key_combo))
            return {"success": True, "message": "Pressed key: '{}'.".format(key_combo)}
        except Exception as e:
            logger.error("screen_key error: {}".format(e))
            return {"success": False, "message": "Key press failed: {}".format(e)}

    def screen_scroll(self, direction, amount=3):
        """Scrolls the screen up or down by the given number of clicks.

        Args:
            direction: 'up' or 'down'
            amount: Number of scroll clicks.
        Returns:
            Dict with success and message.
        """
        try:
            import pyautogui
            clicks = amount if direction.lower() == "up" else -amount
            pyautogui.scroll(clicks)
            logger.info("screen_scroll: {} by {}".format(direction, amount))
            return {"success": True, "message": "Scrolled {} by {} clicks.".format(direction, amount)}
        except Exception as e:
            logger.error("screen_scroll error: {}".format(e))
            return {"success": False, "message": "Scroll failed: {}".format(e)}

    def arrange_windows_split(self, app1, app2):
        """Snaps two windows side-by-side using Windows Snap Assist.

        Finds both app windows by title keyword, activates app1 and snaps it
        left (Win+Left), then activates app2 and snaps it right (Win+Right).

        Args:
            app1: Title keyword of the app to snap to the LEFT.
            app2: Title keyword of the app to snap to the RIGHT.
        Returns:
            Dict with success and message.
        """
        try:
            import pygetwindow as gw
            import pyautogui

            def find_window(keyword):
                kw = keyword.lower()
                all_wins = gw.getAllWindows()
                for w in all_wins:
                    if kw in (w.title or "").lower() and w.visible:
                        return w
                return None

            win1 = find_window(app1)
            win2 = find_window(app2)

            if not win1:
                return {"success": False, "message": "Window for '{}' not found. Make sure it is open.".format(app1)}
            if not win2:
                return {"success": False, "message": "Window for '{}' not found. Make sure it is open.".format(app2)}

            win1.activate()
            time.sleep(0.4)
            pyautogui.hotkey('win', 'left')
            time.sleep(0.6)

            win2.activate()
            time.sleep(0.4)
            pyautogui.hotkey('win', 'right')
            time.sleep(0.6)

            logger.info("arrange_windows_split: {} (left) | {} (right)".format(app1, app2))
            return {
                "success": True,
                "message": "Arranged '{}' on the left and '{}' on the right, Sir.".format(app1, app2),
            }
        except Exception as e:
            logger.error("arrange_windows_split error: {}".format(e))
            return {"success": False, "message": "Window arrangement failed: {}".format(e)}

    def open_url_in_browser(self, url, browser="chrome"):
        """Opens a URL in Chrome or Edge using subprocess.

        Args:
            url: The URL to open.
            browser: 'chrome' or 'edge'.
        Returns:
            Dict with success and message.
        """
        browser_paths = {
            "chrome": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ],
            "edge": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ],
        }

        exe_candidates = browser_paths.get(browser.lower(), browser_paths["chrome"])
        exe_path = None
        for candidate in exe_candidates:
            if os.path.exists(candidate):
                exe_path = candidate
                break

        if not exe_path:
            try:
                import webbrowser
                webbrowser.open(url)
                time.sleep(2.5)
                return {"success": True, "message": "Opened {} via default browser.".format(url)}
            except Exception as e:
                return {"success": False, "message": "Browser executable not found and fallback failed: {}".format(e)}

        try:
            subprocess.Popen([exe_path, url])
            time.sleep(2.5)
            logger.info("open_url_in_browser: opened {} in {}".format(url, browser))
            return {"success": True, "message": "Opened '{}' in {}, Sir.".format(url, browser.capitalize())}
        except Exception as e:
            logger.error("open_url_in_browser error: {}".format(e))
            return {"success": False, "message": "Failed to open browser: {}".format(e)}
