# -*- coding: utf-8 -*-
"""vision.py — 截屏识图（火山豆包视觉 / 百炼 qwen-vl 兼容两家接口）。

共享主本取 code 版（code ⊃ quiz）：_ask_vision_multi 多图核心 + VIS_MEM 多轮记忆助手
为 code 独有能力，quiz 永不引用（可选能力在场）。VISION_MODEL/BASE_URL/FALLBACK_URL
两版逐字相同故留在本模块。VISION_PROMPT/VISION_MAX_TOKENS 此处暂居 code 版——两版
文本不同，Step 5 收进 profiles.py 的 Profile 字段，do_vision 经 ACTIVE 取用。
do_vision 统一主本（code 版；quiz 问图段更简，同构差异收敛到 profiles）。"""
from .config import _env_get
from .log import log_event
from .state import VIS_MEM, VISION_STATE

# ---------- Alt+P 截屏识图（手撕代码场景：面试官共享屏幕出题 / 笔试 OJ 截图直接出答案） ----------
# 兼容两家 OpenAI 风格接口，用 .env 三件套切换，不用改代码：
#   ARK_API_KEY        = 识图 API key
#   ARK_VISION_MODEL   = 模型名（火山 doubao-1.5-vision-lite-250315 / 百炼 qwen-vl-plus）
#   VISION_BASE_URL    = 接口地址（默认火山 chat/completions；百炼填
#                        https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions）
VISION_MODEL = "doubao-1.5-vision-lite-250315"     # 默认火山豆包轻量视觉（便宜快）
VISION_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
VISION_FALLBACK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
VISION_PROMPT = ("你是笔试/手撕代码助手。本次请求可能附带【历史截图】（同一道题此前截的片段，"
                 "旧→新排列，可能是没截全的题目拼图、运行报错、测试用例输出）和【此前解答】文本，"
                 "最后一张是【最新截图】。\n"
                 "规则1：先判断最新截图与历史内容是否同一道题——\n"
                 "  · 同一题的补充（题目分两次截没拼全 / 报错信息 / 测试用例输出 / 要求继续优化）："
                 "必须结合历史与上次解答处理。报错类先一句话说原因，再给【修改后的完整代码】"
                 "（不许只给 diff/省略号，改动点一行带过）；拼图类把题目信息拼全后正常作答。\n"
                 "  · 明显是全新题目：忽略历史，按新题作答。\n"
                 "规则2：严禁输出思考摸索过程（试错、草稿、多方案对比、'我看看'之类）——只给结论。\n"
                 "规则3：输出固定三块——\n"
                 "【思路】最多 5 条分点，每条一行内，点明算法名/关键步骤；\n"
                 "【代码】完整可运行的代码放 markdown 代码块（按题目要求语言，默认 Python）；\n"
                 "【复杂度】一行。\n"
                 "中文简洁，直接给结论，不要任何前言。")
VISION_MAX_TOKENS = 4096   # 输出上限显式声明：不写就吃服务商默认（智谱 glm-4v-flash 默认仅 1024 token，
                           # 长代码答案必截断——历史"输出不完全"根因）。4096 覆盖手撕代码完整输出


def _vis_mem_note(img_pil, ans):
    """识图答成后记一笔：当前截图压 q80/≤1440 存 b64，答案截前 4000 字；
    截图留最近 6 张、解答留最近 4 条（丢最旧——题目图若被挤掉，续截时补一张即可）。
    答崩（❌）不记——失败历史喂回去只会带偏下一轮"""
    try:
        import io as _io
        import base64 as _b64
        from PIL import Image as _PImage
        w, h = img_pil.size
        sc = min(1.0, 1440.0 / max(w, h))
        if sc < 1.0:
            img_pil = img_pil.resize((max(1, int(w * sc)), max(1, int(h * sc))),
                                     resample=_PImage.LANCZOS)
        buf = _io.BytesIO()
        img_pil.convert("RGB").save(buf, "JPEG", quality=80)
        VIS_MEM["imgs"].append(_b64.b64encode(buf.getvalue()).decode())
        if len(VIS_MEM["imgs"]) > 6:
            del VIS_MEM["imgs"][0]
        a = (ans or "").strip()
        if a:
            VIS_MEM["ans"].append(a[:4000])
            if len(VIS_MEM["ans"]) > 4:
                del VIS_MEM["ans"][0]
    except Exception:
        pass                                    # 记忆失败不影响主链路

