# -*- coding: utf-8 -*-
"""Supervised auto-gripper bench test, using native HA8 UART protocol.

Software stop is NOT a hardware emergency stop. It depends on the serial link.
"""
from __future__ import annotations

import math
import time
import tkinter as tk
from tkinter import ttk, messagebox

from ha8_protocol import HA8Protocol, STOP_HOLD
from grip_estimator import GripDetector, GripSettings, GripSample, GripState


class AutoGripPanel(ttk.Frame):
    POLL_MS = 100
    STALE_S = 0.65

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.state = '待机'
        self.estop_latched = False
        self.phase = None
        self.servo_id = None
        self.active_servo_id = None  # Freeze the target ID until reset.
        self.last_at = None
        self.angle = None
        self.current = None
        self.status_bits = None
        self.detector = None
        self.started = None
        self._stop_sent = False
        self._job = None
        self.session_min = None
        self.session_max = None
        self.session_hold = None
        self._stop_at = None
        self._stop_previous = None
        self._stop_stable_count = 0
        self._stop_reason = ''
        self.param_entries = []
        self.grip_min = tk.StringVar(value='')
        self.open_max = tk.StringVar(value='')
        self.speed = tk.StringVar(value='10')  # Conservative uncalibrated bench default.
        self.power = tk.StringVar(value='1500')
        self.hold_power = tk.StringVar(value='500')
        self.current_text = tk.StringVar(value='— A')
        self.angle_text = tk.StringVar(value='— °')
        self.status_text = tk.StringVar(value='待机；首先完成参数设置及实机标定')
        self.feedback_text = tk.StringVar(value='实时反馈：尚未收到有效监控')
        self._build()
        self._job = self.after(self.POLL_MS, self._tick)

    def _build(self):
        # Daily-use controls only. Calibration and algorithm tuning live in Advanced.
        main = ttk.Frame(self, padding=(14, 10))
        main.pack(fill="both", expand=True)

        status = ttk.LabelFrame(main, text="② 当前状态", padding=14)
        status.pack(fill="x", pady=(0, 12))
        values = ttk.Frame(status)
        values.pack(fill="x")
        ttk.Label(values, text="实时电流", font=("Microsoft YaHei UI", 11)).grid(
            row=0, column=0, sticky="w", padx=(0, 85))
        ttk.Label(values, text="当前位置", font=("Microsoft YaHei UI", 11)).grid(
            row=0, column=1, sticky="w")
        ttk.Label(values, textvariable=self.current_text, font=("Consolas", 24, "bold")).grid(
            row=1, column=0, sticky="w", padx=(0, 85), pady=(2, 6))
        ttk.Label(values, textvariable=self.angle_text, font=("Consolas", 24, "bold")).grid(
            row=1, column=1, sticky="w", pady=(2, 6))
        ttk.Label(status, textvariable=self.feedback_text, foreground="#555555").pack(anchor="w")
        self.pressure_validation_text = tk.StringVar(value="压力验证：未连接（请到“压力验证 / 曲线”页设置）")
        ttk.Label(status, textvariable=self.pressure_validation_text, foreground="#78521c",
                  wraplength=800).pack(anchor="w", pady=(3, 0))

        limits = ttk.LabelFrame(main, text="③ 夹爪运动范围", padding=14)
        limits.pack(fill="x", pady=(0, 12))
        ttk.Label(limits, text="抓取最小角度 (°)", font=("Microsoft YaHei UI", 11)).grid(
            row=0, column=0, sticky="w", padx=(0, 50))
        ttk.Label(limits, text="张开最大角度 (°)", font=("Microsoft YaHei UI", 11)).grid(
            row=0, column=1, sticky="w")
        self.param_entries = []
        for column, variable in enumerate((self.grip_min, self.open_max)):
            entry = ttk.Entry(limits, textvariable=variable, width=19, font=("Consolas", 14))
            entry.grid(row=1, column=column, sticky="w", pady=7, padx=(0, 50))
            self.param_entries.append(entry)
        ttk.Label(limits, text="角度减小＝闭合；角度增大＝张开。两端数值必须先实际标定。",
                  foreground="#777777").grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        ttk.Label(main, text="④ 操作", font=("Microsoft YaHei UI", 11, "bold")).pack(
            anchor="w", pady=(0, 7))
        actions = ttk.Frame(main)
        actions.pack(fill="x")
        self.grip_btn = ttk.Button(actions, text="抓取  /  闭合", command=self.grip,
                                   width=19, style="Action.TButton")
        self.grip_btn.pack(side="left", padx=(0, 12))
        self.open_btn = ttk.Button(actions, text="张开", command=self.open,
                                   width=15, style="Action.TButton")
        self.open_btn.pack(side="left", padx=(0, 12))
        self.stop_btn = ttk.Button(actions, text="立即停止（软件）", command=self.emergency_stop,
                                   style="Danger.TButton")
        self.stop_btn.pack(side="left")

        tools = ttk.Frame(main)
        tools.pack(fill="x", pady=(12, 7))
        self.reset_btn = ttk.Button(tools, text="解除停止锁定", command=self.reset_estop)
        self.reset_btn.pack(side="left")
        self.settings_btn = ttk.Button(tools, text="更多设置  ▾", command=self.toggle_settings)
        self.settings_btn.pack(side="right")

        self.advanced_settings = ttk.LabelFrame(main, text="高级参数（未标定前请勿提高）", padding=12)
        for index, (label, variable) in enumerate((
            ("运动速度 (°/s)", self.speed), ("运动功率上限 (mW)", self.power),
            ("停止保持功率 (mW)", self.hold_power)
        )):
            ttk.Label(self.advanced_settings, text=label).grid(
                row=index, column=0, sticky="w", padx=6, pady=4)
            entry = ttk.Entry(self.advanced_settings, textvariable=variable, width=18)
            entry.grid(row=index, column=1, sticky="w", padx=6, pady=4)
            self.param_entries.append(entry)
        self.monitor_btn = ttk.Button(self.advanced_settings,
                                      text="开启实时监控", command=self.toggle_panel_monitor)
        self.monitor_btn.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 2))
        self.settings_visible = False

        ttk.Label(main, textvariable=self.status_text, foreground="#a31717",
                  wraplength=850, font=("Microsoft YaHei UI", 11)).pack(
            fill="x", pady=(8, 6))
        ttk.Label(main,
                  text="实验功能：接触检测不等于抓稳。软件停止依赖串口，必须配备独立硬件断电急停。",
                  foreground="#a31717", wraplength=850).pack(anchor="w")
        self._refresh_controls()

    def toggle_settings(self):
        self.settings_visible = not self.settings_visible
        if self.settings_visible:
            self.advanced_settings.pack(fill="x", pady=(0, 8))
        else:
            self.advanced_settings.pack_forget()
        self.settings_btn.configure(text="收起设置  ▴" if self.settings_visible else "更多设置  ▾")

    def toggle_panel_monitor(self):
        """Use the existing shared monitor task; do not create competing serial pollers."""
        if not self.app.monitor_running and not self.app.transport.is_open:
            messagebox.showwarning('监控未启动', '先连接官方 USB 串口转接板，再开启实时监控。')
            return
        if self.phase:
            messagebox.showwarning('正在运动', '抓取/张开/停止确认期间不能关闭实时监控。')
            return
        self.app.toggle_monitor()
        self._refresh_controls()

    def _refresh_controls(self):
        busy = bool(self.phase)
        for entry in getattr(self, 'param_entries', ()):
            entry.configure(state='disabled' if busy else 'normal')
        # Keep unavailable actions visibly disabled instead of allowing blind attempts.
        connected = self.app.transport.is_open
        fresh = self.last_at is not None and time.monotonic() - self.last_at <= self.STALE_S
        ready = connected and self.app.monitor_running and fresh
        for btn_name in ('grip_btn', 'open_btn'):
            btn = getattr(self, btn_name, None)
            if btn is not None:
                btn.configure(state='normal' if ready and not busy and not self.estop_latched else 'disabled')
        stop_btn = getattr(self, 'stop_btn', None)
        if stop_btn is not None:
            stop_btn.configure(state='normal' if connected else 'disabled')
        reset_btn = getattr(self, 'reset_btn', None)
        if reset_btn is not None:
            reset_btn.configure(state='normal' if self.estop_latched and not busy else 'disabled')
        monitor_btn = getattr(self, 'monitor_btn', None)
        if monitor_btn is not None:
            monitor_btn.configure(text='停止实时监控' if self.app.monitor_running else '开启实时监控',
                                  state='disabled' if busy else 'normal')

    def _parameters(self):
        lo=float(self.grip_min.get()); hi=float(self.open_max.get())
        vel=float(self.speed.get());power=int(self.power.get());hold=int(self.hold_power.get())
        if not all(math.isfinite(v) for v in (lo,hi,vel,power,hold)):
            raise ValueError('所有参数必须为有限数字')
        if not lo < hi or hi-lo < 3:
            raise ValueError('抓取最小角度必须小于张开最大角度，行程至少 3°')
        if not 0 < vel <= 300 or not 0 <= power <= 30000 or not 0 <= hold <= 30000:
            raise ValueError('速度应为 0~300°/s，功率限制为 0~30000mW；确认机型额定能力')
        return lo,hi,vel,power,hold

    def _preflight(self):
        if self.estop_latched:
            raise RuntimeError('软件急停已锁定；检查机械状态后才能解除')
        if self.phase:
            raise RuntimeError('仍有正在运行的抓取/张开任务，请先软件急停')
        if not self.app.transport.is_open:
            raise RuntimeError('官方串口未连接')
        if not self.app.monitor_running:
            raise RuntimeError('请在本页面点击“开启实时监控”（建议100ms）')
        if getattr(self.app, 'scan_running', False):
            raise RuntimeError('正在扫描舵机 ID，请先结束扫描再进行自动动作')
        sid=self.app.servo_id()
        if self.last_at is None or time.monotonic()-self.last_at>self.STALE_S or self.servo_id!=sid:
            raise RuntimeError('当前舵机角度/电流反馈已过期或ID不匹配，禁止盲动')
        if self.status_bits is None or self.status_bits & 0xFE:
            raise RuntimeError('存在堵转或设备保护故障，禁止运动')
        return sid

    def _move(self,target,vel,power,sid):
        frame=HA8Protocol.move(servo_id=sid,angle_deg=target,multiturn=True,mode='velocity',
                              velocity_dps=vel,t_acc_ms=200,t_dec_ms=200,power_mw=power)
        self.app.send_ha8(frame,'自动抓取测试：发送目标角度',owner='auto_grip')

    def grip(self):
        try:
            lo,hi,vel,power,hold=self._parameters()
            sid=self._preflight()
            if not lo+1 <= self.angle <= hi+1:
                raise ValueError('当前角度不在抓取试验允许区间，请先核对零位及机械限位')
            if not messagebox.askyesno('抓取确认',f'从 {self.angle:.1f}° 向 {lo:.1f}° 闭合；无接触时也会继续向最小角度运动。\n确认夹爪无干涉且硬件急停可用？'):
                return
            ref=self.app.grip_panel.detector.settings
            settings=GripSettings(baseline_a=ref.baseline_a, contact_delta_a=ref.contact_delta_a,
                minimum_grip_current_a=ref.minimum_grip_current_a,maximum_safe_current_a=ref.maximum_safe_current_a,
                low_speed_dps=ref.low_speed_dps,stable_seconds=ref.stable_seconds,
                minimum_travel_deg=ref.minimum_travel_deg,closing_direction=-1,
                valid_angle_min=lo,valid_angle_max=hi,stale_seconds=ref.stale_seconds,
                window_size=ref.window_size)
            self.detector=GripDetector(settings,self.app.grip_panel.detector.curve)
            self.detector.arm(time.monotonic())
            if self._preflight() != sid:
                raise RuntimeError('舵机 ID 在确认期间发生改变，取消本次动作')  # Confirmation dialogs can outlive fresh feedback.
            self.phase='gripping';self.started=time.monotonic();self._stop_sent=False
            self.active_servo_id=sid
            self.session_min,self.session_max,self.session_hold=lo,hi,hold
            self._refresh_controls()
            self._move(lo,vel,power,sid)
            lab = getattr(self.app, "pressure_lab", None)
            if lab is not None:
                lab.on_grip_start()  # Read-only experiment; no pressure control path.
            self.status_text.set('抓取中：等待接触判定，或在最小角度前停止')
        except Exception as e:
            if self.phase:
                self.estop_latched=True  # May have initiated a command; operator must check.
            self.phase=None
            self.detector=None
            self._refresh_controls()
            messagebox.showerror('抓取失败',str(e))

    def open(self):
        try:
            lo,hi,vel,power,hold=self._parameters()
            sid=self._preflight()
            if not lo-1 <= self.angle <= hi+1:
                raise ValueError('当前位置超出试验范围，禁止张开')
            if not messagebox.askyesno('张开确认',f'将张开至 {hi:.1f}°。确认机械限位与周边安全？'):
                return
            self.detector=None
            if self._preflight() != sid:
                raise RuntimeError('舵机 ID 在确认期间发生改变，取消本次动作')  # Re-check after modal.
            self.phase='opening';self.started=time.monotonic();self._stop_sent=False
            self.active_servo_id=sid
            self.session_min,self.session_max,self.session_hold=lo,hi,hold
            self._refresh_controls()
            self._move(hi,vel,power,sid)
            self.status_text.set('张开中，等待角度反馈确认')
        except Exception as e:
            if self.phase:
                self.estop_latched=True
            self.phase=None
            self.detector=None
            self._refresh_controls()
            messagebox.showerror('张开失败',str(e))

    def _send_hold(self,reason):
        if self._stop_sent:
            return
        self._stop_sent=True
        try:
            power = self.session_hold
            if power is None:
                power = int(float(self.hold_power.get()))
            if not 0 <= power <= 30000:
                power = 0
            if not self.app.transport.is_open:
                raise RuntimeError('串口已断开')
            sid = self.active_servo_id if self.active_servo_id is not None else self.app.servo_id()
            self.app.send_ha8(HA8Protocol.stop(sid, STOP_HOLD, power),
                              f'自动抓取测试：保持停止（{reason}）',owner='auto_grip')
            self.phase = 'stopping'
            self.detector = None
            self._stop_at = time.monotonic()
            self._stop_previous = None
            self._stop_stable_count = 0
            self._stop_reason = reason
            self.status_text.set(f'{reason}；已发送保持停止，正在观察角度是否稳定（非安全确认）')
        except Exception as ex:
            self._stop_unconfirmed(f'停止指令发送失败：{ex}')
        self._refresh_controls()

    def on_external_hold(self):
        """A different page sent HOLD to this session's servo: lock and observe."""
        self.estop_latched = True
        self._stop_sent = True
        self.phase = 'stopping'
        self.detector = None
        self._stop_at = time.monotonic()
        self._stop_previous = None
        self._stop_stable_count = 0
        self._stop_reason = '其他页面下发保持停止'
        self.status_text.set('外部保持停止已发送，正在核对角度稳定；软件急停已锁定')
        self._refresh_controls()

    def _stop_unconfirmed(self, reason):
        self.phase = None
        self.detector = None
        self.estop_latched = True
        self._stop_sent = True
        self.status_text.set(f'{reason}；停止未确认，请使用硬件急停并人工检查')
        self.app.log(f'自动抓取测试：{reason}；STOP_UNCONFIRMED')
        lab = getattr(self.app, "pressure_lab", None)
        if lab is not None:
            lab.on_grip_end(reason, confirmed_motion_stop=False)
            self.pressure_validation_text.set(lab.evidence_text.get())
        self._refresh_controls()

    def _observe_stopping(self, now):
        """Consecutive low-angle-speed samples are a diagnostic, NOT safety proof."""
        if self._stop_at is None:
            self._stop_unconfirmed('停止确认上下文缺失')
            return
        if self.status_bits & 0xFE:
            self.estop_latched = True
        if self._stop_previous is not None:
            then, angle = self._stop_previous
            dt = now - then
            if dt >= 0.03 and abs((self.angle - angle) / dt) <= 2.0:
                self._stop_stable_count += 1
            else:
                self._stop_stable_count = 0
        self._stop_previous = (now, self.angle)
        if self._stop_stable_count >= 3 and now - self._stop_at >= 0.25:
            self.phase = None
            self._stop_sent = False
            if not self.estop_latched:
                self.active_servo_id = None
            self.status_text.set(
                f'{self._stop_reason}；反馈角度连续稳定（仅软件观测，实际停机及夹持力仍待验证）'
                + ('；软件急停锁定中' if self.estop_latched else '')
            )
            lab = getattr(self.app, "pressure_lab", None)
            if lab is not None:
                lab.on_grip_end(self._stop_reason, confirmed_motion_stop=not self.estop_latched)
                self.pressure_validation_text.set("压力验证：" + lab.evidence_text.get())
            self._refresh_controls()

    def emergency_stop(self):
        self.estop_latched=True
        self.phase=None
        self.detector=None
        self._stop_sent=False
        self._send_hold('软件急停已锁定')
        self.app.log('自动抓取测试：触发软件急停；必须人工确认后解锁。')
        self._refresh_controls()

    def reset_estop(self):
        if not self.estop_latched:return
        if not messagebox.askyesno('解除软件急停', '确认舵机已停止、夹爪无碰撞风险、可重新进行台架试验？'):
            return
        if self.phase:
            messagebox.showwarning('暂不能解锁', '仍在等待停止反馈，请先确认真实停止。')
            return
        self.estop_latched=False
        self._stop_sent=False
        self.session_hold=None
        self.active_servo_id=None
        self.status_text.set('软件急停锁定已解除，待机')
        self._refresh_controls()

    def on_monitor(self,servo_id,fields):
        expected_id = self.active_servo_id if self.phase and self.active_servo_id is not None else self.app.servo_id()
        if servo_id != expected_id:
            return
        now=time.monotonic()
        self.servo_id=servo_id;self.last_at=now
        self.angle=float(fields['angle_deg'])
        self.current=float(fields['current_ma'])/1000
        self.status_bits=int(fields['status'])
        self.angle_text.set(f'{self.angle:.1f} °')
        self.current_text.set(f'{self.current:.3f} A')
        if hasattr(self, 'feedback_text'):
            self.feedback_text.set(f'监控正常  ·  舵机 ID {servo_id}'
                                   if not self.status_bits & 0xFE
                                   else '设备报告异常，请停止并检查')
        if self.phase == 'stopping':
            self._observe_stopping(now)
            return
        if not self.phase or self.estop_latched:return
        if self.status_bits & 0xFE:
            self.emergency_stop();return
        if self.phase=='gripping' and self.detector is not None:
            result=self.detector.observe(GripSample(now,self.angle,self.current,self.status_bits))
            if result.state in (GripState.CONTACT,GripState.CANDIDATE):
                self._send_hold(result.state.value)
                return
            if result.state in (GripState.FAULT,GripState.INVALID,GripState.STALE):
                self.emergency_stop();return
            lo=self.session_min
            if self.angle<=lo+0.8:
                self._send_hold('到达抓取最小角度（未确认抓到物体）')
        elif self.phase=='opening':
            hi=self.session_max
            if self.angle>=hi-0.8:
                self._send_hold('已接近张开最大角度')

    def _tick(self):
        if hasattr(self, 'feedback_text'):
            fresh = self.last_at is not None and time.monotonic() - self.last_at <= self.STALE_S
            if not fresh:
                self.feedback_text.set('实时反馈：无有效数据 / 数据超时')
                self.current_text.set('— A')
                self.angle_text.set('— °')
            elif not self.app.monitor_running:
                self.feedback_text.set('监控已暂停，可在“更多设置”中重新开启')
        if self.phase:
            now=time.monotonic()
            if self.phase == 'stopping':
                if (self.last_at is None or now-self.last_at>self.STALE_S
                        or self._stop_at is None or now-self._stop_at>2.0):
                    self._stop_unconfirmed('停止后反馈超时或角度未稳定')
            elif not self.estop_latched:
                try:
                    selected_id = self.app.servo_id()
                except (ValueError, tk.TclError):
                    selected_id = None
                if self.active_servo_id is not None and selected_id != self.active_servo_id:
                    self.emergency_stop()
                elif (self.last_at is None or now-self.last_at>self.STALE_S
                        or self.started is not None and now-self.started>20.0):
                    self.emergency_stop()
        self._refresh_controls()
        self._job=self.after(self.POLL_MS,self._tick)

    def disconnected(self):
        if self.phase or self._stop_sent:
            self.estop_latched=True  # Reconnect must not silently re-enable motion.
        self.phase=None;self.detector=None
        self.last_at=None;self.servo_id=None
        self.current_text.set('— A');self.angle_text.set('— °')
        self.status_text.set('串口已断开，停止检测；软件无法保证电机停止')
        if hasattr(self, 'feedback_text'):
            self.feedback_text.set('实时反馈：设备未连接')
        self._refresh_controls()

    def destroy(self):
        if self._job is not None:
            try:self.after_cancel(self._job)
            except tk.TclError:pass
        super().destroy()