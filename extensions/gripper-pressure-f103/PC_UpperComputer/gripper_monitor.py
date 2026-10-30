"""F103 夹爪压力 Windows 上位机。只显示/记录数据，不控制电机。"""
from __future__ import annotations

import csv
import json
import math
import queue
import statistics
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from protocol import (PressureFrame, estimate_force_g, estimate_factory_force_g,
                      factory_reference_ready, MANUFACTURER_POINTS, parse_frame, validate_points,
                      feedback_resistor_valid, estimate_circuit_force_g)

BAUD = 115200
DEFAULT_RF_KOHM = 158.0  # 本项目采用的 AO-RES 阻值，单位 kΩ；需要与实际硬件一致
CAL_FILE = Path(__file__).with_name("calibration.json")
DATA_FLAGS = {1: "ADC采集失败", 2: "ADC高端接近饱和", 4: "ADC上电校准失败"}


class GripperMonitor:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("夹爪压力实时监测 | STM32F103")
        root.geometry("1220x850")
        root.minsize(950, 730)
        self.conn = None
        self.worker = None
        self.stop = threading.Event()
        self.messages = queue.Queue(maxsize=3000)
        self.history = deque(maxlen=6000)
        self.capture_buffer = deque(maxlen=100)
        self.cal_points = []
        self.zero_adc = None
        self.reference_adc = None
        self.reference_g = None
        self.active_mode = "circuit"  # 电路模型免砝码 / 一点参考 / 多点实测
        self.circuit_zero_adc = None
        self.last_frame = None
        self.last_received_monotonic = 0.0
        self.peak_g = 0.0
        self.expected_seq = None
        self.dropped = 0
        self.file_handle = None
        self.writer = None
        self.port_value = tk.StringVar()
        self.adc_text = tk.StringVar(value="--")
        self.mv_text = tk.StringVar(value="-- mV")
        self.force_text = tk.StringVar(value="待设置")
        self.newton_text = tk.StringVar(value="-- N")
        self.peak_text = tk.StringVar(value="-- g")
        self.rate_text = tk.StringVar(value="--")
        self.status_text = tk.StringVar(value="未连接")
        self.point_g = tk.StringVar(value="0")
        self.reference_input_g = tk.StringVar(value="500")
        self.rf_kohm_text = tk.StringVar(value=f"{DEFAULT_RF_KOHM:g}")
        self.factory_state_text = tk.StringVar(value="尚未采集零点 / 参考载荷")
        self.method_text = tk.StringVar(value="运放电路换算 · 估算 (Rf=158kΩ)")
        self.mark_time = time.monotonic()
        self.mark_count = 0
        self._closing = False
        self._drain_job = None
        self._chart_job = None
        self._build_ui()
        self._load_calibration()
        self.refresh_ports()
        self._drain_job = self.root.after(50, self._drain)
        self._chart_job = self.root.after(120, self._redraw_chart)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        self.root.configure(bg="#f4f6f9")
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=5)
        style.configure("TEntry", padding=4)
        container = ttk.Frame(self.root, padding=14)
        container.pack(fill="both", expand=True)
        top = ttk.Frame(container)
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="串口").pack(side="left")
        self.port_box = ttk.Combobox(top, textvariable=self.port_value, width=15, state="readonly")
        self.port_box.pack(side="left", padx=6)
        ttk.Button(top, text="刷新", command=self.refresh_ports).pack(side="left")
        self.btn_conn = ttk.Button(top, text="连接 115200", command=self.toggle_connection)
        self.btn_conn.pack(side="left", padx=8)
        ttk.Label(top, textvariable=self.status_text).pack(side="right")

        main = ttk.Frame(container)
        main.pack(fill="both", expand=True)
        # 左侧表单较长：为不同分辨率增加独立滚动区，避免保存/记录按钮被遮挡。
        left_outer = ttk.Frame(main, width=360)
        left_outer.pack(side="left", fill="y", padx=(0, 12))
        left_outer.pack_propagate(False)
        left_canvas = tk.Canvas(left_outer, width=338, bg="#f4f6f9", highlightthickness=0)
        left_bar = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_bar.set)
        left_bar.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill="both", expand=True)
        left = ttk.Frame(left_canvas)
        inner_window = left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", lambda e: left_canvas.configure(scrollregion=left_canvas.bbox("all")))
        left_canvas.bind("<Configure>", lambda e: left_canvas.itemconfigure(inner_window, width=e.width))
        # 鼠标停在左侧时，滚轮滚动左侧而不是整页。
        def scroll_form(event):
            left_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        def attach_scroll(_event):
            left_canvas.bind_all("<MouseWheel>", scroll_form)
        def detach_scroll(_event):
            left_canvas.unbind_all("<MouseWheel>")
        left_canvas.bind("<Enter>", attach_scroll)
        left_canvas.bind("<Leave>", detach_scroll)
        right = ttk.Frame(main)
        right.pack(side="right", fill="both", expand=True)

        metrics = ttk.LabelFrame(left, text="实时测量", padding=12)
        metrics.pack(fill="x")
        ttk.Label(metrics, text="夹爪受力（克力）").pack(anchor="w")
        ttk.Label(metrics, textvariable=self.method_text, foreground="#9a651b").pack(anchor="w")
        ttk.Label(metrics, textvariable=self.force_text, font=("Arial", 31, "bold"), foreground="#1863ac").pack(anchor="w", pady=5)
        ttk.Label(metrics, textvariable=self.newton_text).pack(anchor="w")
        ttk.Separator(metrics).pack(fill="x", pady=10)
        for name, var in (("ADC (0–4095)", self.adc_text),
                          ("输出电压", self.mv_text), ("峰值", self.peak_text),
                          ("接收速率", self.rate_text)):
            line = ttk.Frame(metrics)
            line.pack(fill="x", pady=3)
            ttk.Label(line, text=name).pack(side="left")
            ttk.Label(line, textvariable=var).pack(side="right")
        ttk.Button(metrics, text="清除峰值", command=self.clear_peak).pack(fill="x", pady=(10, 0))

        # 双模式标定页：默认使用厂家电导曲线，另提供实测多点标定。
        cal = ttk.LabelFrame(left, text="受力换算方式", padding=8)
        cal.pack(fill="x", pady=9)
        self.cal_notebook = ttk.Notebook(cal)
        self.cal_notebook.pack(fill="x")
        factory = ttk.Frame(self.cal_notebook, padding=8)
        measured = ttk.Frame(self.cal_notebook, padding=8)
        circuit = ttk.Frame(self.cal_notebook, padding=8)
        self.cal_notebook.add(circuit, text="免砝码 · 电路")
        self.cal_notebook.add(factory, text="单点参考")
        self.cal_notebook.add(measured, text="多点实测")
        ttk.Label(circuit, text="按转换模块手册 Uo=0.1×(1+Rf/Rx) 与传感器厂家曲线反算。\n不需要已知受力，但必须知道板上 AO-RES 实际阻值。",
                  foreground="#685a42", wraplength=305, justify="left").pack(anchor="w", pady=(0, 6))
        resistor_row = ttk.Frame(circuit)
        resistor_row.pack(fill="x", pady=4)
        ttk.Label(resistor_row, text="AO-RES 实际电阻 Rf (kΩ)").pack(side="left")
        ttk.Entry(resistor_row, textvariable=self.rf_kohm_text, width=8).pack(side="left", padx=(6, 0))
        self.rf_kohm_text.trace_add("write", self._on_rf_changed)
        ttk.Button(circuit, text="① 无负载采集零点（推荐）",
                   command=self.capture_circuit_zero).pack(fill="x", pady=4)
        self.circuit_state_text = tk.StringVar(value="默认 Rf=158kΩ；请核实实际硬件电阻")
        ttk.Label(circuit, textvariable=self.circuit_state_text, wraplength=305,
                  foreground="#1863ac", justify="left").pack(anchor="w", pady=4)
        ttk.Label(circuit, text="当前按 Rf=158kΩ 进行理论估算；300kΩ 是厂家建议值，并非本模块实际设置。",
                  foreground="#666", wraplength=305, justify="left").pack(anchor="w", pady=3)
        ttk.Label(circuit, text="断电后万用表测未焊 R2 两端阻值。若希望测到 2kg，理论上 Rf 需约≤160kΩ，且超出传感器标称 1kg。",
                  foreground="#985500", wraplength=305, justify="left").pack(anchor="w", pady=3)
        ttk.Label(circuit, text="⚠ 理论估算 ≠ 精确夹持力。电位器调节后必须更新 Rf。",
                  foreground="#985500", wraplength=305, justify="left").pack(anchor="w", pady=3)
        self.cal_notebook.bind("<<NotebookTabChanged>>", self._on_mode_changed)

        ttk.Label(factory, text="使用厂家第2页电导-受力数据。\n需无载零点 + 1个已知载荷确定转换板增益。",
                  foreground="#685a42", wraplength=305, justify="left").pack(anchor="w", pady=(0, 6))
        ttk.Button(factory, text="① 松开夹爪，采集无载零点", command=self.capture_factory_zero).pack(fill="x", pady=3)
        line = ttk.Frame(factory)
        line.pack(fill="x", pady=4)
        ttk.Label(line, text="参考受力 (g力)").pack(side="left")
        ttk.Entry(line, textvariable=self.reference_input_g, width=9).pack(side="left", padx=8)
        ttk.Button(factory, text="② 稳定施加已知受力，采集参考点", command=self.capture_factory_reference).pack(fill="x", pady=3)
        ttk.Label(factory, textvariable=self.factory_state_text, foreground="#1863ac",
                  wraplength=305, justify="left").pack(anchor="w", pady=5)
        ttk.Label(factory, text="厂家参考：50g→160kΩ，500g→18kΩ，\n1kg→9.8kΩ，2kg→5kΩ（超标称量程）。",
                  foreground="#666", justify="left").pack(anchor="w", pady=4)
        ttk.Label(factory, text="⚠ 按厂家曲线估算，不等于准确的夹持力。\n改变 AO_RES / 安装方式须重新采集。",
                  foreground="#985500", wraplength=305, justify="left").pack(anchor="w", pady=5)

        hint = "依次采集 0、50、100、200、500、1000g 等实测点。"
        ttk.Label(measured, text=hint, foreground="#666", wraplength=305).pack(anchor="w")
        input_row = ttk.Frame(measured)
        input_row.pack(fill="x", pady=7)
        ttk.Label(input_row, text="已知受力 (g力)").pack(side="left")
        ttk.Entry(input_row, textvariable=self.point_g, width=10).pack(side="left", padx=8)
        ttk.Button(measured, text="采集实测点（最近约1秒）", command=self.take_calibration).pack(fill="x")
        self.point_list = tk.Listbox(measured, height=5, font=("Consolas", 10))
        self.point_list.pack(fill="x", pady=8)
        ttk.Button(measured, text="清空全部实测点", command=self.clear_calibration).pack(fill="x")
        ttk.Label(measured, text="至少2点，要求 ADC 严格单调。",
                  foreground="#666").pack(anchor="w", pady=(5, 0))

        ttk.Button(cal, text="保存当前标定/模式", command=self.save_calibration).pack(fill="x", pady=(8, 0))
        log = ttk.LabelFrame(left, text="保存实测数据", padding=10)
        log.pack(fill="x")
        self.log_btn = ttk.Button(log, text="开始 CSV 记录", command=self.toggle_record)
        self.log_btn.pack(fill="x")
        ttk.Label(log, text="CSV 包含 ADC、受力估算及标定模式。", foreground="#666").pack(anchor="w", pady=(5, 0))

        chart = ttk.LabelFrame(right, text="60 秒实时曲线", padding=7)
        chart.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(chart, bg="#ffffff", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        info = ttk.LabelFrame(right, text="设备通信说明", padding=10)
        info.pack(fill="x", pady=(10, 0))
        ttk.Label(info, text="P,序号,单片机毫秒,ADC,毫伏,状态位 | 115200 / 8N1 | 约100帧/秒", foreground="#555").pack(anchor="w")
        ttk.Label(info, text="当前仅监测受力；不是电机控制/安全停机系统。", foreground="#8a5300").pack(anchor="w", pady=(3, 0))

    def refresh_ports(self):
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except ImportError:
            ports = []
            self.status_text.set("缺少 pyserial，请先 pip install pyserial")
        self.port_box["values"] = ports
        if ports and self.port_value.get() not in ports:
            self.port_value.set(ports[0])

    def toggle_connection(self):
        if self.conn is not None:
            self.disconnect()
            return
        port = self.port_value.get()
        if not port:
            messagebox.showwarning("串口", "请插入 USB 转 TTL，刷新并选择 COM 端口")
            return
        try:
            import serial
            self.conn = serial.Serial(port, BAUD, timeout=0.2)
        except Exception as exc:
            messagebox.showerror("连接失败", str(exc))
            return
        self.messages = queue.Queue(maxsize=3000)
        self.stop.clear()
        self.history.clear()
        self.capture_buffer.clear()
        self.last_frame = None
        self.expected_seq = None
        self.mark_time = time.monotonic()
        self.mark_count = 0
        self.dropped = 0
        self.worker = threading.Thread(target=self._read_thread, args=(self.conn,), daemon=True)
        self.worker.start()
        self.btn_conn.configure(text="断开连接")
        self.status_text.set(f"已连接 {port}")

    def _read_thread(self, conn):
        while not self.stop.is_set():
            try:
                line = conn.readline().decode("ascii", errors="ignore")
            except Exception as exc:
                if not self.stop.is_set():
                    try:
                        self.messages.put_nowait(("error", str(exc)))
                    except queue.Full:
                        pass
                break
            if not line:
                continue
            frame = parse_frame(line)
            if frame is not None:
                try:
                    self.messages.put_nowait(("frame", frame))
                except queue.Full:
                    pass

    def disconnect(self):
        self.stop.set()
        old = self.conn
        self.conn = None
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self.btn_conn.configure(text="连接 115200")
        self.status_text.set("未连接")
        self.rate_text.set("--")
        self.capture_buffer.clear()
        self.force_text.set("-- g")
        self.newton_text.set("-- N")

    def _drain(self):
        try:
            for _ in range(550):
                try:
                    kind, item = self.messages.get_nowait()
                except queue.Empty:
                    break
                if kind == "error":
                    self.disconnect()
                    self.status_text.set(f"串口错误：{item}")
                    break
                self._handle_frame(item)
            now = time.monotonic()
            if now - self.mark_time >= 1.0:
                self.rate_text.set(f"{self.mark_count/(now-self.mark_time):.0f} 帧/秒 | 丢 {self.dropped}")
                self.mark_count = 0
                self.mark_time = now
        finally:
            if not self._closing:
                self._drain_job = self.root.after(50, self._drain)

    def _handle_frame(self, frame: PressureFrame):
        self.mark_count += 1
        if self.expected_seq is not None:
            delta = (frame.sequence - self.expected_seq) & 0xFFFFFFFF
            if 0 < delta < 100000:
                self.dropped += delta
        self.expected_seq = (frame.sequence + 1) & 0xFFFFFFFF
        self.last_frame = frame
        self.last_received_monotonic = time.monotonic()
        self.adc_text.set(str(frame.adc))
        self.mv_text.set(f"{frame.voltage_mv} mV ({frame.voltage_mv/1000:.3f} V)")
        if frame.status & 1:
            self.status_text.set("ADC 采集错误，最近一帧无效")
            self.force_text.set("无效")
            self.newton_text.set("-- N")
            return
        self.capture_buffer.append(frame.adc)
        force = self._estimate(frame.adc)
        if frame.status & 4:
            self.status_text.set("ADC 上电校准失败，数值不可靠")
            force = None
        elif frame.status & 2:
            self.status_text.set("ADC 电压接近上限，请检查增益")
            force = None
        elif self._calibration_ready() and force is None:
            self.status_text.set("超出当前模式估算范围（不外推）")
        else:
            self.status_text.set(f"已连接 {self.port_value.get()}")
        if force is None:
            self.force_text.set("-- g" if self._calibration_ready() else "待设置")
            self.newton_text.set("-- N")
        else:
            prefix = "≈ " if self.active_mode in ("factory", "circuit") else ""
            self.force_text.set(f"{prefix}{force:.1f} g")
            self.newton_text.set(f"{force * 0.00980665:.3f} N")
            self.peak_g = max(self.peak_g, force)
            self.peak_text.set(f"{self.peak_g:.1f} g")
        self.history.append((frame.uptime_ms, frame.adc, frame.voltage_mv, frame.status))
        if self.writer is not None:
            self.writer.writerow([datetime.now().isoformat(timespec="milliseconds"),
                frame.sequence, frame.uptime_ms, frame.adc, frame.voltage_mv,
                "" if force is None else f"{force:.2f}",
                "" if force is None else f"{force * 0.00980665:.5f}", frame.status, self.active_mode])

    def _paint(self):
        canvas = self.canvas
        w, h = canvas.winfo_width(), canvas.winfo_height()
        canvas.delete("all")
        if w < 100 or h < 100:
            return
        x0, y0, x1, y1 = 65, 25, w - 20, h - 45
        canvas.create_rectangle(x0, y0, x1, y1, outline="#cad3dc")
        calibrated = self._calibration_ready()
        unit = ({"circuit":"g力（电路理论估算）", "factory":"g力（单点参考）",
                 "measured":"g力（多点实测）"}.get(self.active_mode, "g力")) if calibrated else "V (电压，待设置)"
        canvas.create_text(x0, 10, anchor="w", text=unit, fill="#555")
        series = []
        if self.history:
            t_end = self.history[-1][0]
            for ms, adc, mv, flag in self.history:
                if ((t_end - ms) & 0xFFFFFFFF) > 60000 or (flag & 7):
                    continue
                value = self._estimate(adc) if calibrated else mv/1000
                if value is not None:
                    series.append((ms, value))
        ys = [v for _, v in series]
        ymax = max(ys + [1.0]) if calibrated else 3.3
        ymax = max(1.0, math.ceil(ymax / 100.0) * 100.0) if calibrated else 3.3
        for i in range(5):
            y = y1 - (y1-y0)*i/4
            canvas.create_line(x0, y, x1, y, fill="#ebeff2")
            canvas.create_text(x0-8, y, anchor="e", text=f"{ymax*i/4:.0f}" if calibrated else f"{ymax*i/4:.2f}", fill="#667")
        for i in range(5):
            x = x0+(x1-x0)*i/4
            canvas.create_line(x, y0, x, y1, fill="#eef2f6")
            canvas.create_text(x, y1+17, text=f"-{60-15*i}s" if i != 4 else "现在", fill="#667")
        if len(series) > 1:
            t_end = series[-1][0]
            # 每次最多绘制约1000个点，避免 Tkinter 随时间变慢。
            step = max(1, len(series)//1000)
            sampled = series[::step]
            if sampled[-1] != series[-1]:
                sampled.append(series[-1])
            coords = []
            for ms, val in sampled:
                age = min(60000, (t_end-ms) & 0xFFFFFFFF)
                x = x1 - age/60000*(x1-x0)
                y = y1 - min(ymax, max(0.0, val))/ymax*(y1-y0)
                coords.extend((x, y))
            canvas.create_line(*coords, fill="#237dd0", width=2, smooth=False)
        else:
            canvas.create_text((x0+x1)/2, (y0+y1)/2, text="连接后显示实时数据", fill="#95a0ae")

    def _redraw_chart(self):
        try:
            self._paint()
        finally:
            if not self._closing:
                self._chart_job = self.root.after(120, self._redraw_chart)

    def _calibration_ready(self):
        if self.active_mode == "circuit":
            return feedback_resistor_valid(self.rf_kohm_text.get())
        if self.active_mode == "factory":
            return factory_reference_ready(self.zero_adc, self.reference_adc, self.reference_g)
        return validate_points(self.cal_points)

    def _estimate(self, adc):
        if self.active_mode == "circuit":
            return estimate_circuit_force_g(adc, self.rf_kohm_text.get(), self.circuit_zero_adc)
        if self.active_mode == "factory":
            return estimate_factory_force_g(adc, self.zero_adc, self.reference_adc, self.reference_g)
        return estimate_force_g(adc, self.cal_points)

    def _on_rf_changed(self, *_args):
        if not hasattr(self, "circuit_state_text"):
            return
        ready = feedback_resistor_valid(self.rf_kohm_text.get())
        zero = ("未采集，理论零位 0.100V" if self.circuit_zero_adc is None
                else f"已采集，ADC {self.circuit_zero_adc:.1f}")
        self.circuit_state_text.set(
            f"Rf：{self.rf_kohm_text.get() if ready else '请输入 0～300 范围内阻值'} kΩ\n"
            f"零位：{zero}\n"
            + ("已启用理论受力估算（请实测核对）" if ready else "无法反算受力"))
        self.clear_peak()

    def capture_circuit_zero(self):
        adc = self._average_current_adc()
        if adc is None:
            return
        self.circuit_zero_adc = adc
        self._on_rf_changed()
        self.status_text.set(f"已采无载零点 ADC {adc:.1f}，仍需 Rf 才能反算受力")

    def _on_mode_changed(self, _event=None):
        self.active_mode = ("circuit", "factory", "measured")[self.cal_notebook.index("current")]
        self.method_text.set({"circuit":"厂家电路模型 · 仅理论估算",
                              "factory":"厂家曲线 · 单点参考估算",
                              "measured":"多点实测插值"}[self.active_mode])
        self.peak_g = 0.0
        self.peak_text.set("-- g")
        self.force_text.set("待设置")
        self.newton_text.set("-- N")
        self._paint()

    def _average_current_adc(self):
        if (self.conn is None or self.last_frame is None or len(self.capture_buffer) < 20
                or time.monotonic() - self.last_received_monotonic > 0.5):
            messagebox.showwarning("没有稳定数据", "请连接串口，保持受力稳定至少1秒，再采集。")
            return None
        if self.last_frame.status != 0:
            messagebox.showwarning("传感器状态异常", "ADC出错或电压已接近满量程，不能用来标定。")
            return None
        adc = statistics.mean(self.capture_buffer)
        std = statistics.pstdev(self.capture_buffer)
        if std > 18:
            messagebox.showwarning("压力尚未稳定", f"最近一秒 ADC 标准差 {std:.1f}，请保持夹爪静止后再试。")
            return None
        return round(adc, 2)

    def _update_factory_state(self):
        zero = f"{self.zero_adc:.1f}" if self.zero_adc is not None else "未采集"
        reference = (f"{self.reference_g:g}g / ADC {self.reference_adc:.1f}"
                     if self.reference_adc is not None and self.reference_g is not None
                     else "未采集")
        ready = "可以估算受力" if factory_reference_ready(self.zero_adc, self.reference_adc, self.reference_g) else "尚不能换算受力"
        self.factory_state_text.set(f"零点 ADC：{zero}\n参考点：{reference}\n{ready}")

    def capture_factory_zero(self):
        adc = self._average_current_adc()
        if adc is None:
            return
        self.zero_adc = adc
        # 零点变更会改变斜率，旧参考点不再可用。
        self.reference_adc = None
        self.reference_g = None
        self._update_factory_state()
        self.clear_peak()
        self.status_text.set(f"零点已更新，ADC={adc:.1f}；请重新采集已知参考载荷")

    def capture_factory_reference(self):
        if self.zero_adc is None:
            messagebox.showwarning("未采零点", "先在无压力情况下点击①采集零点。")
            return
        try:
            g = float(self.reference_input_g.get())
        except ValueError:
            messagebox.showerror("无效受力", "请输入准确的已知受力，如 500（单位 g力）。")
            return
        if not (50 <= g <= 2000):
            messagebox.showerror("超出范围", "参考点必须在 50～2000g力之间。超过 1kg 请先确认安全。")
            return
        if g > 1000 and not messagebox.askyesno("超过标称量程", "资料首页标称量程为1kg。确定要使用超过1kg的参考载荷吗？"):
            return
        adc = self._average_current_adc()
        if adc is None:
            return
        if not factory_reference_ready(self.zero_adc, adc, g):
            messagebox.showerror("信号变化不足", "当前 ADC 与零点相差不足20，无法可靠换算。请检查施力或 AO_RES 增益。")
            return
        self.reference_adc = adc
        self.reference_g = g
        self._update_factory_state()
        self.clear_peak()
        self.status_text.set(f"厂家曲线已启用：零点 {self.zero_adc:.1f}，{g:g}g参考 {adc:.1f} ADC")

    def take_calibration(self):
        try:
            g = float(self.point_g.get())
        except ValueError:
            messagebox.showerror("输入错误", "请填写实际已知载荷 g")
            return
        if not (0 <= g <= 2000):
            messagebox.showerror("超出范围", "本工具只接收0～2000g的标定输入")
            return
        adc = self._average_current_adc()
        if adc is None:
            return
        candidate = [p for p in self.cal_points if p["g"] != g]
        candidate.append({"g": g, "adc": round(adc, 2)})
        candidate.sort(key=lambda p: p["g"])
        # 新点从第3个开始必须保持输入单调，否则不覆盖现有曲线。
        if len(candidate) >= 2 and not validate_points(candidate):
            messagebox.showerror("曲线异常", "ADC 与载荷不是单调对应，检查安装、增益及受力是否稳定")
            return
        self.cal_points = candidate
        self._display_points()
        self.status_text.set(f"实测标定：{g:g}g，ADC平均 {adc:.2f}")

    def _display_points(self):
        self.point_list.delete(0, tk.END)
        for p in sorted(self.cal_points, key=lambda x: x["g"]):
            self.point_list.insert(tk.END, f"{p['g']:>6g} g  →  ADC {p['adc']:.2f}")

    def _load_calibration(self):
        if not CAL_FILE.exists():
            self._update_factory_state()
            self._on_rf_changed()
            return
        try:
            data = json.loads(CAL_FILE.read_text(encoding="utf-8"))
            points = data.get("points", [])
            if points and not validate_points(points):
                raise ValueError("多点标定数据不合法")
            self.cal_points = points
            factory = data.get("factory", {})
            self.zero_adc = factory.get("zero_adc")
            self.reference_adc = factory.get("ref_adc")
            self.reference_g = factory.get("ref_g")
            if self.zero_adc is not None and not (0 <= float(self.zero_adc) <= 4095):
                raise ValueError("零点超出 ADC 范围")
            if self.reference_adc is not None and not factory_reference_ready(self.zero_adc, self.reference_adc, self.reference_g):
                raise ValueError("厂家参考点数据不合法")
            # 兼容 V1/V2 的旧 calibration.json，同时恢复电路模型 Rf 和零位。
            circuit = data.get("circuit", {})
            if not isinstance(circuit, dict):
                raise ValueError("电路模型配置不合法")
            rf = circuit.get("rf_kohm", None)
            if rf is not None:
                if not feedback_resistor_valid(rf):
                    raise ValueError("保存的 AO-RES 阻值不合法")
                self.rf_kohm_text.set(f"{float(rf):g}")
            self.circuit_zero_adc = circuit.get("zero_adc", None)
            if self.circuit_zero_adc is not None and not (0 <= float(self.circuit_zero_adc) <= 4095):
                raise ValueError("电路模型零位超出 ADC 范围")
            mode = data.get("mode", "measured" if validate_points(points) else "circuit")
            self.cal_notebook.select({"circuit":0,"factory":1,"measured":2}.get(mode, 0))
            self._on_mode_changed()
            self._on_rf_changed()
            if self.reference_g is not None:
                self.reference_input_g.set(f"{self.reference_g:g}")
            self._display_points()
            self._update_factory_state()
        except (ValueError, OSError, KeyError, TypeError) as exc:
            messagebox.showwarning("标定文件读取失败", str(exc))

    def save_calibration(self):
        if not self._calibration_ready():
            messagebox.showwarning("尚未设置", "免砝码模式需要实测 AO-RES 电阻值；单点参考模式需要零点+已知力；多点模式需要至少2点。")
            return
        payload = {
            "version": 3, "unit": "gram-force", "mode": self.active_mode,
            "notes": "仅适用于当前传感器/可调转换模块/增益/夹爪机械结构。厂家曲线属于推算。",
            "points": self.cal_points if validate_points(self.cal_points) else [],
            "factory": {"zero_adc": self.zero_adc, "ref_adc": self.reference_adc, "ref_g": self.reference_g},
            "circuit": {"rf_kohm": float(self.rf_kohm_text.get()) if feedback_resistor_valid(self.rf_kohm_text.get()) else None,
                        "zero_adc": self.circuit_zero_adc},
        }
        try:
            CAL_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        messagebox.showinfo("保存成功", f"配置已写入：\n{CAL_FILE}\n模式：{self.active_mode}")

    def clear_calibration(self):
        if not messagebox.askyesno("清空标定", "确认清空所有标定点吗？保存后将覆盖原标定文件。"):
            return
        self.cal_points = []
        self._display_points()
        self.peak_g = 0
        self.force_text.set("待设置")
        self.newton_text.set("-- N")
        self.peak_text.set("-- g")

    def clear_peak(self):
        self.peak_g = 0.0
        self.peak_text.set("0.0 g" if self._calibration_ready() else "-- g")

    def toggle_record(self):
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None
            self.writer = None
            self.log_btn.configure(text="开始 CSV 记录")
            return
        name = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV数据", "*.csv")],
            initialfile=f"gripper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        if not name:
            return
        try:
            self.file_handle = open(name, "w", encoding="utf-8-sig", newline="")
            self.writer = csv.writer(self.file_handle)
            self.writer.writerow(["pc_time", "sequence", "mcu_ms", "adc", "voltage_mv", "force_g", "force_N", "status", "calibration_mode"])
        except OSError as exc:
            messagebox.showerror("无法写入文件", str(exc))
            return
        self.log_btn.configure(text="停止 CSV 记录")

    def close(self):
        self._closing = True
        for job in (self._drain_job, self._chart_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        self.disconnect()
        if self.file_handle:
            self.file_handle.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    GripperMonitor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
