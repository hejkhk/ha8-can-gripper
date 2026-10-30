# 夹爪薄膜压力监测扩展 | STM32F103C8T6 + Windows（V3）

> **交接入口：**[完整项目交接文档（2026-10-30）](docs/PROJECT_HANDOFF_2026-10-30.md)  
> **状态：**ADC/USB-TTL/上位机压力变化链路已有用户实物观察；158kΩ 理论受力**尚未**完成标准法向力验证。

## 1. 项目定位

本项目是 `hejkhk/ha8-can-gripper` 中的**独立压力监测模块**，不直接控制 HA8 舵机、不执行压力闭环、不具备安全停机功能。原 HA8 上位机依旧通过**官方 USB 串口板**控制舵机；本模块通过单独 F103/USB-TTL 串口监测薄膜受力。

```text
IMS003-C10A-1KG (FSR)
       ↓ 两线
5V 线性电压转换模块 (AO)
       ↓ PA1 / ADC1_IN1
STM32F103C8T6 (16次平均 + EMA + 10ms/帧)
       ↓ PA9 USART1_TX → USB-TTL RXD, 共地，115200 8N1
Windows PC：Python/Tkinter 上位机
```

**连接前务必先用万用表确认 AO 不超过 F103 允许的 ADC 输入电压；USB-TTL 信号使用 3.3V TTL，高低电平与主控兼容。** 当前 DO 未接。

## 2. Windows 快速开始（现有 MCU 固件无需更新）

```powershell
git clone https://github.com/hejkhk/ha8-can-gripper.git
cd ha8-can-gripper\extensions\gripper-pressure-f103
py -3 -m pip install -r PC_UpperComputer\requirements.txt
py -3 PC_UpperComputer\gripper_monitor.py
```

1. 在 GUI 中选择实际 USB-TTL COM 端口并连接，查看 ADC / mV / 实时曲线；先确认按压会使电压增加。
2. 选择 **“免砝码 · 电路”**，确认 `AO-RES 实际电阻 Rf` 输入是 **158**（单位 kΩ）。
3. **完全卸载压力**并保持稳定至少 1s，再点击“无负载采集零点”。
4. 点击“保存当前标定/模式”；以后会从本地 `calibration.json` 恢复。**旧配置会覆盖软件默认 158**，如有旧值需手动更新并重新保存。
5. 实时显示**理论估算**克力/N、60s 曲线、峰值并可导出 CSV。

## 3. 受力换算与精度限制

- 转换模块手册公式：`Uo = 0.1 * (1 + Rf/Rx)`，`G = (Uo - Uzero) / (0.1 * Rf)`；根据传感器厂家第 2 页的 **电导—受力表**作分段插值。
- V3 默认 `Rf=158kΩ` 是按当前使用要求配置的**假定反馈阻值**，**并非已实测证实**；应断电按手册测 R2 未焊焊盘核对真实反馈阻值。
- 厂家首页标称测力量程 1kg、最小测力约 50g；虽然第二页有 2kg 参考点，但超出标称部分无精度/寿命保证。
- 理论在 Rf=158kΩ 时，2kg 对应 AO≈3.26V，已非常接近标称 3.3V 上限，实际可能提前饱和。只采零点能校正偏置，**不能替代精度验收**。
- 软件提供 **免砝码电路 / 单点参考 / 多点实测** 三种模式；无需砝码时只能称“估计”，不是“精准夹持力”。

详细公式：[AO 电路模型](docs/ao_converter_v3.md)；完整状态与接手指南：[项目交接文档](docs/PROJECT_HANDOFF_2026-10-30.md)。

## 4. 主要文件

| 文件 | 功能 |
|---|---|
| `Core/Src/main.c` | ADC1 PA1、上电校准、16次采样平均、EMA、USART1 每约 10ms 发一帧 |
| `Gripper_Pressure_F103.ioc` | CubeMX 外设和采样时间 239.5 周期 |
| `MDK-ARM/Gripper_Pressure_F103.uvprojx` | Keil MDK 工程配置 |
| `PC_UpperComputer/gripper_monitor.py` | Windows GUI、串口、图表、峰值、零点和 CSV |
| `PC_UpperComputer/protocol.py` | 串口帧解析、转换模块计算、厂家曲线插值 |
| `tests/test_protocol.py` | 公式、边界条件、帧和插值的单元测试 |
| `docs/PROJECT_HANDOFF_2026-10-30.md` | **维护/交接所需的完整项目现状** |

串口协议：`P,seq,mcu_ms,adc,mv,flags\r\n`，115200/8N1；flags：1 ADC失败、2 ADC接近上限、4 上电校准失败。

## 5. 开发与测试

在模块目录运行：

```powershell
py -3 -m py_compile PC_UpperComputer\protocol.py PC_UpperComputer\gripper_monitor.py tests\test_protocol.py
py -3 -m unittest discover -s tests -v
```

重新生成或编译 STM32 时，请先安装 STM32CubeF1 HAL/CMSIS 驱动依赖（GitHub 不包含 `Drivers/`）并备份代码，防止重新生成覆盖 USER CODE；详见交接文档。

**重要：**此压力估算没有经过已知法向受力标定，不能充当安全相关的夹爪停止/防夹保护，也不能用物体质量直接等同于实际夹持力。
