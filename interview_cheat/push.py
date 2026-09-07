# -*- coding: utf-8 -*-
"""push.py — Telegram 手机推送（兜底渠道）。"""
from .config import _env_get

def push_answer(question, answer):
    """答案推送手机（独立线程 fire-and-forget；失败只打日志，不影响主链路）
    模块级且自读 .env：poll()（模块级）也要调——原来定义在 main() 局部，
    push_on 作用域修好后 NameError 就转移到了这里，手机推送才真正生效"""
    import threading
    tg_token = _env_get("BOT_TOKEN")
    tg_ids = [int(x) for x in _env_get("ALLOWED_IDS").split(",") if x.strip()]
    tg_chat_id = tg_ids[0] if tg_ids else 0
    PROXY = _env_get("PROXY")
    if not tg_token or not tg_chat_id:
        return

    def _run():
        import requests
        try:
            text = f"❓ {question}\n\n💡 {answer}"
            if len(text) > 3900:
                text = text[:3900]
            resp = requests.post(
                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                data={"chat_id": tg_chat_id, "text": text},
                proxies={"http": PROXY, "https": PROXY} if PROXY else None,
                timeout=(10, 20))
            if not resp.json().get("ok"):
                print(f"⚠️ 手机推送失败: {resp.text[:100]}", flush=True)
            else:
                print("📱 答案已推送到手机", flush=True)
        except Exception as e:
            print(f"⚠️ 手机推送异常: {e}", flush=True)

    threading.Thread(target=_run, daemon=True).start()