def _vis_mem_reset(why=""):
    """换新题时清空多轮记忆（Alt+3 触发），防旧题截图/旧解答污染新题。返回是否真丢了内容"""
    n_img, n_ans = len(VIS_MEM["imgs"]), len(VIS_MEM["ans"])
    VIS_MEM["imgs"] = []
    VIS_MEM["ans"] = []
    try:
        log_event({"type": "vis_mem_reset", "why": why,
                   "dropped_imgs": n_img, "dropped_ans": n_ans})
    except Exception:
        pass
    return (n_img + n_ans) > 0

def _vis_mem_parts():
    """历史截图 → API parts 列表（旧→新；主流程把最新截图追加在后）"""
    return [{"b64": b} for b in VIS_MEM["imgs"]]

def _vis_mem_prompt_suffix():
    """此前成功解答 → prompt 后缀：告诉模型这是上一轮自己给的答案，报错修复/继续优化对照用"""
    if not VIS_MEM["ans"]:
        return ""
    s = "\n\n【此前解答】（我上一轮给出的回答——报错修复或继续优化时以此为基础改，供对照）：\n"
    for i, a in enumerate(VIS_MEM["ans"], 1):
        s += f"——第 {i} 轮解答——\n{a}\n"
    return s


def _vision_parse(j):
    """解析 chat/completions / responses 两种响应格式，返回文本"""
    try:                                            # chat/completions 格式（主流）
        c = j["choices"][0]["message"]
        if c.get("content"):
            return c["content"]
        rc = c.get("reasoning_content") or ""       # content 空：只认「非英文思考流」的兜底
        if rc and not rc.lstrip().startswith(("The user", "Let me", "We need", "I need", "Okay")):
            return rc
        return None                                 # 纯思考流（deepseek-v4 实测）→ 当没答案，交给上层报清晰错误
    except Exception:
        try:                                        # responses 格式（火山新接口）
            out = j["output"]
            return "".join(c.get("text", "") for c in out[0]["content"] if isinstance(c, dict))
        except Exception:
            return None

def _crop_center_zoom(img, fx=1.8):
    """裁屏幕中央 60% 宽 × 75% 高（题目主体一般在中间偏上）再放大 fx 倍——
    小图形/小数字整图里看不清，裁出来放大后模型才认得（穷替版 VisualCoT）"""
    from PIL import Image
    w, h = img.size
    cw, ch = int(w * 0.6), int(h * 0.75)
    x0, y0 = (w - cw) // 2, int(h * 0.08)           # 中央略偏上：题目区一般在中上部
    crop = img.crop((x0, y0, x0 + cw, y0 + ch))
    return crop.resize((max(1, int(cw * fx)), max(1, int(ch * fx))), resample=Image.LANCZOS)

