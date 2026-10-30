# HA8 智能夹爪｜统一 Windows 上位机（V3.5-beta）

**只运行一个上位机：`HA8_UpperComputer.py`。** 它同时负责 HA8-U35H-M 蜗轮蜗杆夹爪、STM32F103 薄膜压力采集，以及“舵机电流—压力响应”验证实验。

## 使用入口

```powershell
git clone https://github.com/hejkhk/ha8-can-gripper.git
cd ha8-can-gripper
py -3 -m pip install -r requirements.txt
py -3 HA8_UpperComputer.py
```

当前推荐 Windows + Python 3.10 及以上，两个串口独立：

```text
Windows 单窗口 HA8 智能夹爪
 ├─ USB COM A → 官方 HA8 串口板 → HA8-U35H-M 舵机 → 蜗轮蜗杆夹爪
 └─ USB COM B ← USB-TTL ← STM32F103 ← AO 电压转换模块 ← IMS003 薄膜传感器
```

两路 UART 都是 115200 8N1，但协议**完全不同**：

- **F103 压力通道：**上电持续发送 ASCII `P,seq,mcu_ms,adc,mv,flags\r\n`。程序被动读取，要求两个连续有效序号才识别为压力模块；从不对它发送 HA8 命令。
- **HA8 控制通道：**正常不主动播报数据，程序只在用户点击自动识别按钮之后，对安静的串口发送**只读 Ping**，要求完整的 HA8 帧头、长度、校验和、命令及匹配舵机 ID 的响应才认定是 HA8。
- **未知或被占用的串口不会被猜测为某种设备。** 识别出多个同类 COM 也不会任意选择；可以在界面手动指定。请在设备已接好电、无人控制夹爪时运行自动识别。Ping 不是运动指令，但串口驱动本身可能在打开时切换 DTR/RTS。

## 常用操作（单窗口）

1. 将两路 USB 接入电脑，打开主程序，按 **「自动识别并连接两设备」**。成功后会显示两个 COM 号；若 HA8 舵机 ID 不是默认 0，先点右上角「显示高级调试」，将正确的舵机 ID 填进去，再重新识别。
2. 在「夹爪控制」页，确认 HA8 反馈电流、角度正常。填写**已实机验证的**抓取最小角度与张开最大角度，再进行低速抓取/张开。
3. 在同一窗口「压力验证 / 曲线」页，确认 STM32 压力数据正常；传感器完全**无载**后点击「无负载采集零点」。
4. 点「开始采集」，切回「夹爪控制」进行一次夹取测试，停止后看压力接触证据；结束采集，查看以电流 (A) 为横轴、压力增量 (ΔADC) 或未标定理论 gf 为纵轴的曲线，可导出 CSV。
5. 按右上角「显示高级调试」查看完整协议测试、参数、夹持算法、数据监控和串口日志等旧功能。平常无需打开它们。

**重要安全边界：**薄膜压力只用于**观察/曲线/辅助验证**，不参与舵机运动或安全急停。检测到持续受压不能证明防滑、两指均抓稳或能安全搬运。软件“立即停止”依赖串口，不能代替独立硬件断电急停。厂家曲线 + 假定反馈阻值 Rf=158kΩ 只是理论估计，尚未实测证实其夹紧法向力精度。

## 工程目录

```text
HA8_UpperComputer.py           # 唯一推荐的 Windows UI 入口
ha8_protocol.py                # HA8 原生协议
ha8_serial.py                  # 官方 HA8 串口板
serial_device_discovery.py     # 自动识别两个 COM（协议验证，非 COM 数字猜测）
auto_grip_panel.py             # 抓取、张开、软件停止
grip_estimator.py / grip_panel.py  # HA8 电流检测与实验算法
pressure_lab_panel.py          # 统一 UI 内的压力验证与电流-压力曲线
pressure_validation.py         # 压力帧、零点、证据与 CSV 配对
extensions/gripper-pressure-f103/
  Core/ MDK-ARM/ *.ioc         # STM32F103 源码、CubeMX 与 Keil 工程
  PC_UpperComputer/protocol.py # F103 协议及原厂曲线唯一数据源
  PC_UpperComputer/gripper_monitor.py # 旧独立压力 GUI，保留供维护/比对
  docs/ tests/                 # 压力扩展原始说明与单元测试
legacy/                        # 过去 USB-CAN、F103-CAN 桥接实现，不被主程序使用
tests/                         # 单元测试、伪串口和 Tk 虚拟界面测试
doc/                           # 当前指南、交接文档、历史参考文档
```

**仓库目录约定：**根目录仅放运行中会用到的 HA8/融合代码，硬件固件保存在 `extensions/`，废弃历史通信驱动保存在 `legacy/`。不删除历史文件，也不把 CubeMX 编译生成的 HAL 驱动、实验 CSV、校准 JSON、用户本地 COM 参数或日志提交 Git。

## 验证与交接

```powershell
py -3 -m unittest discover -s tests -v
py -3 -m unittest discover -s extensions/gripper-pressure-f103/tests -v
```

GitHub Actions 在 Linux + Xvfb 中运行两个测试集与 Python 语法检查；这不证明已完成双实体 COM、夹爪运动和压力精度的 Windows 实机验收。

- [**当前融合架构和一键 COM 识别**](doc/UNIFIED_APP_AND_COM_DISCOVERY_2026-10-30.md)
- [电流—薄膜压力交叉验证及 CSV](doc/PRESSURE_HA8_INTEGRATION_2026-10-30.md)
- [F103 压力固件与原厂曲线交接](extensions/gripper-pressure-f103/docs/PROJECT_HANDOFF_2026-10-30.md)
- [HA8 V3.2 历史交接](doc/PROJECT_HANDOFF_2026-10-16.md)
- [文档总索引](doc/README.md)
