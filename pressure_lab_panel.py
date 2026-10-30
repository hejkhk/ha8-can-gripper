# -*- coding: utf-8 -*-
"""Experimental read-only pressure validation page for the HA8 gripper.

The F103 channel is independent of the HA8 USB UART. Pressure values NEVER
issue servo movement, hold, emergency-stop or permission-to-lift commands.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from serial.tools import list_ports

from pressure_validation import PressureSerialLink, PressureEvidence, CurveRecorder


class PressureLabPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.link = PressureSerialLink(self._thread_frame, self._thread_error)
        self.sensor = PressureEvidence(rf_kohm=158)
        self.recorder = CurveRecorder()
        self.pressure_port = tk.StringVar(value="")
        self.connection_text = tk.StringVar(value="未连接压力模块")
        self.adc_text = tk.StringVar(value="— ADC")
        self.pressure_text = tk.StringVar(value="—")
        self.zero_text = tk.StringVar(value="尚未采集无载零点")
        self.evidence_text = tk.StringVar(value="待机：传感器仅用于实验验证，不影响抓取控制")
        self.points_text = tk.StringVar(value="尚未开始采集")
        self.unit = tk.StringVar(value="adc")
        self.trial = tk.StringVar(value="试验1")
        self._job = None
        self._build()
        self.refresh_ports()
        self._job = self.after(350, self._tick)

    def _build(self):
        area = ttk.Frame(self, padding=8)
        area.pack(fill="both", expand=True)
        top = ttk.LabelFrame(area, text="① 连接压力传感器（STM32F103 独立 USB-TTL）", padding=10)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="压力串口").pack(side="left")
        self.combo = ttk.Combobox(top, textvariable=self.pressure_port, state="readonly", width=14)
        self.combo.pack(side="left", padx=6)
        ttk.Button(top, text="刷新", command=self.refresh_ports).pack(side="left")
        self.conn_btn = ttk.Button(top, text="连接压力模块", command=self.toggle_connection)
        self.conn_btn.pack(side="left", padx=12)
        ttk.Label(top, textvariable=self.connection_text).pack(side="left")

        readouts = ttk.LabelFrame(area, text="② 先采无载零点，再查看接触证据", padding=10)
        readouts.pack(fill="x", pady=(0, 8))
        first = ttk.Frame(readouts)
        first.pack(fill="x")
        ttk.Label(first, text="原始读数：").pack(side="left")
        ttk.Label(first, textvariable=self.adc_text, font=("Consolas", 13, "bold")).pack(side="left")
        ttk.Label(first, text="  理论受力（158kΩ 假定）：").pack(side="left", padx=(14, 0))
        ttk.Label(first, textvariable=self.pressure_text, font=("Consolas", 13, "bold")).pack(side="left")
        row = ttk.Frame(readouts)
        row.pack(fill="x", pady=6)
        ttk.Button(row, text="无负载采集零点", command=self.capture_zero).pack(side="left")
        ttk.Button(row, text="检查当前压力接触", command=self.check_contact).pack(side="left", padx=8)
        ttk.Label(row, textvariable=self.zero_text).pack(side="left", padx=10)
        ttk.Label(readouts, textvariable=self.evidence_text,
                  foreground="#a15311", wraplength=900).pack(anchor="w")

        experiment = ttk.LabelFrame(area, text="③ 采集舵机电流与压力的对应曲线", padding=10)
        experiment.pack(fill="both", expand=True)
        controls = ttk.Frame(experiment)
        controls.pack(fill="x")
        ttk.Label(controls, text="实验名称").pack(side="left")
        ttk.Entry(controls, textvariable=self.trial, width=16).pack(side="left", padx=(5, 12))
        self.start_btn = ttk.Button(controls, text="开始采集", command=self.start_record)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(controls, text="结束采集", command=self.stop_record)
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(controls, text="导出 CSV", command=self.export_csv).pack(side="left", padx=5)
        ttk.Label(controls, textvariable=self.points_text).pack(side="left", padx=8)

        selectors = ttk.Frame(experiment)
        selectors.pack(fill="x", pady=(9, 3))
        ttk.Label(selectors, text="横轴：HA8 电流(A)  |  纵轴：").pack(side="left")
        ttk.Radiobutton(selectors, text="压力相对零点(ADC)", value="adc", variable=self.unit,
                        command=self._draw).pack(side="left")
        ttk.Radiobutton(selectors, text="理论估算(gf)", value="gf", variable=self.unit,
                        command=self._draw).pack(side="left", padx=10)
        self.chart = tk.Canvas(experiment, background="#ffffff", height=245,
                               highlightthickness=1, highlightbackground="#dddddd")
        self.chart.pack(fill="both", expand=True, pady=(3, 5))
        self.chart.bind("<Configure>", lambda event: self._draw())
        ttk.Label(experiment, text="散点＝同步采样；线＝分区中位数趋势（样本不足不画线）。"
                  " 传感器估算力不是末端真实夹紧力，不证明防滑或可安全搬运。",
                  foreground="#a15311", wraplength=900).pack(anchor="w")

    def refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        self.combo.configure(values=ports)
        selected = self.pressure_port.get()
        if selected not in ports:
            ha8_port = self.app.port_var.get().strip()
            choices = [p for p in ports if p.lower() != ha8_port.lower()]
            self.pressure_port.set(choices[0] if choices else "")

    def toggle_connection(self):
        if self.link.is_open:
            self.disconnect()
            return
        port = self.pressure_port.get().strip()
        ha8_port = self.app.port_var.get().strip()
        if not port:
            messagebox.showwarning("请选择串口", "压力传感器需要第二个 USB-TTL COM 口")
            return
        if port.lower() == ha8_port.lower():
            messagebox.showerror("串口冲突", "压力模块和 HA8 舵机不能使用同一个串口")
            return
        try:
            self.link.open(port)
            self.sensor = PressureEvidence(rf_kohm=158)
            self.recorder.stop()
            self.connection_text.set(f"已连接 {port}，正在接收")
            self.conn_btn.configure(text="断开压力模块")
            self.evidence_text.set("请确认压力片无载，再采集零点")
        except Exception as exc:
            self.connection_text.set(f"连接失败：{exc}")
            messagebox.showerror("压力模块连接失败", str(exc))

    def disconnect(self):
        self.recorder.stop()
        self.link.close()
        self.connection_text.set("未连接压力模块")
        self.conn_btn.configure(text="连接压力模块")
        self.adc_text.set("— ADC")
        self.pressure_text.set("—")
        self.evidence_text.set("压力模块已断开；夹爪运动控制不受影响")

    def _thread_frame(self, frame, at):
        self.app.ui_queue.put(("pressure_frame", (frame, at)))

    def _thread_error(self, exc):
        self.app.ui_queue.put(("pressure_error", str(exc)))

    def on_pressure_frame(self, frame, at):
        if not self.link.is_open:
            return
        self.sensor.add(frame, at)
        # Bad status flags are never accepted as force or contact evidence.
        if frame.status:
            self.connection_text.set(f"压力采集异常 flags=0x{frame.status:02X}")
            return
        if frame.adc >= 4085:
            self.connection_text.set("压力 ADC 接近饱和，数据不可靠")
            return
        if at-self.sensor.samples[-1].at > 0.3:
            return
        if frame.sequence % 10 == 0:
            self.adc_text.set(f"{frame.adc} ADC / {frame.voltage_mv} mV")
            gf = self.sensor.theoretical_force_g(frame.adc)
            self.pressure_text.set("—（未校零/超范围）" if gf is None else f"≈{gf:.0f} gf（未实测标定）")
            self.connection_text.set("压力数据接收正常")

    def on_pressure_error(self, reason):
        self.disconnect()
        self.connection_text.set("串口错误：请检查 USB-TTL")
        self.evidence_text.set(f"压力采集已停止：{reason}")

    def capture_zero(self):
        try:
            zero = self.sensor.capture_zero()
            self.zero_text.set(f"零点 ADC {zero:.1f}（Rf=158kΩ，未经实测）")
            self.evidence_text.set("零点采集成功；后续接触证据仅用于验证实验")
        except ValueError as exc:
            messagebox.showwarning("无法采零点", str(exc))

    def check_contact(self):
        label, delta = self.sensor.evidence()
        suffix = "" if delta is None else f"，相对零点 {delta:+.0f} ADC"
        self.evidence_text.set(label+suffix)

    def on_ha8_monitor(self, servo_id, fields):
        phase = self.app.auto_grip_panel.phase or "idle"
        if self.recorder.add(time.monotonic(), servo_id, fields, self.sensor, phase):
            if len(self.recorder.rows) % 10 == 0:
                self.points_text.set(f"已配对 {len(self.recorder.rows)} 点")

    def on_grip_start(self):
        self.evidence_text.set("抓取动作已开始；压力仅记录，不参与控制")

    def on_grip_end(self, reason, confirmed_motion_stop=True):
        if not confirmed_motion_stop:
            self.evidence_text.set("舵机停止未确认；压力不能证明安全抓稳")
            return
        label, delta = self.sensor.evidence()
        tail = "" if delta is None else f"（ΔADC={delta:+.0f}）"
        self.evidence_text.set(f"HA8：{reason}；FSR：{label}{tail}")

    def start_record(self):
        if not self.link.is_open or self.sensor.zero_adc is None:
            messagebox.showwarning("无法采集", "请先连接压力模块并采集无载零点")
            return
        if not self.app.transport.is_open or not self.app.monitor_running:
            messagebox.showwarning("无法采集", "请先连接 HA8 舵机，让主界面获取实时电流")
            return
        if self.recorder.rows and not messagebox.askyesno(
                "覆盖当前实验", "开始新实验会清空尚未导出的曲线数据，确定继续？"):
            return
        self.recorder.start(self.trial.get())
        self.points_text.set("采集中：请通过夹爪控制页做低速试验")
        self.evidence_text.set("采集启动；现有 HA8 控制逻辑完全不变")

    def stop_record(self):
        self.recorder.stop()
        self.points_text.set(f"已停止：配对 {len(self.recorder.rows)} 个样本")
        self._draw()

    def export_csv(self):
        if not self.recorder.rows:
            messagebox.showinfo("无数据", "先开始采集，再进行一次夹爪试验")
            return
        path = filedialog.asksaveasfilename(title="导出 HA8 电流-压力实验数据",
                                            defaultextension=".csv",
                                            filetypes=[("CSV","*.csv")])
        if path:
            try:
                self.recorder.export_csv(path)
                self.points_text.set(f"已保存 {len(self.recorder.rows)} 点")
            except OSError as exc:
                messagebox.showerror("保存失败", str(exc))

    def _draw(self):
        canvas = self.chart
        canvas.delete("all")
        w,h = max(360,canvas.winfo_width()),max(190,canvas.winfo_height())
        l,t,r,b = 70,20,w-24,h-39
        canvas.create_line(l,b,r,b,fill="#555555",width=1)
        canvas.create_line(l,b,l,t,fill="#555555",width=1)
        canvas.create_text((l+r)/2,h-16,text="HA8 舵机电流 (A)",fill="#444444")
        unit = self.unit.get()
        canvas.create_text(9,10,text="ΔADC" if unit=="adc" else "理论 gf",
                           anchor="nw",fill="#444444")
        points, curve = self.recorder.curve(unit)
        if not points:
            canvas.create_text((l+r)/2,(t+b)/2,text="等待采集有效的电流与压力配对数据",
                               fill="#888888")
            return
        xs=[p[0] for p in points];ys=[p[1] for p in points]
        x0,x1=min(xs),max(xs);y0,y1=min(ys),max(ys)
        if x1-x0<0.02:x0-=0.01;x1+=0.01
        if y1-y0<1:y0-=0.5;y1+=0.5
        xp=lambda x:l+(x-x0)/(x1-x0)*(r-l)
        yp=lambda y:b-(y-y0)/(y1-y0)*(b-t)
        canvas.create_text(l,b+12,text=f"{x0:.2f}",anchor="w",fill="#555555")
        canvas.create_text(r,b+12,text=f"{x1:.2f}",anchor="e",fill="#555555")
        canvas.create_text(l-5,b,text=f"{y0:.0f}",anchor="e",fill="#555555")
        canvas.create_text(l-5,t,text=f"{y1:.0f}",anchor="e",fill="#555555")
        for x,y in points[-1200:]:
            px,py=xp(x),yp(y)
            canvas.create_oval(px-2,py-2,px+2,py+2,fill="#86abc6",outline="")
        if len(curve)>=2:
            coordinates=[]
            for x,y in curve:
                coordinates.extend((xp(x),yp(y)))
            canvas.create_line(*coordinates,fill="#bb4f27",width=2)
            for x,y in curve:
                px,py=xp(x),yp(y)
                canvas.create_oval(px-3,py-3,px+3,py+3,fill="#bb4f27",outline="")

    def _tick(self):
        if not self.link.is_open or self.sensor.latest() is None:
            self.adc_text.set("— ADC")
            self.pressure_text.set("—")
            if self.link.is_open:
                self.connection_text.set("压力数据超时/异常（不能用于验证）")
        self._draw()
        self._job = self.after(350, self._tick)

    def shutdown(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
        self.link.close()

    def destroy(self):
        self.shutdown()
        super().destroy()
