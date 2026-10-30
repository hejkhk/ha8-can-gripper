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
from grip_force_calibration import ForceMap, DEFAULT_PATH, observed_closing_motion
from calibration_capture import CalibrationRun, StepMotionState
from pressure_protocol import estimate_circuit_force_g
from ha8_protocol import HA8Protocol, STOP_HOLD


class PressureLabPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.link = PressureSerialLink(self._thread_frame, self._thread_error)
        self.sensor = PressureEvidence(rf_kohm=158)
        self.recorder = CurveRecorder()
        self.capture = None
        self.step_state = StepMotionState()
        self.last_ha8 = None
        self.live_force_text = tk.StringVar(value="未归零 · -- gf")
        self.live_voltage_text = tk.StringVar(value="ADC -- · -- mV")
        self.step_status_text = tk.StringVar(value="等待归零并开始采集")
        self.confirm_mechanism = tk.BooleanVar(value=False)
        self.model = None
        self.model_message = tk.StringVar(value="离线模型：尚未生成")
        self.gap_a_angle = tk.StringVar()
        self.gap_a_mm = tk.StringVar()
        self.gap_b_angle = tk.StringVar()
        self.gap_b_mm = tk.StringVar()
        self._load_model()
        self.pressure_port = tk.StringVar(value="")
        self.connection_text = tk.StringVar(value="未连接压力模块")
        self.adc_text = tk.StringVar(value="— ADC")
        self.pressure_text = tk.StringVar(value="—")
        self.zero_text = tk.StringVar(value="⚠ 尚未归零：请让压力片完全无载，再点击归零")
        self.evidence_text = tk.StringVar(value="待机：传感器仅用于实验验证，不影响抓取控制")
        self.points_text = tk.StringVar(value="尚未开始采集")
        self.unit = tk.StringVar(value="adc")
        self.trial = tk.StringVar(value="试验1")
        self.manual_closing = tk.BooleanVar(value=False)
        self._previous_ha8 = None
        self._job = None
        self._build()
        self.refresh_ports()
        self._update_zero_controls()
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

        readouts = ttk.LabelFrame(area, text="② 必做：压力片无载归零（每次连接后重新采集）", padding=10)
        readouts.pack(fill="x", pady=(0, 8))
        first = ttk.Frame(readouts)
        first.pack(fill="x")
        ttk.Label(first, text="原始读数：").pack(side="left")
        ttk.Label(first, textvariable=self.adc_text, font=("Consolas", 13, "bold")).pack(side="left")
        ttk.Label(first, text="  理论受力（158kΩ 假定）：").pack(side="left", padx=(14, 0))
        ttk.Label(first, textvariable=self.pressure_text, font=("Consolas", 13, "bold")).pack(side="left")
        row = ttk.Frame(readouts)
        row.pack(fill="x", pady=6)
        self.zero_btn = ttk.Button(row, text="① 无载归零（采最近1秒）", command=self.capture_zero)
        self.zero_btn.pack(side="left")
        ttk.Button(row, text="检查当前压力接触", command=self.check_contact).pack(side="left", padx=8)
        ttk.Label(row, textvariable=self.zero_text).pack(side="left", padx=10)
        live = ttk.Frame(readouts)
        live.pack(fill="x", pady=(6, 4))
        ttk.Label(live, text="实时指尖理论受力：",font=("Microsoft YaHei UI",11)).pack(side="left")
        ttk.Label(live,textvariable=self.live_force_text,font=("Consolas",23,"bold"),
                  foreground="#185d94").pack(side="left")
        ttk.Label(live,textvariable=self.live_voltage_text).pack(side="left",padx=18)
        ttk.Label(readouts,text="理论估计：Rf=158kΩ。传感器标称1kg；厂家2kg曲线点不是额定测力范围。",
                  foreground="#ad4516",wraplength=1000).pack(anchor="w")
        ttk.Label(readouts, textvariable=self.evidence_text,
                  foreground="#a15311", wraplength=900).pack(anchor="w")

        experiment = ttk.LabelFrame(area, text="③ 采集舵机电流与压力的对应曲线", padding=10)
        experiment.pack(fill="both", expand=True)
        controls = ttk.Frame(experiment)
        controls.pack(fill="x")
        ttk.Label(controls, text="实验名称").pack(side="left")
        ttk.Entry(controls, textvariable=self.trial, width=16).pack(side="left", padx=(5, 12))
        self.start_btn = ttk.Button(controls, text="② 开始标定采集（先归零）", command=self.start_record)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(controls, text="完成并自动导出", command=self.stop_record)
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(controls, text="重新导出全部 CSV", command=self.export_csv).pack(side="left", padx=5)
        ttk.Label(controls, textvariable=self.points_text).pack(side="left", padx=8)
        ttk.Checkbutton(experiment, text="手动位置小步闭合也作为训练样本（仅标记；不发电机指令）",
                        variable=self.manual_closing).pack(anchor="w")
        step_area = ttk.LabelFrame(experiment, text="手动逐步标定 · 每次点击仅闭合1°", padding=8)
        step_area.pack(fill="x",pady=6)
        ttk.Checkbutton(step_area,text="已确认独立硬件急停、闭合方向、机械限位和安全距离",
                        variable=self.confirm_mechanism).pack(anchor="w")
        self.step_btn=ttk.Button(step_area,text="闭合 1°（单次）",command=self.step_one_degree)
        self.step_btn.pack(side="left",pady=6,padx=(0,12))
        self.finish_btn=ttk.Button(step_area,text="完成记录并自动导出",command=self.stop_record)
        self.finish_btn.pack(side="left",pady=6)
        ttk.Label(step_area,textvariable=self.step_status_text,foreground="#844923",
                  wraplength=560).pack(side="left",padx=12)
        ttk.Label(experiment,text="每一步必须收到稳定到位反馈。理论受力接近标称1kg时拒绝继续步进，"
                  "可在任意时刻完成记录；不可仅凭软件停机代替独立断电。",
                  foreground="#a33317",wraplength=920).pack(anchor="w")
        model_box = ttk.LabelFrame(experiment, text="④ 采集一次 → 保存离线估算模型（仅实验）", padding=6)
        model_box.pack(fill="x", pady=4)
        buttons = ttk.Frame(model_box)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="从本次数据生成并保存模型", command=self.make_model).pack(side="left")
        ttk.Button(buttons, text="重载已存模型", command=self._load_model).pack(side="left", padx=6)
        ttk.Label(model_box, textvariable=self.model_message, foreground="#815e12",
                  wraplength=830).pack(anchor="w", pady=2)
        gaps = ttk.Frame(model_box)
        gaps.pack(fill="x")
        for label, var in (("角度A°",self.gap_a_angle),("实测开口A mm",self.gap_a_mm),
                           ("角度B°",self.gap_b_angle),("实测开口B mm",self.gap_b_mm)):
            ttk.Label(gaps, text=label).pack(side="left", padx=(4,0))
            ttk.Entry(gaps, textvariable=var, width=7).pack(side="left", padx=(2,4))
        ttk.Label(model_box, text="毫米值需要人工测量；静止保持、未覆盖电流/角度不显示受力预测。",
                  foreground="#815e12").pack(anchor="w")

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
            ha8_port = self.app.port_var.get().strip() if self.app.transport.is_open else ""
            choices = [p for p in ports if p.lower() != ha8_port.lower()]
            self.pressure_port.set(choices[0] if choices else "")

    def toggle_connection(self):
        if self.link.is_open:
            self.disconnect()
            return
        try:
            self.connect_port(self.pressure_port.get().strip())
        except Exception as exc:
            messagebox.showerror("压力模块连接失败", str(exc))

    def connect_port(self, port: str):
        """Shared entry for auto identification and manual port selection."""
        port = str(port).strip()
        if not port:
            raise ValueError("压力传感器需要单独的 USB-TTL COM 口")
        ha8_port = self.app.port_var.get().strip()
        if (self.app.transport.is_open and port.casefold()==ha8_port.casefold()):
            raise ValueError("压力模块不能占用已连接 HA8 的串口")
        if self.link.is_open:
            raise RuntimeError("压力串口已经连接，请先断开再切换")
        try:
            self.link.open(port)
        except Exception:
            self.connection_text.set(f"连接 {port} 失败")
            raise
        self.pressure_port.set(port)
        self.sensor = PressureEvidence(rf_kohm=158)
        self.recorder.stop()
        self.capture = None
        self.step_state.clear()
        self._previous_ha8 = None
        self.zero_text.set("⚠ 新连接：尚未归零；确认夹爪松开且压力片无载")
        self.connection_text.set(f"已连接 {port}，等待无载数据")
        self.conn_btn.configure(text="断开压力模块")
        self.evidence_text.set("必须先无载归零，才能开始本次标定；断线重连后旧零点无效")
        self._update_zero_controls()

    def disconnect(self):
        if self.recorder.active:
            self.stop_record()
        self._previous_ha8 = None
        self.recorder.stop()
        self.step_state.clear()
        self.link.close()
        self.sensor = PressureEvidence(rf_kohm=158)
        self.zero_text.set("⚠ 压力连接已断开；下次连接后必须重新无载归零")
        self.connection_text.set("未连接压力模块")
        self.conn_btn.configure(text="连接压力模块")
        self.adc_text.set("— ADC")
        self.pressure_text.set("—")
        self.live_force_text.set("已断开 · -- gf")
        self.live_voltage_text.set("ADC -- · -- mV")
        self.evidence_text.set("压力模块已断开；本次标定已停止，重新连接后需归零")
        self._update_zero_controls()

    def _thread_frame(self, frame, at):
        self.app.ui_queue.put(("pressure_frame", (frame, at)))

    def _thread_error(self, exc):
        self.app.ui_queue.put(("pressure_error", str(exc)))

    def on_pressure_frame(self, frame, at):
        if not self.link.is_open:
            return
        self.sensor.add(frame, at)
        raw_force = None
        if self.sensor.zero_adc is not None and frame.status == 0 and frame.adc < 4085:
            raw_force = estimate_circuit_force_g(frame.adc, 158, self.sensor.zero_adc)
        if self.capture is not None and self.capture.active:
            try:
                self.capture.pressure(frame, at, raw_force)
            except OverflowError as exc:
                self._end_capture_due_to_error(str(exc))
        if frame.sequence % 10 == 0:
            self.live_voltage_text.set(f"ADC {frame.adc} · {frame.voltage_mv} mV")
            if frame.status or frame.adc >= 4085:
                self.live_force_text.set("数据异常/饱和")
            elif raw_force is None:
                self.live_force_text.set("未校零/超范围")
            else:
                note = " 超标称量程" if raw_force > 1000 else ""
                self.live_force_text.set(f"≈{raw_force:.0f} gf / {raw_force*0.00980665:.2f} N{note}")
        # Bad status flags are never accepted as force or contact evidence.
        if frame.status:
            self.connection_text.set(f"压力采集异常 flags=0x{frame.status:02X}")
            return
        if frame.adc >= 4085:
            self.connection_text.set("压力 ADC 接近饱和，数据不可靠")
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
        # A zero captured after the trial begins would silently relabel its
        # samples. Never combine rows with different zero baselines.
        if self.recorder.active:
            messagebox.showwarning("不能重新归零", "请先结束本次标定采集；运行中禁止更改零点")
            return
        if not self.link.is_open:
            messagebox.showwarning("压力未连接", "请先连接 STM32F103 压力模块")
            return
        if self.recorder.rows and not messagebox.askyesno(
                "重新归零将清空旧实验",
                "当前还有上一轮实验数据。重新归零将清空未导出的数据，建议先导出 CSV。是否继续？"):
            return
        try:
            zero = self.sensor.capture_zero()
        except ValueError as exc:
            messagebox.showwarning("无法采零点", str(exc))
            return
        # Zero accepted; discard all samples from the previous zero.
        if self.recorder.rows:
            self.recorder.rows.clear()
            self.points_text.set("零点已更新；上一轮采样已清空")
            self._draw()
        self.capture = None
        self.zero_text.set(
            f"✓ 已无载归零：ADC {zero:.1f}，噪声≈{self.sensor.zero_noise_adc:.1f} ADC")
        self.evidence_text.set("零点已采集；保持无载稳定，再开始标定采集")
        self._update_zero_controls()

    def check_contact(self):
        if not self.link.is_open:
            self.evidence_text.set("压力传感器未连接，无法交叉验证")
            return
        label, delta = self.sensor.evidence()
        suffix = "" if delta is None else f"，相对零点 {delta:+.0f} ADC"
        self.evidence_text.set(label+suffix)

    def on_ha8_monitor(self, servo_id, fields):
        now = time.monotonic()
        angle = float(fields["angle_deg"])
        previous = self._previous_ha8
        self._previous_ha8 = (servo_id, now, angle)
        self.last_ha8 = (now, servo_id, dict(fields))
        if self.capture is not None and self.capture.active:
            try:
                self.capture.ha8(servo_id, fields, now,
                                 self.app.auto_grip_panel.phase or "idle",
                                 self.step_state.target)
            except OverflowError as exc:
                self._end_capture_due_to_error(str(exc))
        if self.step_state.pending and self.capture is not None and self.capture.active:
            self._observe_step(servo_id, angle, fields, now)
        closing_motion = observed_closing_motion(previous, servo_id, now, angle)
        phase = self.app.auto_grip_panel.phase or "idle"
        if phase == "gripping" and not closing_motion:
            phase = "idle"  # 运动停止时不能把静态电流作为力标定样本
        elif self.manual_closing.get() and phase == "idle" and closing_motion:
            phase = "gripping"
        if self.model is not None:
            force = self.model.predict(float(fields["current_ma"])/1000,
                                       angle, phase, int(fields["status"]))
            gap = self.model.gap_mm(float(fields["angle_deg"]))
            if force is None:
                text = "离线估算：静止/未覆盖的工况，无法估计"
            else:
                distance = "，开口≈%.1f mm" % gap if gap is not None else "，开口毫米未标定"
                text = "单指尖≈%.0f gf%s（未验证）" % (force, distance)
            self.model_message.set(text)
            if hasattr(self.app.auto_grip_panel, "model_force_text"):
                self.app.auto_grip_panel.model_force_text.set(text)

        if self.recorder.add(now, servo_id, fields, self.sensor, phase):
            if len(self.recorder.rows) % 10 == 0:
                self.points_text.set(f"已配对 {len(self.recorder.rows)} 点")

    def on_grip_start(self):
        self.evidence_text.set("抓取动作已开始；压力仅记录，不参与控制")

    def on_grip_end(self, reason, confirmed_motion_stop=True):
        if not self.link.is_open:
            self.evidence_text.set("压力模块未连接；无法验证本次接触")
            return
        if not confirmed_motion_stop:
            self.evidence_text.set("舵机停止未确认；压力不能证明安全抓稳")
            return
        label, delta = self.sensor.evidence()
        tail = "" if delta is None else f"（ΔADC={delta:+.0f}）"
        self.evidence_text.set(f"HA8：{reason}；FSR：{label}{tail}")

    def start_record(self):
        if self.recorder.active:
            return
        if not self.link.is_open:
            messagebox.showwarning("无法采集", "请先连接 STM32F103 压力模块")
            return
        ok, reason = self.sensor.ready_for_trial()
        if not ok:
            messagebox.showwarning("请先完成无载归零", reason)
            self.evidence_text.set(reason)
            return
        if not self.app.transport.is_open or not self.app.monitor_running:
            messagebox.showwarning("无法采集", "请先连接 HA8 舵机，让主界面获取实时电流")
            return
        if self.recorder.rows and not messagebox.askyesno(
                "覆盖当前实验", "开始新实验会清空尚未导出的曲线数据，确定继续？"):
            return
        if self.app.auto_grip_panel.phase or self.app.auto_grip_panel.estop_latched:
            messagebox.showwarning("禁止开始", "请先结束其他夹爪运动与软件停机锁定")
            return
        self.recorder.start(self.trial.get())
        self.step_state.clear()
        self.manual_closing.set(True)
        self.capture = CalibrationRun(self.trial.get(), self.sensor.zero_adc, self.app.servo_id())
        self.capture.event("start",zero_adc=self.sensor.zero_adc)
        self.points_text.set("已开始：独立记录压力全部帧、HA8监控和每次步进")
        self.evidence_text.set("本轮已锁定无载零点；采集进行中不允许重新归零")
        self._update_zero_controls()

    def stop_record(self):
        if self.step_state.pending:
            self._stop_step("用户结束本次实验")
        if self.capture is not None and self.capture.active:
            self.capture.event("finish_by_operator")
            self.capture.stop()
        self.recorder.stop()
        if self.capture is None:
            self.points_text.set("尚未开始实验")
            self._update_zero_controls()
            return
        try:
            folder = self.capture.export(self.recorder.rows)
            self.points_text.set(f"已导出 {folder}：压力 {len(self.capture.pressure_rows)}，"
                                 f"HA8 {len(self.capture.ha8_rows)}，配对 {len(self.recorder.rows)}")
            messagebox.showinfo("已保存全部原始数据",
                f"CSV 文件夹：\n{folder}\n\n01_pressure_f103.csv：压力每帧\n"
                "02_ha8_servo.csv：电流/角度监控\n03_step_events.csv：点击操作\n"
                "04_paired_curve.csv：同步曲线\nmetadata.json：实验说明")
        except (OSError, ValueError) as exc:
            self.points_text.set("保存失败，数据仍在内存；检查磁盘后点击重新导出")
            messagebox.showerror("导出失败",str(exc))
        self._update_zero_controls()
        self._draw()

    def _end_capture_due_to_error(self,reason):
        if self.capture is None:return
        self.capture.stop()
        self.recorder.stop()
        if self.step_state.pending:
            self._stop_step("数据缓存异常，已拒绝继续运动")
        self.step_status_text.set(f"记录中断：{reason}；请完成导出")
        self._update_zero_controls()

    def _stop_step(self,reason):
        if not self.step_state.pending:return
        target = self.step_state.target
        self.step_state.clear()
        if self.capture is not None and self.capture.active:
            self.capture.event("step_stop",reason=reason,target_deg=target)
        try:
            self.app.send_ha8(HA8Protocol.stop(self.app.servo_id(),STOP_HOLD,300),
                              "实验中止步进（软件保持）",owner="pressure_calibration")
        except Exception as exc:
            self.step_status_text.set(f"STOP发送失败：{exc}。使用独立硬件急停")
            return
        self.step_status_text.set(reason+"；已发软件停止，仍需确认实际停机")

    def _observe_step(self,servo_id,angle,fields,now):
        if self.capture is None or servo_id != self.capture.servo_id:return
        state=self.step_state.observe(angle,now,fields["status"])
        if state=="complete":
            self.capture.event("step_arrived",at=now,angle_deg=angle)
            self.step_status_text.set(f"反馈已到位 {angle:.1f}°；可再点击一次")
        elif state in ("fault","timeout"):
            self._stop_step(f"目标未正常完成（{state}）")
        elif state=="moving":
            self.step_status_text.set(f"正在前往 {self.step_state.target:.1f}°，请勿重复点击")

    def step_one_degree(self):
        try:
            if not self.recorder.active or self.capture is None or not self.capture.active:
                raise RuntimeError("先压力归零，再开始本轮标定采集")
            if not self.confirm_mechanism.get():
                raise RuntimeError("先确认硬件急停、闭合方向及安全夹爪限位")
            if self.step_state.pending:
                raise RuntimeError("前一次1°运动还未反馈到位")
            last=self.sensor.latest() if self.link.is_open else None
            if last is None:
                raise RuntimeError("压力传感器串口异常或数据过期，禁止动作")
            force=self.sensor.theoretical_force_g(last.adc)
            if force is None or force>=900:
                raise RuntimeError("传感器接近标称1kg或估算无效，禁止继续步进；请完成记录")
            panel=self.app.auto_grip_panel
            sid=panel._preflight()
            if sid!=self.capture.servo_id or self.last_ha8 is None:
                raise RuntimeError("HA8 监控舵机与实验舵机不一致")
            t,read_sid,fields=self.last_ha8
            if read_sid!=sid or time.monotonic()-t>0.4 or int(fields["status"])!=0:
                raise RuntimeError("HA8反馈已超时或状态异常")
            lo,hi,vel,power,hold=panel._parameters()
            angle=float(fields["angle_deg"])
            target=round(angle-1.0,1)
            if not lo<=angle<=hi or target<lo+0.3:
                raise RuntimeError(f"已接近经过实机确认的最小角度 {lo:g}°")
            if power<=0:raise RuntimeError("功率上限必须大于0")
            velocity=min(5.0,vel)
            used_power=min(1500,power)
            frame=HA8Protocol.move(sid,target,multiturn=True,mode="velocity",
                                   velocity_dps=velocity,t_acc_ms=200,t_dec_ms=200,
                                   power_mw=used_power)
            self.app.send_ha8(frame,f"人工逐步闭合 1° → {target:.1f}°",
                              owner="pressure_calibration")
            now=time.monotonic()
            self.step_state.begin(target,now)
            self.capture.event("step_command",at=now,servo_id=sid,angle_before_deg=angle,
                               target_deg=target,velocity_dps=velocity,power_mW=used_power,
                               force_gf_theoretical=force)
            self.step_status_text.set(f"已发送1° → {target:.1f}°；等待稳定到位")
        except (ValueError,TypeError,RuntimeError) as exc:
            self.step_status_text.set(str(exc))
            messagebox.showwarning("1° 步进被拒绝",str(exc))
        self._update_zero_controls()


    def _load_model(self):
        try:
            model = ForceMap.load()
        except FileNotFoundError:
            self.model = None
            self.model_message.set("离线模型：尚未生成")
            return
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.model = None
            self.model_message.set(f"无效模型：{exc}")
            return
        self.model = model
        self.model_message.set(f"载入 {len(model.points)} 条样本：仅闭合期间、原工况范围内估算")

    def make_model(self):
        if self.recorder.active:
            messagebox.showwarning("先结束采集", "先结束数据采集再建立模型")
            return
        try:
            model = ForceMap.train(self.recorder.rows)
            gap_values = [var.get().strip() for var in
                          (self.gap_a_angle, self.gap_a_mm, self.gap_b_angle, self.gap_b_mm)]
            if any(gap_values):
                if not all(gap_values):
                    raise ValueError("夹口标定需填写两组完整的角度/开口毫米")
                model = model.with_gaps([
                    {"angle_deg":float(gap_values[0]),"gap_mm":float(gap_values[1])},
                    {"angle_deg":float(gap_values[2]),"gap_mm":float(gap_values[3])}])
            if DEFAULT_PATH.exists() and not messagebox.askyesno("覆盖模型",
                    "将覆盖此前本机模型。确定是同一夹爪装配和受力工况？"):
                return
            model.save()
        except (ValueError, OSError, TypeError) as exc:
            messagebox.showerror("标定未完成", str(exc))
            return
        self.model = model
        self.model_message.set(f"保存 {len(model.points)} 条样本；拆除压力传感器后仅用于未验证的闭合阶段参考")

    def export_csv(self):
        if self.recorder.active:
            messagebox.showwarning("尚未完成记录", "点击完成记录后才会自动导出")
            return
        if self.capture is None:
            messagebox.showinfo("无数据","尚无本次实验")
            return
        try:
            folder=self.capture.export(self.recorder.rows)
            messagebox.showinfo("已导出全部 CSV",f"实验目录：{folder}")
        except (OSError,ValueError) as exc:
            messagebox.showerror("导出失败",str(exc))

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

    def _update_zero_controls(self):
        if not hasattr(self, "start_btn"):
            return
        self.zero_btn.configure(state="normal" if self.link.is_open and not self.recorder.active
                                else "disabled")
        ready, _ = self.sensor.ready_for_trial()
        can_start = (self.link.is_open and ready and self.app.transport.is_open
                     and self.app.monitor_running and not self.recorder.active)
        self.start_btn.configure(state="normal" if can_start else "disabled")
        running=self.recorder.active and self.capture is not None and self.capture.active
        if hasattr(self,"step_btn"):
            self.step_btn.configure(state="normal" if running and not self.step_state.pending
                                    and self.confirm_mechanism.get() else "disabled")
        if hasattr(self,"finish_btn"):
            self.finish_btn.configure(state="normal" if running else "disabled")

    def _tick(self):
        if self.step_state.pending and self.step_state.sent_at is not None and (
                time.monotonic()-self.step_state.sent_at>3.0):
            self._stop_step("1°目标反馈超时")
        self._update_zero_controls()
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
