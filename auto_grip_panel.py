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
        self.last_at = None
        self.angle = None
        self.current = None
        self.status_bits = None
        self.detector = None
        self.started = None
        self._stop_sent = False
        self._job = None
        self.grip_min = tk.StringVar(value='')
        self.open_max = tk.StringVar(value='')
        self.speed = tk.StringVar(value='45')
        self.power = tk.StringVar(value='1500')
        self.hold_power = tk.StringVar(value='500')
        self.current_text = tk.StringVar(value='— A')
        self.angle_text = tk.StringVar(value='— °')
        self.status_text = tk.StringVar(value='待机；首先完成参数设置及实机标定')
        self._build()
        self._job = self.after(self.POLL_MS, self._tick)

    def _build(self):
        group = ttk.LabelFrame(self, text='自动抓取功能台架测试（单舵机）', padding=12)
        group.pack(fill='x')
        items = [
            ('抓取最小角度 °',self.grip_min),('张开最大角度 °',self.open_max),
            ('运动速度 °/s',self.speed),('运动功率上限 mW',self.power),
            ('停止保持功率 mW',self.hold_power),
        ]
        for i,(name,var) in enumerate(items):
            rr,cc=divmod(i,3)
            ttk.Label(group,text=name).grid(row=rr*2,column=cc,sticky='w',padx=8,pady=(5,1))
            ttk.Entry(group,textvariable=var,width=18).grid(row=rr*2+1,column=cc,sticky='w',padx=8,pady=(1,8))
        ttk.Label(group,text='当前电流').grid(row=4,column=0,sticky='w',padx=8)
        ttk.Label(group,textvariable=self.current_text,font=('Consolas',20,'bold')).grid(row=5,column=0,sticky='w',padx=8)
        ttk.Label(group,text='当前角度').grid(row=4,column=1,sticky='w',padx=8)
        ttk.Label(group,textvariable=self.angle_text,font=('Consolas',20,'bold')).grid(row=5,column=1,sticky='w',padx=8)
        actions=ttk.Frame(self)
        actions.pack(fill='x',pady=12)
        self.grip_btn=ttk.Button(actions,text='抓取',command=self.grip)
        self.grip_btn.pack(side='left',padx=8)
        self.open_btn=ttk.Button(actions,text='张开',command=self.open)
        self.open_btn.pack(side='left',padx=8)
        ttk.Button(actions,text='一键急停（软件）',command=self.emergency_stop).pack(side='left',padx=8)
        ttk.Button(actions,text='解除软件急停锁定',command=self.reset_estop).pack(side='left',padx=8)
        ttk.Label(self,textvariable=self.status_text,wraplength=1130,foreground='#a31717',
                  font=('Microsoft YaHei UI',12,'bold')).pack(fill='x',pady=8)
        ttk.Label(self,text='必须预先确认舵机旋转方向：此页只支持“抓取朝更小角度、张开朝更大角度”。\n'
                  '抓取遇到疑似接触/疑似稳定或最小角度即下发保持停止；仅是实验性判定，不能保证夹持力。\n'
                  '软件急停依赖 USB 通讯及舵机正常响应，不能替代独立断电硬件急停。',
                  foreground='#a31717',justify='left',wraplength=1130).pack(anchor='w')

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
            raise RuntimeError('请先在“数据监控”页开启周期监控（建议100ms）')
        sid=self.app.servo_id()
        if self.last_at is None or time.monotonic()-self.last_at>self.STALE_S or self.servo_id!=sid:
            raise RuntimeError('当前舵机角度/电流反馈已过期或ID不匹配，禁止盲动')
        if self.status_bits is None or self.status_bits & 0xFC:
            raise RuntimeError('存在堵转或设备保护故障，禁止运动')
        return sid

    def _move(self,target,vel,power,sid):
        frame=HA8Protocol.move(servo_id=sid,angle_deg=target,multiturn=True,mode='velocity',
                              velocity_dps=vel,t_acc_ms=200,t_dec_ms=200,power_mw=power)
        self.app.send_ha8(frame,'自动抓取测试：发送目标角度')

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
            self.phase='gripping';self.started=time.monotonic();self._stop_sent=False
            self._move(lo,vel,power,sid)
            self.status_text.set('抓取中：等待接触判定，或在最小角度前停止')
        except Exception as e:
            self.phase=None
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
            self.phase='opening';self.started=time.monotonic();self._stop_sent=False
            self._move(hi,vel,power,sid)
            self.status_text.set('张开中，等待角度反馈确认')
        except Exception as e:
            self.phase=None
            messagebox.showerror('张开失败',str(e))

    def _send_hold(self,reason):
        if self._stop_sent:
            return
        self._stop_sent=True
        try:
            power=int(float(self.hold_power.get()))
            if not 0<=power<=30000:power=0
            if self.app.transport.is_open:
                self.app.send_ha8(HA8Protocol.stop(self.app.servo_id(),STOP_HOLD,power),
                                  f'自动抓取测试：保持停止（{reason}）')
            else:
                raise RuntimeError('串口已断开')
            self.status_text.set(f'{reason}；已发送保持停止指令（未验证舵机执行）')
        except Exception as ex:
            self.status_text.set(f'{reason}；停止发送失败：{ex}，请使用硬件急停')
        finally:
            self.phase=None
            self.detector=None

    def emergency_stop(self):
        self.estop_latched=True
        self.phase=None
        self.detector=None
        self._stop_sent=False
        self._send_hold('软件急停已锁定')
        self.app.log('自动抓取测试：触发软件急停；必须人工确认后解锁。')

    def reset_estop(self):
        if not self.estop_latched:return
        if not messagebox.askyesno('解除软件急停', '确认舵机已停止、夹爪无碰撞风险、可重新进行台架试验？'):
            return
        self.estop_latched=False
        self._stop_sent=False
        self.status_text.set('软件急停锁定已解除，待机')

    def on_monitor(self,servo_id,fields):
        if servo_id != self.app.servo_id():
            return
        now=time.monotonic()
        self.servo_id=servo_id;self.last_at=now
        self.angle=float(fields['angle_deg'])
        self.current=float(fields['current_ma'])/1000
        self.status_bits=int(fields['status'])
        self.angle_text.set(f'{self.angle:.1f} °')
        self.current_text.set(f'{self.current:.3f} A')
        if not self.phase or self.estop_latched:return
        if self.status_bits & 0xFC:
            self.emergency_stop();return
        if self.phase=='gripping' and self.detector is not None:
            result=self.detector.observe(GripSample(now,self.angle,self.current,self.status_bits))
            if result.state in (GripState.CONTACT,GripState.CANDIDATE):
                self._send_hold(result.state.value)
                return
            if result.state in (GripState.FAULT,GripState.INVALID,GripState.STALE):
                self.emergency_stop();return
            lo=float(self.grip_min.get())
            if self.angle<=lo+0.8:
                self._send_hold('到达抓取最小角度（未确认抓到物体）')
        elif self.phase=='opening':
            hi=float(self.open_max.get())
            if self.angle>=hi-0.8:
                self._send_hold('已接近张开最大角度')

    def _tick(self):
        if self.phase and not self.estop_latched:
            if (self.last_at is None or time.monotonic()-self.last_at>self.STALE_S
                    or self.started is not None and time.monotonic()-self.started>20.0):
                self.emergency_stop()
        self._job=self.after(self.POLL_MS,self._tick)

    def disconnected(self):
        self.phase=None;self.detector=None
        self.last_at=None;self.servo_id=None
        self.current_text.set('— A');self.angle_text.set('— °')
        self.status_text.set('串口已断开，停止检测；软件无法保证电机停止')

    def destroy(self):
        if self._job is not None:
            try:self.after_cancel(self._job)
            except tk.TclError:pass
        super().destroy()