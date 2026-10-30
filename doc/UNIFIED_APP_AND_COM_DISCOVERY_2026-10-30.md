# HA8 夹爪统一 UI 与双串口协议识别（2026-10-30）

## 自动识别协议

- **压力 F103：**上电主动发送 `P,seq,mcu_ms,adc,mv,flags\r\n`，程序被动读取至少两个序列连续、MCU 时间递增且字段有效的 ASCII 帧，才将此端口识别成压力模块。不会发送 HA8 命令给压力模块。
- **HA8 官方 USB 转串口板：**通常不主动上报。点击「自动识别并连接两设备」后，程序先监听压力帧，**仅对没有其他数据的端口**发送当前舵机 ID 的只读 HA8 Ping。收到有效 `05 1C 01 01 ID CHECKSUM`，并校验帧头、命令、长度、校验和、ID 后才认可。
- 后台工作线程执行探测；发现角色后关闭探测串口，由统一窗口分别打开 HA8 和 F103 通信服务。检测过程中不会发送运动、标定或 STOP 指令。

```text
                  HA8_UpperComputer.py（唯一日常入口）
                     |            |
               HA8 串口       F103 压力串口
                     |            |
              ha8_serial.py   pressure_validation.py
                     |            |
              ha8_protocol.py 压力 extensions/.../protocol.py
                     |            |
             auto_grip_panel.py pressure_lab_panel.py
                     \            /
                     配对实验数据和 CSV
```

## 使用与异常

1. 在 Windows 项目根目录安装 `requirements.txt` 并启动 `python HA8_UpperComputer.py`。
2. 插入两套 USB 设备，在设备无运动、无其他软件占用 COM 时点击「自动识别并连接两设备」。
3. 找到唯一 HA8 和唯一 F103 时自动连接；串口繁忙、设备未上电、识别重复或响应无效时不强行选择。手动选择仍保留。
4. 舵机 ID 并非 0 时，请先打开「显示高级调试」修改 ID 后再识别；自动识别**不会扫描所有 254 个 ID**。
5. 在「压力验证 / 曲线」完成无载零点采集；在「夹爪控制」设置实际校准过的限位后，才进行低速夹持实验。

## 安全与工程限制

**该识别逻辑只通过模拟串口及虚拟 Tk 窗口测试，未用用户当前 Windows 两套实体串口验收。** 打开 USB-TTL 时，部分驱动可能切换 DTR/RTS 并导致 MCU 复位；若 F103 重启时间较长，第一次识别可能失败，请重新扫描或手动选择。程序不会凭 COM 序号、USB 芯片描述等推断物理角色。

压力仍**只用于独立验证**、不参与 HA8 运动/急停。持续受压不证明防滑或可安全提物；Rf=158kΩ 理论值不等于实际法向力标定。软件停止不是安全硬件急停。

## 仓库整理

- 根目录：运行中使用的 HA8、压力和统一 GUI 模块。
- `extensions/gripper-pressure-f103/`：F103 固件、CubeMX/Keil 工程、厂家原始曲线逻辑和单独 GUI（仅供历史维护与校验，不再是推荐日常入口）。
- `legacy/`：旧 USB-CAN / F103 UART-CAN 代码，与当前 F103 压力项目**不是同一用途**。
- `doc/`：当前与旧方案文档。旧文档不代表最新接线。
- `tests/`：GUI、协议、模拟双串口、数据配对与算法离线测试。

## 验证

```powershell
py -3 -m py_compile HA8_UpperComputer.py ha8_serial.py ha8_protocol.py auto_grip_panel.py pressure_validation.py pressure_lab_panel.py serial_device_discovery.py
py -3 -m unittest discover -s tests -v
py -3 -m unittest discover -s extensions/gripper-pressure-f103/tests -v
```

所有新开发直接提交 `main`，并记录 Commit、测试及未实机验证范围。
