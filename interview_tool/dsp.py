# -*- coding: utf-8 -*-
"""dsp.py — 门控/断句 DSP（SpeechDetector + GateState），无 IO 纯算法。"""
import threading
import time

import numpy as np

from .config import (
    BLOCK, END_SILENCE, GATE_FAST_ONSET_MIN_GAP, GATE_FAST_ONSET_SEC,
    GATE_RMS_THR, GATE_SILENCE_BLOCKS, MAX_UTTERANCE, MIN_SPEECH,
    SAMPLE_RATE, VAD_RMS_THR,
)

# ---------- VAD 攒句状态机（自动模式：回环轨断面试官句子 / 麦克风轨断你的话） ----------
# 自最早原版单体移植。回调在 feed 内（持有本对象锁）被调——编排线程单线程喂 feed，
# 回调体只允许发事件（event_q.put），禁止拿其他锁 / 调其他 detector 的方法（非重入锁死锁）。
class SpeechDetector:
    """监听音频块 RMS：开口 ≥min_speech 开始攒，停顿 ≥end_silence 句子完成。
    回调：on_speech_start（检测到新语音，作废旧答案）、on_utterance（句子完成）。"""
    def __init__(self, on_speech_start, on_utterance, rms_thr=VAD_RMS_THR,
                 min_speech=MIN_SPEECH, end_silence=END_SILENCE, max_sec=MAX_UTTERANCE):
        self.on_speech_start = on_speech_start
        self.on_utterance = on_utterance
        self.rms_thr = rms_thr
        self.min_speech = min_speech
        self.end_silence = end_silence
        self.max_sec = max_sec
        self._frames = []
        self._pending = []            # 预检测缓存：确认开口时把开头一起算进句子
        self._speech_run = 0
        self._silence_run = 0
        self._started_at = 0.0
        self._lock = threading.Lock()

    def feed(self, block, block_rate):
        rms = float(np.sqrt(np.mean(block ** 2)))
        with self._lock:
            bps = block_rate / BLOCK
            if not self._frames:
                # 预检测：语音持续 ≥min_speech 才确认开口；期间缓存音频，
                # 确认时把缓存一起算进句子（不丢开头——坑：只判断不攒会吃前 1.2s）
                if rms > self.rms_thr:
                    self._speech_run += 1
                    self._pending.append(block)
                    maxp = int(self.min_speech * bps)
                    if len(self._pending) > maxp:
                        self._pending.pop(0)
                    if self._speech_run >= maxp:
                        self._speech_run = 0
                        self._frames = list(self._pending) + [block]
                        self._pending = []
                        self._silence_run = 0
                        self._started_at = time.time()
                        self.on_speech_start()
                else:
                    self._speech_run = 0
                    self._pending.clear()
                return
            self._frames.append(block)
            if rms > self.rms_thr:
                self._silence_run = 0
            else:
                self._silence_run += 1
            if self._silence_run >= int(self.end_silence * bps):
                self._finish()
            elif time.time() - self._started_at > self.max_sec:
                self._finish()

    def flush_now(self):
        """立即结算 in-progress 句子并返回（抢答场景：面试官话没说完你开口，
        半句也要并入 pending 再发送）；未确认开口的预缓存丢弃；无内容返回 None。
        同步返回不回调——编排线程直接处理，保证"并入 pending"先于"发送"执行。"""
        with self._lock:
            self._pending = []
            self._speech_run = 0
            if not self._frames:
                return None
            buf = np.concatenate(self._frames)
            self._frames = []
            self._silence_run = 0
            return buf

    def _finish(self):
        buf = np.concatenate(self._frames)
        self._frames = []
        self._silence_run = 0
        self.on_utterance(buf)

    def reset(self):
        with self._lock:
            self._frames = []
            self._pending = []
            self._silence_run = 0
            self._speech_run = 0

# ---------- 门控状态：回环响/静音（callback 线程写、编排线程读；GIL 单变量写无需锁） ----------
class GateState:
    """回环快速 RMS 判定。loop_hi 用衰减释放（连续低 RMS 块数），
    门控判定用 loop_recent()（含衰减余量）。快速 onset 供打断作废（epoch++）。"""
    def __init__(self):
        self.loop_rms = 0.0           # 最近一块回环 RMS
        self.loop_hi = False          # 回环正在响（衰减判定）
        self.loop_hi_at = 0.0         # 最近一次"响"的时刻（perf_counter）
        self.silent_blocks = 0        # 连续低 RMS 块数
        self.onset_run = 0.0          # 快速 onset 累计有声秒数
        self.last_onset = 0.0         # 上次快速 onset 时刻

    def feed_loop_rms(self, rms):
        """loop callback 每块调用（轻量：浮点比较 + 计数）"""
        now = time.perf_counter()
        self.loop_rms = rms
        if rms > GATE_RMS_THR:
            self.loop_hi = True
            self.loop_hi_at = now
            self.silent_blocks = 0
            self.onset_run += BLOCK / SAMPLE_RATE
        else:
            self.silent_blocks += 1
            if self.silent_blocks >= GATE_SILENCE_BLOCKS:
                self.loop_hi = False
            if self.onset_run and now - self.loop_hi_at > 0.2:
                self.onset_run = 0.0  # 静音中断快速 onset

    def fast_onset_hit(self):
        """编排线程调用：回环连续有声 ≥GATE_FAST_ONSET_SEC 且距上次足够久 → 返回 True（作废）"""
        now = time.perf_counter()
        if self.onset_run >= GATE_FAST_ONSET_SEC and \
                now - self.last_onset > GATE_FAST_ONSET_MIN_GAP:
            self.last_onset = now
            self.onset_run = 0.0
            return True
        return False

    def loop_recent(self):
        """回环最近是否响过（含 0.4s 衰减余量）——门控判定用"""
        return self.loop_hi or (time.perf_counter() - self.loop_hi_at) < 0.4

    def reset(self):
        self.__init__()