def _ask_vision_multi(key, model, url, parts, prompt, max_tokens):
    """多图识图核心（2026-09-06 多轮记忆的基础，单请求多图已实测支持）：
    parts 每项是 PIL.Image 或 {"b64": 已编码字符串}，按旧→新排列，最后一张最新；
    一次性全喂——同题续截（拼图/报错）模型自己对照，省一次往返。
    返回 (答案文本 or None, HTTP 状态码)；chat/completions 格式被拒(400)时自动回退 responses 格式"""
    import io as _io
    import base64 as _b64
    import requests
    b64s = []
    for p in parts:
        if isinstance(p, dict) and p.get("b64"):
            b64s.append(p["b64"])
        else:
            buf = _io.BytesIO()
            p.convert("RGB").save(buf, "JPEG", quality=92)  # q92：小图形细节不再压糊
            b64s.append(_b64.b64encode(buf.getvalue()).decode())
    hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    imgs = [{"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in b64s]
    body = {"model": model, "messages": [{"role": "user",
            "content": imgs + [{"type": "text", "text": prompt}]}], "max_tokens": max_tokens}
    r = requests.post(url, headers=hdr, json=body, timeout=60)
    if r.status_code == 200:
        return _vision_parse(r.json()), 200
    if r.status_code == 400:                        # chat 格式被拒 → 回退 responses 格式
        body2 = {"model": model, "input": [{"role": "user", "content":
            [{"type": "input_image",
              "image_url": f"data:image/jpeg;base64,{b}"} for b in b64s] +
            [{"type": "input_text", "text": prompt}]}]}
        r2 = requests.post(VISION_FALLBACK_URL, headers=hdr, json=body2, timeout=60)
        if r2.status_code == 200:
            return _vision_parse(r2.json()), 200
        return None, r2.status_code
    return None, r.status_code

def _ask_vision_once(key, model, url, img, prompt, max_tokens):
    """单张 PIL 图入口（保留旧签名兼容）→ 走多图核心"""
    return _ask_vision_multi(key, model, url, [img], prompt, max_tokens)

def do_vision(ui):
    """Alt+P 识图主流程（后台线程）：全屏截图 →（自动带上同题历史截图+上次解答）→ 识图 API →
    答案窗显示。答成记入多轮记忆；整图失败裁剪放大重试且复用同一份上下文，不打断主链路"""
    try:
        key = _env_get("ARK_API_KEY")
        if not key:
            ui("status", "❌ 缺 ARK_API_KEY：.env 里填识图 API key")
            return
        model = _env_get("ARK_VISION_MODEL") or VISION_MODEL   # 可在 .env 覆盖模型名
        url = _env_get("VISION_BASE_URL") or VISION_BASE_URL   # 可在 .env 换服务商
        from PIL import Image, ImageGrab
        import time as _time
        ui("ov_ctl", "hide")                        # 置顶窗先离场：它会被截进图，模型看见「Alt+P截」等字样拒答
        try:
            _time.sleep(0.35)                       # 等 Tk 主线程 withdraw + 合成一帧
            img = ImageGrab.grab()                  # 全屏
        finally:
            ui("ov_ctl", "restore")                 # 截完立刻回来（不等 API，闪感最小）
        w, h = img.size
        scale = min(1.0, 1920.0 / max(w, h))        # 最长边压到 1920（看清小图形细节）
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                             resample=Image.LANCZOS)
        # 多轮记忆：历史截图（旧→新）+ 当前新图一并发；prompt 附此前解答文本
        parts = _vis_mem_parts() + [img]
        prompt = VISION_PROMPT + _vis_mem_prompt_suffix()
        mem_n = len(VIS_MEM["imgs"])
        ans, st = _ask_vision_multi(key, model, url, parts, prompt, VISION_MAX_TOKENS)
        if not ans:                                 # 整图（含历史）没答出来 → 中央裁剪放大再看一眼
            ui("status", "🔍 整图没认出，放大题目重看中…")
            zoom = _crop_center_zoom(img)
            ans2, st2 = _ask_vision_multi(key, model, url,
                                          _vis_mem_parts() + [zoom], prompt, VISION_MAX_TOKENS)
            if ans2:
                ans = f"（整图没答出，放大重看）\n{ans2}"
            else:
                ans = (f"❌ 模型没答出来（整图 HTTP {st} / 放大 HTTP {st2}），"
                       f"重按 Alt+P 截一次或语音问我")
        if ans and not ans.startswith("❌"):
            _vis_mem_note(img, ans)                 # 答成才记，答崩不污染记忆
        ui("vision", ans)
        log_event({"type": "vision", "ok": bool(ans and not ans.startswith("❌")),
                   "err": None if (ans and not ans.startswith("❌")) else (ans or "")[:200],
                   "answer": ans[:2000], "ans_len": len(ans or ""),
                   "truncated": bool(ans) and len(ans) > 2000,
                   "mem_imgs": mem_n, "mem_ans": len(VIS_MEM["ans"])})
    except Exception as e:
        ui("status", f"❌ 识图异常: {e}")
    finally:
        VISION_STATE["busy"] = False
