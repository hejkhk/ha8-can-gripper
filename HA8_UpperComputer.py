# -*- coding: utf-8 -*-
"""
HA8-U35H-M Independent Upper Computer V1
========================================

Architecture:
    HA8_UpperComputer.py  -> GUI / application
    usb_can_cdc.py        -> direct USB-CAN CDC transport
    ha8_protocol.py       -> ALL HA8 control & response protocol

Hardware path:
    PC -> USB-CAN -> CAN 1 Mbps -> CTS100M -> UART 115200
       -> servo expansion board -> HA8-U35H-M

CAN IDs:
    0x6A0 command
    0x6A1 feedback
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from serial.tools import list_ports

from ha8_protocol import (
    HA8Protocol,
    ResponseStreamParser,
    decode_response,
    hex_bytes,
    parse_hex_string,
    STOP_RELEASE,
    STOP_HOLD,
    STOP_DAMPING,
)
from usb_can_cdc import (
    UsbCanCdc,
    CanFrame,
    DEFAULT_TX_ID,
    DEFAULT_RX_ID,
    CAN_BITRATE_TEXT,
    CDC_BAUD,
)

APP_TITLE = "HA8-U35H-M 独立上位机"
APP_VERSION = "1.1"


class HA8UpperComputer(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(f"{APP_TITLE} V{APP_VERSION}")
        self.geometry("1220x820")
        self.minsize(1080, 720)

        self.protocol_parser = ResponseStreamParser()
        self.transport = UsbCanCdc(
            on_frame=self._on_can_frame_thread,
            on_error=self._on_transport_error_thread,
        )

        self.ui_queue: queue.Queue = queue.Queue()
        self.monitor_running = False
        self.monitor_job = None

        self.tx_can_count = 0
        self.rx_can_count = 0
        self.tx_ha8_count = 0
        self.rx_ha8_count = 0

        self._setup_style()
        self._build_ui()
        self.refresh_ports()
        self.after(20, self._pump_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- style ----------
    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("BigValue.TLabel", font=("Consolas", 20, "bold"))
        style.configure("OK.TLabel", foreground="#187a2f", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("BAD.TLabel", foreground="#a31717", font=("Microsoft YaHei UI", 10, "bold"))

    # ---------- UI ----------
    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="USB-CAN → CAN 1Mbps → CTS100M → HA8   |   CMD 0x6A0 / FB 0x6A1",
        ).pack(side="right")

        self._build_connection(root)

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, pady=(8, 8))

        self.tab_control = ttk.Frame(self.nb, padding=10)
        self.tab_monitor = ttk.Frame(self.nb, padding=10)
        self.tab_maint = ttk.Frame(self.nb, padding=10)
        self.tab_debug = ttk.Frame(self.nb, padding=10)

        self.nb.add(self.tab_control, text="位置控制")
        self.nb.add(self.tab_monitor, text="状态监控")
        self.nb.add(self.tab_maint, text="停止 / 标定")
        self.nb.add(self.tab_debug, text="CAN 调试")

        self._build_control_tab()
        self._build_monitor_tab()
        self._build_maint_tab()
        self._build_debug_tab()
        self._build_log(root)

    def _build_connection(self, parent):
        box = ttk.LabelFrame(parent, text="USB-CAN 连接", padding=8)
        box.pack(fill="x", pady=(8, 0))

        ttk.Label(box, text="端口").grid(row=0, column=0, padx=4, pady=4)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(box, textvariable=self.port_var, width=22, state="normal")
        self.port_combo.grid(row=0, column=1, padx=4)

        ttk.Button(box, text="刷新", command=self.refresh_ports).grid(row=0, column=2, padx=4)

        self.connect_btn = ttk.Button(box, text="连接 USB-CAN", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=3, padx=(14, 4))

        self.conn_var = tk.StringVar(value="未连接")
        self.conn_label = ttk.Label(box, textvariable=self.conn_var, style="BAD.TLabel")
        self.conn_label.grid(row=0, column=4, padx=8)

        ttk.Separator(box, orient="vertical").grid(row=0, column=5, sticky="ns", padx=12)

        ttk.Label(box, text="舵机 ID").grid(row=0, column=6, padx=4)
        self.servo_id_var = tk.IntVar(value=0)
        ttk.Spinbox(box, from_=0, to=254, textvariable=self.servo_id_var, width=7).grid(
            row=0, column=7, padx=4
        )

        ttk.Button(box, text="Ping", command=self.ping_servo).grid(row=0, column=8, padx=4)

        self.online_var = tk.StringVar(value="舵机：未知")
        self.online_label = ttk.Label(box, textvariable=self.online_var)
        self.online_label.grid(row=0, column=9, padx=8)

        ttk.Label(
            box,
            text=f"CDC {CDC_BAUD} 8N1 | CAN {CAN_BITRATE_TEXT}",
        ).grid(row=0, column=10, padx=(20, 4))

    def _build_control_tab(self):
        left = ttk.LabelFrame(self.tab_control, text="目标运动", padding=12)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self.multiturn_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            left,
            text="多圈模式（蜗杆夹爪建议）",
            variable=self.multiturn_var,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        labels = [
            ("目标角度 (°)", "angle_var", "0"),
            ("运动时间 (ms)", "interval_var", "2000"),
            ("目标速度 (°/s)", "velocity_var", "120"),
            ("加速时间 (ms)", "tacc_var", "200"),
            ("减速时间 (ms)", "tdec_var", "200"),
            ("运行功率 (mW)", "power_var", "5000"),
        ]

        for row, (label, attr, default) in enumerate(labels, start=1):
            ttk.Label(left, text=label).grid(row=row, column=0, sticky="w", pady=5)
            var = tk.StringVar(value=default)
            setattr(self, attr, var)
            ttk.Entry(left, textvariable=var, width=18).grid(row=row, column=1, sticky="w")

        ttk.Label(left, text="控制方式").grid(row=7, column=0, sticky="w", pady=5)
        self.mode_var = tk.StringVar(value="velocity")
        ttk.Combobox(
            left,
            textvariable=self.mode_var,
            state="readonly",
            width=22,
            values=["simple", "interval", "velocity"],
        ).grid(row=7, column=1, sticky="w")
        ttk.Label(left, text="simple=时间 / interval=梯形时间 / velocity=梯形速度").grid(
            row=7, column=2, sticky="w", padx=8
        )

        btns = ttk.Frame(left)
        btns.grid(row=8, column=0, columnspan=3, sticky="w", pady=(16, 0))
        ttk.Button(btns, text="发送运动指令", command=self.send_move).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="读取当前角度", command=self.query_angle).pack(side="left")

        right = ttk.LabelFrame(self.tab_control, text="当前位置", padding=16)
        right.pack(side="right", fill="y", padx=(8, 0))

        self.current_angle_var = tk.StringVar(value="—")
        ttk.Label(right, text="角度").pack(anchor="w")
        ttk.Label(right, textvariable=self.current_angle_var, style="BigValue.TLabel").pack(
            anchor="w", pady=(4, 14)
        )

        self.current_turn_var = tk.StringVar(value="—")
        ttk.Label(right, text="圈数").pack(anchor="w")
        ttk.Label(right, textvariable=self.current_turn_var, style="BigValue.TLabel").pack(
            anchor="w", pady=(4, 14)
        )

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=8)
        ttk.Label(
            right,
            text="首次运动请确保机构无干涉，\n建议先低功率、小角度测试。",
            justify="left",
        ).pack(anchor="w", pady=8)

    def _build_monitor_tab(self):
        top = ttk.Frame(self.tab_monitor)
        top.pack(fill="x")

        ttk.Button(top, text="读取一次", command=self.query_monitor).pack(side="left")
        self.monitor_btn = ttk.Button(top, text="开始自动监控", command=self.toggle_monitor)
        self.monitor_btn.pack(side="left", padx=8)

        ttk.Label(top, text="周期(ms)").pack(side="left", padx=(18, 4))
        self.monitor_period_var = tk.StringVar(value="300")
        ttk.Entry(top, textvariable=self.monitor_period_var, width=8).pack(side="left")

        grid = ttk.LabelFrame(self.tab_monitor, text="HA8 状态", padding=12)
        grid.pack(fill="both", expand=True, pady=(10, 0))

        self.monitor_vars = {}
        rows = [
            ("电压", "voltage"),
            ("电流", "current"),
            ("功率", "power"),
            ("温度", "temperature"),
            ("温度ADC", "temp_raw"),
            ("角度", "angle"),
            ("圈数", "turn"),
            ("状态字", "status"),
            ("状态解释", "status_text"),
        ]

        for i, (label, key) in enumerate(rows):
            ttk.Label(grid, text=label, width=12).grid(row=i, column=0, sticky="w", pady=6)
            var = tk.StringVar(value="—")
            self.monitor_vars[key] = var
            ttk.Label(grid, textvariable=var, font=("Consolas", 12)).grid(
                row=i, column=1, sticky="w", pady=6
            )

    def _build_maint_tab(self):
        stop_box = ttk.LabelFrame(self.tab_maint, text="停止模式", padding=12)
        stop_box.pack(fill="x", pady=(0, 10))

        ttk.Label(stop_box, text="保持/阻尼功率 (mW)").grid(row=0, column=0, sticky="w")
        self.stop_power_var = tk.StringVar(value="500")
        ttk.Entry(stop_box, textvariable=self.stop_power_var, width=12).grid(row=0, column=1, padx=6)

        ttk.Button(
            stop_box, text="失锁释放", command=lambda: self.send_stop(STOP_RELEASE)
        ).grid(row=0, column=2, padx=6)
        ttk.Button(
            stop_box, text="保持", command=lambda: self.send_stop(STOP_HOLD)
        ).grid(row=0, column=3, padx=6)
        ttk.Button(
            stop_box, text="阻尼停止", command=lambda: self.send_stop(STOP_DAMPING)
        ).grid(row=0, column=4, padx=6)

        damping = ttk.LabelFrame(self.tab_maint, text="阻尼模式", padding=12)
        damping.pack(fill="x", pady=(0, 10))
        ttk.Label(damping, text="阻尼功率 (mW)").pack(side="left")
        self.damping_power_var = tk.StringVar(value="500")
        ttk.Entry(damping, textvariable=self.damping_power_var, width=12).pack(side="left", padx=6)
        ttk.Button(damping, text="进入阻尼模式", command=self.send_damping).pack(side="left", padx=6)

        zero = ttk.LabelFrame(self.tab_maint, text="零位 / 多圈", padding=12)
        zero.pack(fill="x", pady=(0, 10))
        ttk.Button(zero, text="设置当前机械原点", command=self.confirm_set_origin).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(zero, text="重置多圈圈数", command=self.confirm_reset_turn).pack(side="left")
        ttk.Label(
            zero,
            text="这两个操作会先发送失锁释放；请确保机械位置安全。",
        ).pack(side="left", padx=16)

    def _build_debug_tab(self):
        tx = ttk.LabelFrame(self.tab_debug, text="手动发送标准 CAN 数据帧（调试用）", padding=10)
        tx.pack(fill="x")

        ttk.Label(tx, text="ID (hex)").grid(row=0, column=0, padx=4)
        self.raw_can_id_var = tk.StringVar(value="6A0")
        ttk.Entry(tx, textvariable=self.raw_can_id_var, width=10).grid(row=0, column=1, padx=4)

        ttk.Label(tx, text="DATA (最多8字节)").grid(row=0, column=2, padx=(16, 4))
        self.raw_can_data_var = tk.StringVar(value="12 4C 01 01 00 60")
        ttk.Entry(tx, textvariable=self.raw_can_data_var, width=45).grid(row=0, column=3, padx=4)

        ttk.Button(tx, text="发送 CAN", command=self.send_raw_can).grid(row=0, column=4, padx=8)

        dbg = ttk.LabelFrame(self.tab_debug, text="CAN 收发", padding=8)
        dbg.pack(fill="both", expand=True, pady=(10, 0))

        self.can_text = tk.Text(dbg, height=18, wrap="none", font=("Consolas", 10))
        self.can_text.pack(fill="both", expand=True)

    def _build_log(self, parent):
        box = ttk.LabelFrame(parent, text="运行日志", padding=6)
        box.pack(fill="both", expand=False)

        self.log_text = tk.Text(box, height=9, wrap="none", font=("Consolas", 9))
        self.log_text.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(box, orient="vertical", command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

        foot = ttk.Frame(parent)
        foot.pack(fill="x", pady=(6, 0))

        self.counter_var = tk.StringVar(value="CAN TX 0 | CAN RX 0 | HA8 TX 0 | HA8 RX 0")
        ttk.Label(foot, textvariable=self.counter_var).pack(side="left")

        ttk.Button(foot, text="清空日志", command=self.clear_logs).pack(side="right")
        ttk.Button(foot, text="保存日志", command=self.save_log).pack(side="right", padx=6)

    # ---------- connection ----------
    def refresh_ports(self):
        ports = list(list_ports.comports())
        values = [p.device for p in ports]
        self.port_combo["values"] = values

        current = self.port_var.get().strip()
        if current in values:
            return
        if "COM11" in values:
            self.port_var.set("COM11")
        elif values:
            self.port_var.set(values[0])

    def toggle_connection(self):
        if self.transport.is_open:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("未选择端口", "请选择 USB-CAN 对应的 COM 端口")
            return

        try:
            self.log(f"连接 {port}，初始化 USB-CAN...")
            self.transport.open(port)
            self.protocol_parser.reset()
            self.conn_var.set(f"已连接 {port}")
            self.conn_label.configure(style="OK.TLabel")
            self.connect_btn.configure(text="断开")
            self.log(
                f"USB-CAN 初始化完成：CDC={CDC_BAUD}, CAN={CAN_BITRATE_TEXT}, "
                f"CMD=0x{DEFAULT_TX_ID:03X}, FB=0x{DEFAULT_RX_ID:03X}"
            )
        except Exception as exc:
            self.transport.close()
            self.conn_var.set("连接失败")
            self.conn_label.configure(style="BAD.TLabel")
            messagebox.showerror("连接失败", str(exc))
            self.log(f"ERROR 连接失败：{exc}")

    def disconnect(self):
        self.stop_monitor()
        self.transport.close()
        self.conn_var.set("未连接")
        self.conn_label.configure(style="BAD.TLabel")
        self.connect_btn.configure(text="连接 USB-CAN")
        self.online_var.set("舵机：未知")
        self.online_label.configure(style="")
        self.log("USB-CAN 已断开")

    # ---------- helpers ----------
    def servo_id(self) -> int:
        sid = int(self.servo_id_var.get())
        if not 0 <= sid <= 254:
            raise ValueError("舵机 ID 必须在 0~254")
        return sid

    def ensure_connected(self):
        if not self.transport.is_open:
            raise RuntimeError("请先连接 USB-CAN")

    def safe_action(self, fn):
        try:
            self.ensure_connected()
            fn()
        except Exception as exc:
            self.log(f"ERROR: {exc}")
            messagebox.showerror("操作失败", str(exc))

    def send_ha8(self, frame: bytes, label: str):
        self.ensure_connected()
        self.transport.send_ha8(frame, DEFAULT_TX_ID)
        self.tx_ha8_count += 1
        self.tx_can_count += (len(frame) + 7) // 8
        self.log(f"HA8 TX [{label}] {hex_bytes(frame)}")
        self._update_counter()

    # ---------- commands ----------
    def ping_servo(self):
        self.safe_action(
            lambda: self.send_ha8(HA8Protocol.ping(self.servo_id()), "Ping")
        )

    def query_angle(self):
        def act():
            frame = HA8Protocol.query_angle(self.servo_id(), bool(self.multiturn_var.get()))
            self.send_ha8(frame, "读取角度")
        self.safe_action(act)

    def send_move(self):
        def act():
            angle = float(self.angle_var.get())
            multiturn = bool(self.multiturn_var.get())
            if not multiturn and not -180.0 <= angle <= 180.0:
                raise ValueError(
                    f"单圈模式只能控制 -180°~+180°；当前输入 {angle:g}°。"
                    " 若要控制 600° 这类角度，请勾选‘多圈模式’。"
                )
            frame = HA8Protocol.move(
                servo_id=self.servo_id(),
                angle_deg=angle,
                multiturn=multiturn,
                mode=self.mode_var.get(),
                interval_ms=int(float(self.interval_var.get())),
                velocity_dps=float(self.velocity_var.get()),
                t_acc_ms=int(float(self.tacc_var.get())),
                t_dec_ms=int(float(self.tdec_var.get())),
                power_mw=int(float(self.power_var.get())),
            )
            self.send_ha8(frame, "运动控制")
        self.safe_action(act)

    def query_monitor(self):
        self.safe_action(
            lambda: self.send_ha8(HA8Protocol.monitor(self.servo_id()), "数据监控")
        )

    def toggle_monitor(self):
        if self.monitor_running:
            self.stop_monitor()
            return

        try:
            period = int(float(self.monitor_period_var.get()))
            if period < 50:
                raise ValueError("自动监控周期不能小于 50 ms")
        except Exception as exc:
            messagebox.showwarning("参数错误", str(exc))
            return

        self.monitor_running = True
        self.monitor_btn.configure(text="停止自动监控")
        self.log(f"自动监控开始：{period} ms")
        self._monitor_tick()

    def _monitor_tick(self):
        if not self.monitor_running:
            return

        if self.transport.is_open:
            try:
                self.send_ha8(HA8Protocol.monitor(self.servo_id()), "自动监控")
            except Exception as exc:
                self.log(f"自动监控失败：{exc}")

        try:
            period = max(50, int(float(self.monitor_period_var.get())))
        except Exception:
            period = 300
        self.monitor_job = self.after(period, self._monitor_tick)

    def stop_monitor(self):
        self.monitor_running = False
        if hasattr(self, "monitor_btn"):
            self.monitor_btn.configure(text="开始自动监控")
        if self.monitor_job is not None:
            try:
                self.after_cancel(self.monitor_job)
            except Exception:
                pass
            self.monitor_job = None

    def send_stop(self, method: int):
        def act():
            power = int(float(self.stop_power_var.get()))
            frame = HA8Protocol.stop(self.servo_id(), method, power)
            self.send_ha8(frame, f"停止 0x{method:02X}")
        self.safe_action(act)

    def send_damping(self):
        def act():
            power = int(float(self.damping_power_var.get()))
            self.send_ha8(HA8Protocol.damping(self.servo_id(), power), "阻尼控制")
        self.safe_action(act)

    def confirm_set_origin(self):
        if not messagebox.askyesno(
            "设置原点",
            "将先发送“失锁释放”，再设置当前机械原点。\n"
            "请确认机构处于安全位置。\n\n继续？",
        ):
            return

        def worker():
            try:
                sid = self.servo_id()
                self.send_ha8(HA8Protocol.stop(sid, STOP_RELEASE, 0), "失锁释放")
                time.sleep(0.05)
                self.send_ha8(HA8Protocol.set_origin(sid), "设置原点")
            except Exception as exc:
                self.ui_queue.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

    def confirm_reset_turn(self):
        if not messagebox.askyesno(
            "重置多圈",
            "将先发送“失锁释放”，再重置多圈圈数。\n"
            "请确认机构处于安全位置。\n\n继续？",
        ):
            return

        def worker():
            try:
                sid = self.servo_id()
                self.send_ha8(HA8Protocol.stop(sid, STOP_RELEASE, 0), "失锁释放")
                time.sleep(0.05)
                self.send_ha8(HA8Protocol.reset_multiturn(sid), "重置多圈")
            except Exception as exc:
                self.ui_queue.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

    def send_raw_can(self):
        def act():
            can_id = int(self.raw_can_id_var.get().strip().lower().replace("0x", ""), 16)
            data = parse_hex_string(self.raw_can_data_var.get())
            if len(data) > 8:
                raise ValueError("手动 CAN 单帧最多 8 字节")
            self.transport.send_can(can_id, data)
            self.tx_can_count += 1
            self._append_can_text(f"TX  ID=0x{can_id:03X} DLC={len(data)} DATA={hex_bytes(data)}")
            self._update_counter()
        self.safe_action(act)

    # ---------- RX ----------
    def _on_can_frame_thread(self, frame: CanFrame):
        self.ui_queue.put(("can_frame", frame))

    def _on_transport_error_thread(self, exc: Exception):
        self.ui_queue.put(("transport_error", exc))

    def _pump_ui_queue(self):
        try:
            while True:
                kind, value = self.ui_queue.get_nowait()

                if kind == "can_frame":
                    self._handle_can_frame(value)

                elif kind == "transport_error":
                    self.log(f"USB-CAN 接收错误：{value}")
                    messagebox.showerror("USB-CAN 错误", str(value))
                    self.disconnect()

                elif kind == "error":
                    self.log(f"ERROR: {value}")
                    messagebox.showerror("操作失败", str(value))

        except queue.Empty:
            pass
        self.after(20, self._pump_ui_queue)

    def _handle_can_frame(self, frame: CanFrame):
        self.rx_can_count += 1
        self._append_can_text(
            f"RX  ID=0x{frame.can_id:03X} DLC={frame.dlc} DATA={hex_bytes(frame.data)}"
        )
        self._update_counter()

        if frame.can_id != DEFAULT_RX_ID:
            return

        packets = self.protocol_parser.feed(frame.data)
        for raw in packets:
            self.rx_ha8_count += 1
            self._update_counter()

            try:
                rsp = decode_response(raw)
                self.log(
                    f"HA8 RX [{rsp.cmd_name}] ID={rsp.servo_id} "
                    f"{hex_bytes(raw)}"
                )
                self._apply_response(rsp)
            except Exception as exc:
                self.log(f"HA8 响应解析失败：{exc}; RAW={hex_bytes(raw)}")

    def _apply_response(self, rsp):
        f = rsp.fields or {}

        if rsp.cmd == 0x01 and f.get("online"):
            self.online_var.set(f"舵机：在线 ID={rsp.servo_id}")
            self.online_label.configure(style="OK.TLabel")
            return

        if "angle_deg" in f:
            self.current_angle_var.set(f"{f['angle_deg']:.1f} °")
            self.monitor_vars["angle"].set(f"{f['angle_deg']:.1f} °")

        if "turn" in f:
            self.current_turn_var.set(str(f["turn"]))
            self.monitor_vars["turn"].set(str(f["turn"]))

        if "voltage_mv" in f:
            self.online_var.set(f"舵机：在线 ID={rsp.servo_id}")
            self.online_label.configure(style="OK.TLabel")

            self.monitor_vars["voltage"].set(f"{f['voltage_mv'] / 1000.0:.3f} V")
            self.monitor_vars["current"].set(f"{f['current_ma'] / 1000.0:.3f} A")
            self.monitor_vars["power"].set(f"{f['power_mw'] / 1000.0:.3f} W")

            tc = f.get("temperature_c")
            self.monitor_vars["temperature"].set("—" if tc is None else f"{tc:.1f} °C")
            self.monitor_vars["temp_raw"].set(str(f["temperature_adc"]))
            self.monitor_vars["status"].set(
                f"0x{f['status']:02X} / {f['status']:08b}"
            )
            self.monitor_vars["status_text"].set(f["status_text"])

    # ---------- log ----------
    def log(self, text: str):
        stamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{stamp}] {text}\n")
        self.log_text.see("end")

    def _append_can_text(self, text: str):
        stamp = time.strftime("%H:%M:%S")
        self.can_text.insert("end", f"[{stamp}] {text}\n")
        self.can_text.see("end")

    def _update_counter(self):
        self.counter_var.set(
            f"CAN TX {self.tx_can_count} | CAN RX {self.rx_can_count} | "
            f"HA8 TX {self.tx_ha8_count} | HA8 RX {self.rx_ha8_count}"
        )

    def clear_logs(self):
        self.log_text.delete("1.0", "end")
        self.can_text.delete("1.0", "end")

    def save_log(self):
        path = filedialog.asksaveasfilename(
            title="保存日志",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write("=== HA8 Upper Computer Log ===\n")
            f.write(self.log_text.get("1.0", "end"))
            f.write("\n=== CAN Debug ===\n")
            f.write(self.can_text.get("1.0", "end"))

    def on_close(self):
        try:
            self.stop_monitor()
            self.transport.close()
        finally:
            self.destroy()


if __name__ == "__main__":
    app = HA8UpperComputer()
    app.mainloop()