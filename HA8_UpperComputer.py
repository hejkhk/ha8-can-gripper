# -*- coding: utf-8 -*-
"""
HA8-U35H-M direct USB serial test console.

Path:
    Windows PC -> Official servo USB serial adapter/expansion board
               -> HA8-U35H-M (12V servo supply as rated)

The transport writes complete HA8 frames directly; no CAN/CTS/F103.
HA8 packet encoding and response parsing remain in ha8_protocol.py.
"""

from __future__ import annotations

import csv
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

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
    build_request,
    decode_status,
    CMD_NAMES,
    CMD_READ_DATA,
    CMD_WRITE_DATA,
    CMD_PING,
    CMD_RESET_USER_DATA,
    CMD_MONITOR,
)
from ha8_serial import HA8SerialTransport
from grip_panel import GripPanel
from auto_grip_panel import AutoGripPanel

APP_TITLE = "HA8-U35H-M 全功能测试上位机"
APP_VERSION = "3.2-beta"


class HA8UpperComputer(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(f"{APP_TITLE} V{APP_VERSION}")
        self.geometry("1330x880")
        self.minsize(1100, 730)

        self.protocol_parser = ResponseStreamParser()
        self.transport = HA8SerialTransport(
            on_bytes=self._on_serial_bytes_thread,
            on_error=self._on_transport_error_thread,
            on_raw=self._on_serial_raw_thread,
        )



        self.ui_queue: queue.Queue = queue.Queue()
        self.monitor_running = False
        self.monitor_job = None
        self.scan_running = False
        self.scan_job = None
        self.scan_found = set()
        self.scan_target = set()
        self.ha8_timestamps = {}
        self.reg_history = {}
        self.samples = []
        self.expert_mode = tk.BooleanVar(value=False)

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
            text="官方 USB 串口转接板 → HA8 | 115200 8N1 | 原生 HA8 协议",
        ).pack(side="right")

        self._build_connection(root)

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, pady=(8, 8))

        self.tab_control = ttk.Frame(self.nb, padding=10)
        self.tab_monitor = ttk.Frame(self.nb, padding=10)
        self.tab_grip = ttk.Frame(self.nb, padding=10)
        self.tab_auto_grip = ttk.Frame(self.nb, padding=10)
        self.tab_maint = ttk.Frame(self.nb, padding=10)
        self.tab_scan = ttk.Frame(self.nb, padding=10)
        self.tab_config = ttk.Frame(self.nb, padding=10)
        self.tab_advanced = ttk.Frame(self.nb, padding=10)
        self.tab_raw = ttk.Frame(self.nb, padding=10)
        self.tab_debug = ttk.Frame(self.nb, padding=10)

        self.nb.add(self.tab_control, text="位置控制")
        self.nb.add(self.tab_monitor, text="数据监控")
        self.nb.add(self.tab_grip, text="夹持检测（实验性）")
        self.nb.add(self.tab_auto_grip, text="自动抓取测试")
        self.nb.add(self.tab_maint, text="停止 / 标定")
        self.nb.add(self.tab_scan, text="通讯检测")
        self.nb.add(self.tab_config, text="参数读写")
        self.nb.add(self.tab_advanced, text="同步 / 异步")
        self.nb.add(self.tab_raw, text="HA8 原始协议")
        self.nb.add(self.tab_debug, text="串口调试")

        self._build_control_tab()
        self._build_monitor_tab()
        self.grip_panel = GripPanel(self.tab_grip, self)
        self.grip_panel.pack(fill="both", expand=True)
        self.auto_grip_panel = AutoGripPanel(self.tab_auto_grip, self)
        self.auto_grip_panel.pack(fill="both", expand=True)
        self._build_maint_tab()
        self._build_scan_tab()
        self._build_config_tab()
        self._build_advanced_tab()
        self._build_raw_protocol_tab()
        self._build_debug_tab()
        self._build_log(root)

    def _build_connection(self, parent):
        box = ttk.LabelFrame(parent, text="官方舵机转接板 USB 串口直连", padding=8)
        box.pack(fill="x", pady=(8, 0))
        ttk.Label(box, text="串口").grid(row=0, column=0, padx=4, pady=4)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(box, textvariable=self.port_var, width=18, state="normal")
        self.port_combo.grid(row=0, column=1, padx=4)
        ttk.Button(box, text="刷新", command=self.refresh_ports).grid(row=0, column=2, padx=4)

        ttk.Label(box, text="波特率").grid(row=0, column=3, padx=(14, 4))
        self.serial_baud_var = tk.StringVar(value="115200")
        self.serial_baud_combo = ttk.Combobox(
            box, textvariable=self.serial_baud_var,
            values=["9600", "57600", "115200", "230400"],
            width=12, state="readonly",
        )
        self.serial_baud_combo.grid(row=0, column=4, padx=4)

        self.connect_btn = ttk.Button(box, text="连接", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=5, padx=8)
        self.conn_var = tk.StringVar(value="未连接")
        self.conn_label = ttk.Label(box, textvariable=self.conn_var, style="BAD.TLabel")
        self.conn_label.grid(row=0, column=6, padx=8)

        ttk.Label(box, text="舵机 ID").grid(row=0, column=7, padx=(14, 4))
        self.servo_id_var = tk.IntVar(value=0)
        ttk.Spinbox(box, from_=0, to=254, textvariable=self.servo_id_var, width=7).grid(
            row=0, column=8, padx=4
        )
        ttk.Button(box, text="Ping", command=self.ping_servo).grid(row=0, column=9, padx=4)
        self.online_var = tk.StringVar(value="舵机：未知")
        self.online_label = ttk.Label(box, textvariable=self.online_var)
        self.online_label.grid(row=0, column=10, padx=8)

        ttk.Label(
            box,
            text="UART 8N1 · 发送完整 HA8 指令，不经过 CAN/STM32",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=11, sticky="w", padx=6, pady=(5, 0))

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
        ttk.Button(top,text="导出监控CSV",command=self.export_monitor_csv).pack(side="right")
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
            ("输出轴动态参考扭矩", "torque_ref"),
            ("夹持状态", "grip_state"),
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

    def _build_scan_tab(self):
        g = ttk.LabelFrame(self.tab_scan, text="通讯检测 / 舵机 ID 扫描", padding=16)
        g.pack(fill="x")
        ttk.Label(g, text="起始 ID").grid(row=0, column=0)
        self.scan_from_var = tk.StringVar(value="0")
        ttk.Entry(g, textvariable=self.scan_from_var, width=8).grid(row=0, column=1, padx=6)
        ttk.Label(g, text="结束 ID").grid(row=0, column=2)
        self.scan_to_var = tk.StringVar(value="10")
        ttk.Entry(g, textvariable=self.scan_to_var, width=8).grid(row=0, column=3, padx=6)
        ttk.Button(g, text="开始扫描", command=self.start_scan).grid(row=0, column=4, padx=6)
        ttk.Button(g, text="停止扫描", command=self.stop_scan).grid(row=0, column=5, padx=6)
        ttk.Label(g, text="每次最多扫描 32 个 ID；扫描期间请停止自动监控").grid(row=1,column=0,columnspan=6,sticky="w",pady=(12,0))
        self.scan_info = tk.StringVar(value="未扫描")
        ttk.Label(g, textvariable=self.scan_info, font=("Consolas", 12)).grid(row=2,column=0,columnspan=7,sticky="w",pady=10)
        ttk.Button(g, text="对当前 ID Ping", command=self.ping_servo).grid(row=3,column=0,columnspan=2,sticky="w")

    def _build_config_tab(self):
        reg = ttk.LabelFrame(self.tab_config, text="数据表（读写原始字节，必须查阅官方地址表）", padding=14)
        reg.pack(fill="x")
        ttk.Label(reg,text="地址 (十进制 / 0xHEX)").grid(row=0,column=0,sticky="w")
        self.reg_addr_var = tk.StringVar(value="1")
        ttk.Entry(reg,textvariable=self.reg_addr_var,width=11).grid(row=0,column=1,padx=6)
        ttk.Button(reg,text="读取该地址",command=self.read_register).grid(row=0,column=2,padx=5)
        ttk.Label(reg,text="快速读取：1=电压  2=电流  3=功率  4=温度ADC  49=缓启动（需核对固件）").grid(row=1,column=0,columnspan=6,sticky="w",pady=8)
        ttk.Label(reg,text="写入数据 HEX").grid(row=2,column=0,sticky="w",pady=8)
        self.reg_hex_var = tk.StringVar(value="01")
        ttk.Entry(reg,textvariable=self.reg_hex_var,width=35).grid(row=2,column=1,columnspan=2,sticky="w")
        ttk.Button(reg,text="写入（需确认）",command=self.write_register).grid(row=2,column=3,padx=6)
        self.reg_out_var = tk.StringVar(value="尚未读取")
        ttk.Label(reg,textvariable=self.reg_out_var,wraplength=920).grid(row=3,column=0,columnspan=6,sticky="w",pady=8)

        danger = ttk.LabelFrame(self.tab_config,text="危险操作：恢复用户数据 / 出厂配置",padding=14)
        danger.pack(fill="x",pady=12)
        ttk.Label(danger,text="恢复后舵机 ID 会回到 0，可能修改其他设置；总线上请只接一颗舵机。",foreground="#a31717").pack(anchor="w")
        ttk.Button(danger,text="恢复用户数据（双重确认）",command=self.reset_user_data).pack(anchor="w",pady=10)

    def _build_advanced_tab(self):
        info = ttk.LabelFrame(self.tab_advanced,text="协议高级测试（部分功能仅支持指定固件版本）",padding=10)
        info.pack(fill="x")
        ttk.Label(info,text="同步 / 异步功能：官方 SDK 标注需无刷磁编码 V316+；HA8 固件兼容性尚未实测。",foreground="#a31717").pack(anchor="w")
        ttk.Checkbutton(info,text="我已核对硬件固件版本，允许发送高级/实验性命令",variable=self.expert_mode).pack(anchor="w",pady=7)

        asyncf=ttk.LabelFrame(self.tab_advanced,text="异步执行（开始缓存 → 发送角度指令 → 执行/取消）",padding=10)
        asyncf.pack(fill="x",pady=8)
        ttk.Button(asyncf,text="1. 开始异步 0x12",command=self.begin_async).pack(side="left",padx=5)
        ttk.Button(asyncf,text="2. 缓存上方位置页的角度指令",command=self.async_move).pack(side="left",padx=5)
        ttk.Button(asyncf,text="3. 执行 0x13",command=lambda:self.end_async(False)).pack(side="left",padx=5)
        ttk.Button(asyncf,text="取消缓存 0x13",command=lambda:self.end_async(True)).pack(side="left",padx=5)

        guided=ttk.LabelFrame(self.tab_advanced,text="同步角度控制（厂商 SDK 六种模式）",padding=10)
        guided.pack(fill="x",pady=8)
        ttk.Label(guided,text="目标列表（以分号分隔，如 0:30;1:-45）").grid(row=0,column=0,sticky="w")
        self.sync_targets_var=tk.StringVar(value="0:20")
        ttk.Entry(guided,textvariable=self.sync_targets_var,width=33).grid(row=0,column=1,padx=5)
        self.sync_multiturn_var=tk.BooleanVar(value=False)
        ttk.Checkbutton(guided,text="多圈",variable=self.sync_multiturn_var).grid(row=0,column=2,padx=5)
        self.sync_mode_var=tk.StringVar(value="velocity")
        ttk.Combobox(guided,textvariable=self.sync_mode_var,state="readonly",width=12,values=["simple","interval","velocity"]).grid(row=0,column=3,padx=5)
        opts=[("运动时间(ms)","sync_interval_var","2000"),("速度(°/s)","sync_velocity_var","60"),("加速(ms)","sync_acc_var","200"),("减速(ms)","sync_dec_var","200"),("功率(mW)","sync_power_var","3000")]
        for i,(label,attr,dflt) in enumerate(opts):
            ttk.Label(guided,text=label).grid(row=1,column=i*2,sticky="w",pady=6)
            v=tk.StringVar(value=dflt);setattr(self,attr,v)
            ttk.Entry(guided,textvariable=v,width=8).grid(row=1,column=i*2+1,padx=3)
        ttk.Button(guided,text="预览同步指令",command=self.preview_guided_sync).grid(row=2,column=0,pady=9)
        ttk.Button(guided,text="确认发送同步运动",command=self.send_guided_sync).grid(row=2,column=1,pady=9)
        ttk.Label(guided,text="同步状态监控 ID(逗号分隔)").grid(row=3,column=0,sticky="w",pady=5)
        self.sync_monitor_ids_var=tk.StringVar(value="0")
        ttk.Entry(guided,textvariable=self.sync_monitor_ids_var,width=28).grid(row=3,column=1,sticky="w")
        ttk.Button(guided,text="读取多舵机监控",command=self.send_sync_monitor).grid(row=3,column=2,sticky="w",padx=6)
        self.sync_guided_preview=tk.StringVar(value="完整 HA8 预览：—")
        ttk.Label(guided,textvariable=self.sync_guided_preview,wraplength=1050).grid(row=4,column=0,columnspan=10,sticky="w",pady=5)

        syncf=ttk.LabelFrame(self.tab_advanced,text="同步指令 0x19（专家原始载荷）",padding=10)
        syncf.pack(fill="x",pady=8)
        ttk.Label(syncf,text="不同固件同步 CONTENT 字段封装可能不同，请按已确认的 SDK 格式输入；软件不推测未核实字节布局。",wraplength=1050).pack(anchor="w")
        self.sync_payload = tk.StringVar(value="")
        ttk.Entry(syncf,textvariable=self.sync_payload,width=75).pack(side="left",padx=5,pady=10)
        ttk.Button(syncf,text="构造/预览",command=self.preview_sync).pack(side="left",padx=5)
        ttk.Button(syncf,text="确认发送",command=self.send_sync).pack(side="left",padx=5)
        self.sync_preview = tk.StringVar(value="等待输入同步 CONTENT 十六进制字节")
        ttk.Label(self.tab_advanced,textvariable=self.sync_preview,wraplength=1080).pack(anchor="w",pady=8)

    def _build_raw_protocol_tab(self):
        g=ttk.LabelFrame(self.tab_raw,text="HA8 请求封装器 / 响应解析",padding=14)
        g.pack(fill="x")
        ttk.Label(g,text="指令 CMD（HEX）").grid(row=0,column=0,sticky="w")
        self.raw_cmd_var=tk.StringVar(value="01")
        ttk.Entry(g,textvariable=self.raw_cmd_var,width=10).grid(row=0,column=1,padx=6)
        ttk.Label(g,text="CONTENT (HEX)").grid(row=0,column=2,sticky="w")
        self.raw_content_var=tk.StringVar(value="00")
        ttk.Entry(g,textvariable=self.raw_content_var,width=64).grid(row=0,column=3,padx=6)
        ttk.Button(g,text="仅构造校验",command=self.preview_raw).grid(row=0,column=4,padx=5)
        ttk.Button(g,text="发送完整 HA8 指令",command=self.send_raw_ha8).grid(row=1,column=3,sticky="w",pady=12)
        self.raw_preview_var=tk.StringVar(value="—")
        ttk.Label(g,textvariable=self.raw_preview_var,wraplength=1080).grid(row=2,column=0,columnspan=5,sticky="w",pady=8)
        ttk.Label(g,text="按 HA8 原生协议自动添加 12 4C、LEN 和校验和；通过官方 USB 串口一次发送完整指令。",foreground="#a31717").grid(row=3,column=0,columnspan=5,sticky="w",pady=6)
        tests=ttk.LabelFrame(self.tab_raw,text="常用原始例子",padding=14)
        tests.pack(fill="x",pady=10)
        for label,cmd,body in [("Ping","01","00"),("单圈读取","0A","00"),("多圈读取","10","00"),("监控","16","00")]:
            ttk.Button(tests,text=label,command=lambda c=cmd,b=body:self.load_raw_example(c,b)).pack(side="left",padx=7)

    def _build_debug_tab(self):
        tx = ttk.LabelFrame(self.tab_debug, text="手动发送串口原始字节（仅用于协议调试）", padding=10)
        tx.pack(fill="x")
        ttk.Label(tx, text="HEX 字节").grid(row=0, column=0, padx=4)
        self.raw_serial_var = tk.StringVar(value="12 4C 01 01 00 60")
        ttk.Entry(tx, textvariable=self.raw_serial_var, width=78).grid(row=0, column=1, padx=6)
        ttk.Button(tx, text="发送原始字节", command=self.send_raw_serial).grid(
            row=0, column=2, padx=8)
        ttk.Label(
            tx,
            text="注意：此项不会自动计算校验和。如需构造正确命令，建议使用“HA8 原始协议”页。",
            foreground="#a31717",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=8)
        dbg = ttk.LabelFrame(self.tab_debug, text="实际串口收发字节（TX / RX）", padding=8)
        dbg.pack(fill="both", expand=True, pady=(10, 0))
        self.serial_text = tk.Text(dbg, height=18, wrap="none", font=("Consolas", 10))
        self.serial_text.pack(fill="both", expand=True)

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

        self.counter_var = tk.StringVar(value="HA8 TX 0 | HA8 RX 0")
        ttk.Label(foot, textvariable=self.counter_var).pack(side="left")

        ttk.Button(foot, text="清空日志", command=self.clear_logs).pack(side="right")
        ttk.Button(foot, text="保存日志", command=self.save_log).pack(side="right", padx=6)

    # ---------- connection ----------
    def refresh_ports(self):
        values = [p.device for p in list_ports.comports()]
        self.port_combo["values"] = values
        if self.port_var.get().strip() in values:
            return
        # On the test bench the official adapter was previously COM6.
        # This is only a preference; the OS may assign any COM port.
        if "COM6" in values:
            self.port_var.set("COM6")
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
            messagebox.showwarning("未选择端口", "请选择官方舵机 USB 串口转接板对应的 COM 端口")
            return
        try:
            baud = int(self.serial_baud_var.get())
            self.transport.open(port, baudrate=baud)
            self.protocol_parser.reset()
            self.conn_var.set(f"已连接 {port} · {baud} 8N1")
            self.conn_label.configure(style="OK.TLabel")
            self.connect_btn.configure(text="断开")
            self.serial_baud_combo.configure(state="disabled")
            self.log(f"官方 USB 串口已连接：{port}, {baud} 8N1，原生 HA8 帧，不经过 CAN")
        except Exception as exc:
            self.transport.close()
            self.conn_var.set("连接失败")
            self.conn_label.configure(style="BAD.TLabel")
            messagebox.showerror("连接失败", str(exc))
            self.log(f"ERROR 连接失败：{exc}")

    def disconnect(self):
        self.stop_scan()
        self.stop_monitor()
        self.transport.close()
        self.protocol_parser.reset()
        self.conn_var.set("未连接")
        self.conn_label.configure(style="BAD.TLabel")
        self.connect_btn.configure(text="连接")
        self.serial_baud_combo.configure(state="readonly")
        self.online_var.set("舵机：未知")
        self.online_label.configure(style="")
        self.grip_panel.disconnected()
        self.auto_grip_panel.disconnected()
        self.log("官方 USB 串口已断开")

    # ---------- helpers ----------
    def servo_id(self) -> int:
        sid = int(self.servo_id_var.get())
        if not 0 <= sid <= 254:
            raise ValueError("舵机 ID 必须在 0~254")
        return sid

    def ensure_connected(self):
        if not self.transport.is_open:
            raise RuntimeError("请先连接通讯设备")

    def safe_action(self, fn):
        try:
            self.ensure_connected()
            fn()
        except Exception as exc:
            self.log(f"ERROR: {exc}")
            messagebox.showerror("操作失败", str(exc))

    def send_ha8(self, frame: bytes, label: str):
        self.ensure_connected()
        self.transport.send_ha8(frame)
        self.tx_ha8_count += 1
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
        if not messagebox.askyesno("设置原点", "将先释放锁力，再将当前位置设为原点。\n请确认机构处于安全位置，继续？"):
            return
        def begin():
            sid=self.servo_id()
            self.send_ha8(HA8Protocol.stop(sid, STOP_RELEASE, 0), "原点准备：失锁释放")
            self.after(120,lambda:self.safe_action(lambda:self.send_ha8(HA8Protocol.set_origin(sid),"设置原点")))
        self.safe_action(begin)

    def confirm_reset_turn(self):
        if not messagebox.askyesno("重置多圈", "将先释放锁力，再将圈数重置。\n请确认机构处于安全位置，继续？"):
            return
        def begin():
            sid=self.servo_id()
            self.send_ha8(HA8Protocol.stop(sid, STOP_RELEASE, 0), "圈数重置准备：失锁释放")
            self.after(120,lambda:self.safe_action(lambda:self.send_ha8(HA8Protocol.reset_multiturn(sid),"重置圈数")))
        self.safe_action(begin)

    def start_scan(self):
        def act():
            lo=int(self.scan_from_var.get(),0)
            hi=int(self.scan_to_var.get(),0)
            if not (0<=lo<=hi<=254) or hi-lo+1>32:
                raise ValueError("扫描范围必须为 0~254 且不超过 32 个 ID")
            self.stop_monitor()
            self.stop_scan()
            self.scan_found=set()
            self.scan_target=set(range(lo,hi+1))
            self._scan_current=lo
            self._scan_last=hi
            self.scan_running=True
            self._scan_next()
        self.safe_action(act)

    def _scan_next(self):
        if not self.scan_running: return
        if self._scan_current>self._scan_last:
            self.scan_running=False
            self.scan_info.set(f"扫描完成，响应的 ID: {sorted(self.scan_found)}")
            self.log(self.scan_info.get())
            return
        sid=self._scan_current
        try:
            self.send_ha8(HA8Protocol.ping(sid),f"扫描 ID={sid}")
        except Exception as exc:
            self.stop_scan()
            self.log(f"扫描失败：{exc}")
            return
        self.scan_info.set(f"正在扫描 {sid} / {self._scan_last}，已响应：{sorted(self.scan_found)}")
        self._scan_current+=1
        self.scan_job=self.after(120,self._scan_next)

    def stop_scan(self):
        self.scan_running=False
        if self.scan_job is not None:
            try: self.after_cancel(self.scan_job)
            except Exception: pass
        self.scan_job=None

    def _reg_addr(self):
        addr=int(self.reg_addr_var.get().strip(),0)
        if not 0<=addr<=255: raise ValueError("寄存器地址范围 0~255")
        return addr

    def read_register(self):
        self.safe_action(lambda:self.send_ha8(HA8Protocol.read_data(self.servo_id(),self._reg_addr()),"读取寄存器"))

    def write_register(self):
        def act():
            addr=self._reg_addr()
            data=parse_hex_string(self.reg_hex_var.get())
            if not data or len(data)>32:
                raise ValueError("请输入 1~32 字节 HEX 数据")
            sid=self.servo_id()
            if not messagebox.askyesno("写入内存表",f"即将修改设备配置：ID={sid}，地址={addr}，数据={hex_bytes(data)}。\n确定数据类型与访问权限正确？"):
                return
            self.send_ha8(HA8Protocol.write_data(sid,addr,data),"写入寄存器")
        self.safe_action(act)

    def reset_user_data(self):
        def act():
            sid=self.servo_id()
            if not messagebox.askyesno("危险：恢复用户数据",f"此操作可能重置 ID、配置表并影响机械臂总线，请确保总线仅一颗舵机 ID={sid}。继续？"):
                return
            prompt=simpledialog.askstring("二次确认", "输入 RESET 才能发送，恢复后舵机 ID 可能变为 0：",parent=self)
            if prompt!="RESET":return
            self.send_ha8(HA8Protocol.reset_user_data(sid),"恢复用户数据（无固定响应）")
        self.safe_action(act)

    def _expert_allowed(self):
        if not self.expert_mode.get():
            raise ValueError("请先勾选已确认固件版本的高级功能开关")

    def begin_async(self):
        def act():
            self._expert_allowed()
            self.stop_monitor()
            self.send_ha8(HA8Protocol.begin_async(),"开始异步")
        self.safe_action(act)

    def async_move(self):
        self.safe_action(lambda:(self._expert_allowed(),self.send_move()))

    def end_async(self,cancel):
        def act():
            self._expert_allowed()
            action="取消缓存" if cancel else "执行缓存的运动"
            if not messagebox.askyesno("异步确认",f"即将 {action}；确认机械结构安全？"):
                return
            self.send_ha8(HA8Protocol.end_async(cancel),"异步结束/取消")
        self.safe_action(act)

    def _guided_sync_frame(self):
        pieces=[x.strip() for x in self.sync_targets_var.get().split(";") if x.strip()]
        targets=[]
        for item in pieces:
            pair=item.split(":")
            if len(pair)!=2: raise ValueError("目标格式应为 0:20;1:-45")
            targets.append((int(pair[0]),float(pair[1])))
        return HA8Protocol.sync_motion(
            targets=targets,
            multiturn=self.sync_multiturn_var.get(),
            mode=self.sync_mode_var.get(),
            interval_ms=int(self.sync_interval_var.get()),
            velocity_dps=float(self.sync_velocity_var.get()),
            t_acc_ms=int(self.sync_acc_var.get()),
            t_dec_ms=int(self.sync_dec_var.get()),
            power_mw=int(self.sync_power_var.get()),
        )

    def preview_guided_sync(self):
        try:
            packet=self._guided_sync_frame()
            self.sync_guided_preview.set(f"HA8 ({len(packet)}字节)：{hex_bytes(packet)}；UART单次发送")
        except Exception as exc:
            self.sync_guided_preview.set(f"参数错误：{exc}")

    def send_guided_sync(self):
        def act():
            self._expert_allowed()
            self.stop_monitor()
            packet=self._guided_sync_frame()
            if not messagebox.askyesno("同步运动确认",f"同步将控制 {packet[6]} 个舵机，固件须支持 V316+，确认空载无干涉？"):
                return
            self.send_ha8(packet,"同步角度控制 0x19")
        self.safe_action(act)

    def send_sync_monitor(self):
        def act():
            self._expert_allowed()
            ids=[int(x.strip()) for x in self.sync_monitor_ids_var.get().split(",") if x.strip()]
            packet=HA8Protocol.sync_monitor(ids)
            self.send_ha8(packet,"同步监控 0x19")
        self.safe_action(act)

    def _sync_bytes(self):
        data=parse_hex_string(self.sync_payload.get())
        if not data: raise ValueError("请输入厂商协议确认过的同步 CONTENT HEX")
        return HA8Protocol.sync_raw(data)

    def preview_sync(self):
        try:
            v=self._sync_bytes()
            self.sync_preview.set(f"完整 HA8 ({len(v)} bytes): {hex_bytes(v)}  | UART单次发送")
        except Exception as exc:
            self.sync_preview.set(str(exc))

    def send_sync(self):
        def act():
            self._expert_allowed()
            b=self._sync_bytes()
            if not messagebox.askyesno("发送同步指令",f"0x19 同步指令，{len(b)} 字节（UART直接发送）；此载荷未经本机固件验证。确定发送？"):
                return
            self.send_ha8(b,"同步指令 0x19 / 原始载荷")
        self.safe_action(act)

    def load_raw_example(self,cmd,content):
        self.raw_cmd_var.set(cmd)
        self.raw_content_var.set(content)
        self.preview_raw()

    def _raw_frame(self):
        cmd=int(self.raw_cmd_var.get().strip().lower().replace("0x",""),16)
        content=parse_hex_string(self.raw_content_var.get())
        return build_request(cmd,content)

    def preview_raw(self):
        try:
            f=self._raw_frame()
            self.raw_preview_var.set(f"请求 {hex_bytes(f)}  | 共 {len(f)} 字节 / UART直接发送")
        except Exception as exc:
            self.raw_preview_var.set(f"构造失败：{exc}")

    def send_raw_ha8(self):
        def act():
            f=self._raw_frame()
            if f[2] not in (0x01,0x03,0x0A,0x10,0x16):
                if not messagebox.askyesno("非只读命令",f"此指令 CMD=0x{f[2]:02X} 可能使舵机动作或修改配置。\n{hex_bytes(f)}\n确定发送？"):
                    return
            self.send_ha8(f,"HA8 原始封包")
        self.safe_action(act)

    def send_raw_serial(self):
        def act():
            data = parse_hex_string(self.raw_serial_var.get())
            if not data:
                raise ValueError("HEX 不能为空")
            if not messagebox.askyesno(
                "发送原始串口数据",
                f"未封装/未检查的原始字节可能触发舵机动作。\\n"
                f"即将发送 {len(data)} 字节：\\n{hex_bytes(data)}\\n\\n确认？"
            ):
                return
            self.transport.send_raw(data)
            self.log(f"UART TX RAW {hex_bytes(data)}")
        self.safe_action(act)

    # ---------- RX ----------
    def _on_serial_raw_thread(self, direction: str, packet: bytes):
        self.ui_queue.put(("serial_stream", (direction, bytes(packet))))

    def _on_serial_bytes_thread(self, data: bytes):
        self.ui_queue.put(("serial_data", bytes(data)))

    def _on_transport_error_thread(self, exc: Exception):
        self.ui_queue.put(("transport_error", exc))

    def _pump_ui_queue(self):
        try:
            while True:
                kind, value = self.ui_queue.get_nowait()
                if kind == "serial_data":
                    self._handle_serial_data(value)
                elif kind == "serial_stream":
                    direction, data = value
                    self._append_serial_text(f"{direction}  {hex_bytes(data)}")
                elif kind == "transport_error":
                    self.log(f"串口接收错误：{value}")
                    messagebox.showerror("串口错误", str(value))
                    self.disconnect()
                elif kind == "error":
                    self.log(f"ERROR: {value}")
                    messagebox.showerror("操作失败", str(value))
        except queue.Empty:
            pass
        self.after(20, self._pump_ui_queue)

    def _handle_serial_data(self, data: bytes):
        packets = self.protocol_parser.feed(data)
        for raw in packets:
            self.rx_ha8_count += 1
            self._update_counter()
            try:
                rsp = decode_response(raw)
                self.log(
                    f"HA8 RX [{rsp.cmd_name}] ID={rsp.servo_id} {hex_bytes(raw)}"
                )
                self._apply_response(rsp)
            except Exception as exc:
                self.log(f"HA8 响应解析失败：{exc}; RAW={hex_bytes(raw)}")

    def _apply_response(self, rsp):
        f = rsp.fields or {}

        if rsp.cmd == CMD_PING and f.get("online"):
            if self.scan_running and rsp.servo_id in self.scan_target:
                self.scan_found.add(rsp.servo_id)
                self.scan_info.set(f"扫描进行中，已响应：{sorted(self.scan_found)}")
            if rsp.servo_id==self.servo_id():
                self.online_var.set(f"舵机：在线 ID={rsp.servo_id}")
                self.online_label.configure(style="OK.TLabel")
            return

        if rsp.cmd==CMD_READ_DATA and "address" in f:
            addr=f["address"]
            value=f.get("data",b"")
            msg=f"ID={rsp.servo_id}, 地址 {addr}, HEX {hex_bytes(value)}"
            if addr in (1,2,3) and len(value)==2:
                raw=int.from_bytes(value,"little")
                msg+=f"，数值 {raw/1000.0:.3f} ({'V' if addr==1 else 'A' if addr==2 else 'W'})"
            elif addr==4 and len(value)==2:
                msg+=f"，ADC {int.from_bytes(value,'little')}"
            self.reg_out_var.set(msg)
            self.reg_history[addr]=value

        if rsp.cmd==CMD_WRITE_DATA and "write_ok" in f:
            self.reg_out_var.set(f"写入响应：地址 {f['address']}，成功={f['write_ok']}，结果字节={f['result_raw']}")

        if "angle_deg" in f:
            self.current_angle_var.set(f"{f['angle_deg']:.1f} °")
            self.monitor_vars["angle"].set(f"{f['angle_deg']:.1f} °")

        if "turn" in f:
            self.current_turn_var.set(str(f["turn"]))
            self.monitor_vars["turn"].set(str(f["turn"]))

        if "voltage_mv" in f:
            grip_result=self.grip_panel.on_monitor(rsp.servo_id,f)
            self.auto_grip_panel.on_monitor(rsp.servo_id,f)
            self.samples.append((
                time.time(),rsp.servo_id,f["voltage_mv"],f["current_ma"],f["power_mw"],
                f["temperature_adc"],f["status"],f["angle_deg"],f["turn"],
                "" if grip_result is None or grip_result.dynamic_torque_nm is None else round(grip_result.dynamic_torque_nm,5),
                "" if grip_result is None or grip_result.angle_speed_dps is None else round(grip_result.angle_speed_dps,5),
                "" if grip_result is None else grip_result.state.value,
                "" if grip_result is None else grip_result.note,
            ))
            if len(self.samples)>20000:
                self.samples=self.samples[-20000:]
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

    def export_monitor_csv(self):
        if not self.samples:
            messagebox.showinfo("没有数据","请先读取一次或启动自动状态监控。")
            return
        path=filedialog.asksaveasfilename(title="保存监控数据",defaultextension=".csv",filetypes=[("CSV","*.csv")])
        if not path:return
        with open(path,"w",encoding="utf-8-sig",newline="") as fh:
            writer=csv.writer(fh)
            writer.writerow(["timestamp_s","servo_id","voltage_mV","current_mA","power_mW","temperature_ADC","status_raw","angle_deg","turn","dynamic_torque_ref_Nm","angle_speed_dps","grip_state","grip_note"])
            writer.writerows(self.samples)
        self.log(f"CSV 监控数据已保存：{path}，{len(self.samples)} 行")

    # ---------- log ----------
    def log(self, text: str):
        stamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{stamp}] {text}\n")
        self.log_text.see("end")

    def _append_serial_text(self, text: str):
        stamp = time.strftime("%H:%M:%S")
        self.serial_text.insert("end", f"[{stamp}] {text}\n")
        self.serial_text.see("end")

    def _update_counter(self):
        self.counter_var.set(
            f"HA8 TX {self.tx_ha8_count} | HA8 RX {self.rx_ha8_count}"
        )

    def clear_logs(self):
        self.log_text.delete("1.0", "end")
        self.serial_text.delete("1.0", "end")

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
            f.write("\n=== Serial Debug ===\n")
            f.write(self.serial_text.get("1.0", "end"))

    def on_close(self):
        try:
            self.stop_scan()
            self.stop_monitor()
            self.transport.close()
        finally:
            self.destroy()


if __name__ == "__main__":
    app = HA8UpperComputer()
    app.mainloop()