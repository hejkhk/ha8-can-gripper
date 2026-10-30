# F103 薄膜压力采集固件（由统一 HA8 GUI 管理）

**唯一 Windows 上位机：仓库根目录 [`HA8_UpperComputer.py`](../../HA8_UpperComputer.py)。** 这里不再保留第二套独立压力上位机。历史版本可从 Git 历史恢复。

## 当前结构

- `Gripper_Pressure_F103.ioc` / `Core/` / `MDK-ARM/`：STM32F103C8T6 固件、CubeMX/Keil 项目。
- `tests/test_protocol.py`：F103 串口协议和厂家曲线回归测试，导入根目录 [`pressure_protocol.py`](../../pressure_protocol.py)。
- `docs/`：V1/V2/V3 历史说明、2026-10-30 交接（**包含旧路径，作为历史资料**）。

## 当前通信

IMS003-C10A-1KG FSR → 5V AO 运放转换模块 → F103 PA1 ADC1，F103 PA9 USART1_TX → USB-TTL RXD → Windows 主 GUI，115200/8N1；约100帧/s、帧格式 `P,seq,mcu_ms,adc,mv,flags`。实际输出需确保不会超过 STM32 ADC 允许输入电压。

原厂传感器标称1kg，Rf=158kΩ 是目前软件的计算假定值。电脑通过 `pressure_protocol.py` 换算理论克力，不代表实测精度。F103 固件依赖 STM32CubeF1 HAL/CMSIS 驱动，仓库未包含厂商完整 `Drivers/`，重新编译须先生成/安装依赖。

**当前任务**：传感器只在训练会话使用，一旦保存本机模型，可以移除传感器但只得到舵机运动期**经验估算**，不可用于安全停机或在静止蜗杆自锁时估算真实夹力。

[最新项目标定交接](../../doc/ONE_TIME_FORCE_CALIBRATION_2026-10-30.md) · [F103 固件历史交接](docs/PROJECT_HANDOFF_2026-10-30.md)
