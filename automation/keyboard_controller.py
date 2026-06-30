"""
微信自动化键盘控制器
"""
import time
import pyautogui
import pyperclip


class KeyboardController:
    def __init__(self, config: dict = None):
        self.config = config or {}

    def type_text(self, text: str) -> bool:
        try:
            pyperclip.copy(text)
            paste_delay = self.config.get('paste_delay', 0.3)
            time.sleep(paste_delay)
            pyautogui.hotkey('ctrl', 'v')
            return True
        except Exception as e:
            return False

    def press_enter(self) -> bool:
        try:
            pyautogui.press('enter')
            send_delay = self.config.get('send_delay', 1.0)
            time.sleep(send_delay)
            return True
        except Exception as e:
            return False

    def clear_input(self) -> bool:
        try:
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.1)
            pyautogui.press('delete')
            return True
        except Exception as e:
            return False

    def send_text(self, text: str) -> bool:
        if not self.type_text(text):
            return False
        return self.press_enter()

    def copy_selected(self) -> str:
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(0.2)
        return pyperclip.paste()
