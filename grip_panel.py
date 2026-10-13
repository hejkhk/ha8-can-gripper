# -*- coding: utf-8 -*-
"""Tkinter experimental grip diagnostics panel for the HA8 upper computer."""
from __future__ import annotations

from collections import deque
from statistics import median
import time
import tkinter as tk
from tkinter import messagebox, ttk

from grip_estimator import (
    GripDetector, GripSettings, GripSample, GripState,
    REFERENCE_DYNAMIC_POINTS, parse_curve, format_curve,
)


class GripPanel(ttk.Frame):
    """Read-only grip observer; the panel never commands servo motion/stop."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.detector = GripDetector()
        self.watch_id: int | None = None
        self.recent_current: dict[int, deque[float]] = {}
        self.last_logged_state = GripState.IDLE
        self._watchdog_job = None
        self._build()
        self._render(self.detector.last_result)
        self._watchdog_job = self.after(250, self._watchdog)

    def _build(self):
        upper = ttk.LabelFrame(self, text='实时参考：不参与运动控制、不自动抬升', padding=10)
        upper.pack(fill='x')
        self.status_var = tk.StringVar(value='未开始')
        self.note_var = tk.StringVar(value='先连接舵机并开启自动监控')
        self.current_var = tk.StringVar(value='—')
        self.speed_var = tk.StringVar(value='—')
        self.torque_var = tk.StringVar(value='不适用')
        self.travel_var = tk.StringVar(value='—')
        ttk.Label(upper,text='状态').grid(row=0,column=0,sticky='w',padx=6,pady=5)
        ttk.Label(upper,textvariable=self.status_var,font=('Microsoft YaHei UI',13,'bold')).grid(
            row=0,column=1,columnspan=6,sticky='w',padx=6)
        for n,(name,var) in enumerate([
            ('滤波电流',self.current_var),('角速度',self.speed_var),
            ('动态参考扭矩',self.torque_var),('闭合行程',self.travel_var),
        ]):
            ttk.Label(upper,text=name).grid(row=1,column=2*n,sticky='w',padx=6,pady=8)
            ttk.Label(upper,textvariable=var,font=('Consolas',11)).grid(row=1,column=2*n+1,sticky='w',padx=6)
        ttk.Label(upper,textvariable=self.note_var,foreground='#9c3c10',wraplength=1150).grid(
            row=2,column=0,columnspan=8,sticky='w',pady=6)

        settings = ttk.LabelFrame(self,text='阈值（示例初始值，需根据机构和实际电流调整）',padding=10)
        settings.pack(fill='x',pady=(8,0))
        params=[
            ('空载电流基线(A)','baseline','0.20'),
            ('接触电流增量(A)','delta','0.18'),
            ('候选夹持电流(A)','minimum','0.55'),
            ('异常电流报警(A)','maximum','1.50'),
            ('低速阈值(°/s)','low_speed','2.0'),
            ('稳定时间(s)','duration','0.50'),
            ('至少闭合角度(°)','travel','2.0'),
            ('有效夹持角度下限','angle_lo',''),
            ('有效夹持角度上限','angle_hi',''),
        ]
        self.values: dict[str,tk.StringVar]={}
        for n,(caption,key,default) in enumerate(params):
            row,col=divmod(n,3)
            ttk.Label(settings,text=caption).grid(row=row,column=2*col,sticky='w',padx=4,pady=6)
            self.values[key]=tk.StringVar(value=default)
            ttk.Entry(settings,textvariable=self.values[key],width=13).grid(
                row=row,column=2*col+1,sticky='w',padx=(4,18))
        ttk.Label(settings,text='闭合方向').grid(row=3,column=0,sticky='w',padx=4,pady=6)
        self.direction=tk.StringVar(value='角度递增')
        ttk.Combobox(settings,textvariable=self.direction,state='readonly',width=12,
                     values=['角度递增','角度递减']).grid(row=3,column=1,sticky='w',padx=4)
        ttk.Label(settings,text='不确定闭合方向时先观察多圈角度变化。角度上下限同时留空，则不会给出稳定夹持候选。',
                  foreground='#a31717',wraplength=1100).grid(
                      row=4,column=0,columnspan=6,sticky='w',pady=6)

        curve=ttk.LabelFrame(self,text='电流→舵机输出轴动态参考扭矩（厂商图粗略读值，可编辑）',padding=10)
        curve.pack(fill='x',pady=(8,0))
        self.curve_value=tk.StringVar(value=format_curve(REFERENCE_DYNAMIC_POINTS))
        ttk.Label(curve,text='格式：电流A:扭矩Nm, 电流A:扭矩Nm …').pack(anchor='w')
        ttk.Entry(curve,textvariable=self.curve_value,width=110).pack(fill='x',pady=5)
        ttk.Label(curve,text='静止保持和曲线电流范围外一律显示“不适用”；不代表蜗杆后的夹持力，不能推导物体可抬升重量。',
                  foreground='#a31717',wraplength=1140).pack(anchor='w')

        buttons=ttk.Frame(self)
        buttons.pack(fill='x',pady=11)
        ttk.Button(buttons,text='应用参数',command=self.apply).pack(side='left',padx=4)
        ttk.Button(buttons,text='采集空载电流基线',command=self.capture_baseline).pack(side='left',padx=4)
        ttk.Button(buttons,text='开始一次夹持检测',command=self.start).pack(side='left',padx=4)
        ttk.Button(buttons,text='停止判定（不停止电机）',command=self.stop).pack(side='left',padx=4)
        ttk.Label(self,text='⚠ “疑似夹持稳定”不代表可靠抓稳。堵转/过流/报警时请人工采取安全措施。软件不发送运动、释放或急停指令。',
                  foreground='#a31717',wraplength=1130).pack(anchor='w',pady=5)

    def apply(self) -> bool:
        try:
            lo=self.values['angle_lo'].get().strip()
            hi=self.values['angle_hi'].get().strip()
            settings=GripSettings(
                baseline_a=float(self.values['baseline'].get()),
                contact_delta_a=float(self.values['delta'].get()),
                minimum_grip_current_a=float(self.values['minimum'].get()),
                maximum_safe_current_a=float(self.values['maximum'].get()),
                low_speed_dps=float(self.values['low_speed'].get()),
                stable_seconds=float(self.values['duration'].get()),
                minimum_travel_deg=float(self.values['travel'].get()),
                closing_direction=1 if self.direction.get()=='角度递增' else -1,
                valid_angle_min=None if not lo else float(lo),
                valid_angle_max=None if not hi else float(hi),
            )
            settings.validate()
            points=parse_curve(self.curve_value.get())
        except (ValueError, TypeError) as exc:
            messagebox.showerror('夹持参数错误',str(exc))
            return False
        self.watch_id=None
        self.detector=GripDetector(settings,points)
        self.last_logged_state=GripState.IDLE
        self._render(self.detector.last_result)
        self.app.log('夹持阈值/动态参考曲线已应用；如在检测中修改需重新开始')
        return True

    def capture_baseline(self):
        try:
            sid=self.app.servo_id()
            if self.detector.armed:
                raise ValueError('请先停止本次夹持检测')
            samples=self.recent_current.get(sid)
            if samples is None or len(samples)<5:
                raise ValueError('请先对当前 ID 采集至少5个监控电流值')
            if not messagebox.askyesno('空载确认','是否确认最近5次采样时未夹物体、未顶机械限位？'):
                return
            self.values['baseline'].set(f'{median(list(samples)[-5:]):.3f}')
            self.apply()
        except Exception as exc:
            messagebox.showwarning('采集失败',str(exc))

    def start(self):
        if not self.app.transport.is_open:
            messagebox.showwarning('未连接','先连接官方 USB 转接板')
            return
        if not self.app.monitor_running:
            messagebox.showwarning('未开启监控','先在数据监控页点击“开始自动监控”，建议周期100ms')
            return
        if not self.apply():
            return
        self.watch_id=self.app.servo_id()
        self.detector.arm()
        self.last_logged_state=GripState.CLOSING
        self._render(self.detector.last_result)
        self.app.log(f'夹持实验检测开始：舵机ID={self.watch_id}，请用原有位置控制发出闭合运动')

    def stop(self):
        self.watch_id=None
        self.detector.reset()
        self.last_logged_state=GripState.IDLE
        self._render(self.detector.last_result)

    def disconnected(self):
        self.stop()
        self.recent_current.clear()

    def _render(self,result):
        self.status_var.set(result.state.value)
        self.note_var.set(result.note)
        self.current_var.set('—' if result.current_filtered_a is None else f'{result.current_filtered_a:.3f} A')
        self.speed_var.set('—' if result.angle_speed_dps is None else f'{result.angle_speed_dps:+.2f} °/s')
        self.torque_var.set('不适用' if result.dynamic_torque_nm is None else f'约 {result.dynamic_torque_nm:.3f} N·m')
        self.travel_var.set(f'{result.travel_deg:.1f}°')
        self.app.monitor_vars['torque_ref'].set(self.torque_var.get())
        self.app.monitor_vars['grip_state'].set(result.state.value)
        if self.detector.armed and result.state!=self.last_logged_state:
            self.app.log(f'夹持状态改变：{result.state.value}，{result.note}')
        self.last_logged_state=result.state

    def on_monitor(self,servo_id:int,fields:dict):
        current=float(fields['current_ma'])/1000.0
        history=self.recent_current.setdefault(servo_id,deque(maxlen=30))
        history.append(current)
        try:
            selected_id = self.watch_id if self.detector.armed else self.app.servo_id()
        except (ValueError, tk.TclError):
            return None
        if servo_id != selected_id:
            return None
        sample=GripSample(time.monotonic(),float(fields['angle_deg']),current,int(fields['status']))
        result=self.detector.observe(sample)
        self._render(result)
        return result

    def _watchdog(self):
        if self.detector.armed:
            r=self.detector.check_stale(time.monotonic())
            if r.state==GripState.STALE and r.state!=self.last_logged_state:
                self._render(r)
        self._watchdog_job=self.after(250,self._watchdog)