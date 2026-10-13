# STM32F103C8T6 串口—CAN 透明桥接模式

## 两种模式的差异

| 设备 | 上位机模式 | PC COM 数据格式 |
|---|---|---|
| 原 USB-CAN 适配器 | USB-CAN CDC | USB-CAN 专用 20 字节 CAN 记录（驱动负责封装） |
| USB-TTL + STM32F103C8T6 | STM32F103 串口桥接 | **HA8 原始帧**，不带 CAN ID、DLC 或封包头 |

统一的舵机协议：请求 `12 4C CMD LEN ... CHECKSUM`，回应 `05 1C CMD LEN ... CHECKSUM`。
统一的 CAN 设定：**1 Mbps，11 位标准数据帧**，命令 `0x6A0`，反馈 `0x6A1`。CTS100M 的 CAN→UART 接收滤波设为只收标准帧 `0x6A0`；CTS UART→CAN 发送 ID 为 `0x6A1`。

## 桥接接线

```text
Windows PC
  └─ USB-TTL (115200 8N1)
       TXD -> F103 PA10 / USART1_RX
       RXD <- F103 PA9  / USART1_TX
       GND --- F103 GND
                └─ F103 CAN1 (PA12 TX / PA11 RX) -> CAN 收发器
                     CANH / CANL -> CTS100M (1 Mbps)
                                         UART TXD/RXD -> 舵机扩展板 -> HA8
```

确认 USB-TTL 与 F103 UART 引脚的逻辑电平兼容；**不可将 RS232 ±12 V 电平直接接 STM32 引脚**。STM32 CAN TX/RX 需要配套 CAN 收发器才能连接物理 CANH/CANL。24V→12V 给舵机独立供电，CTS 裸板按资料使用 3.3V。

## F103 固件必须匹配的规则

此模式基于之前的 `main_gripper_bridge_1M_6A0_6A1.c` 透明桥接逻辑：

1. PC 经 F103 USART1 115200 8N1 发入一串原始 HA8 指令字节。
2. F103 每 8 字节切一帧标准 CAN `0x6A0`，最后不足 8 字节的尾帧需按 UART 空闲约 2ms 刷新；不能插入其他指令。
3. F103 接收 `0x6A1` CAN 数据帧，把 CAN DATA 按顺序送回 USART1 TX。
4. MCU 不解析 HA8、不增加帧头，也不向上位机回送自身调试文本。
5. F103 CAN 位速率和 CTS 均为 1 Mbps；总线两端正确加 120Ω，断电测 CANH-CANL 两端整体常约 60Ω。
6. 上位机对 F103 的串口流 **无法还原真实的 CAN 帧边界、CAN ID、DLC**，CAN 调试页只可当原始数据监视器。

**重要**：历史 F103 固件有过 `0x123` 或“接收所有 CAN 帧”调试版本。必须核对最终烧录固件 **固定 TX `0x6A0`，并且仅将 RX `0x6A1` 回传**；否则 CTS 的滤波或上位机解析将受影响。上面引用的历史源码是参考设计，不代表当前板子已通过实机验收。

## 运行

1. 关闭原厂 CAN 工具和占用串口的软件。
2. 在上位机主界面选择 `STM32F103 串口桥接`、F103 对应 COM、波特率 115200，点击连接。
3. 先发送 Ping：主控实际写入 F103 串口 `12 4C 01 01 00 60`，预期通过 CTS 返回 `05 1C 01 01 00 23`。
4. 在多圈运动前先读取角度，再空载进行小角度低功率试验。
5. 如要切回 USB-CAN，先断开当前连接再切换模式。

## 排故

- Ping 失败：先查 F103 固件 TX CAN ID 是否 0x6A0、CAN 是否 1 Mbps、CTS 滤波是否开启只接 0x6A0。
- Ping 去程正常但无回包：检查 F103 RX CAN 是否只转发 0x6A1，以及 PA9/PA10/USB-TTL TX/RX 交叉。
- 只支持 Ping、长运动不动作：检查 F103 连续 UART 字节分片和 CAN 8 字节分片是否丢失/交错、CTS 到舵机扩展板通讯。
- F103 模式不能直接发其他 CAN ID，这是旧固件的限制；需要改固件时单独评审。