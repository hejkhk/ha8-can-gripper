# 官方舵机 USB 串口直连（当前方案）

## 硬件链路

```text
PC USB ── 官方 HA8 舵机扩展/转接板 ── HA8 本体
                                  └── 舵机按铭牌额定电压供电
```

若使用分立 USB-TTL 而不是板载 USB：

```text
USB-TTL TXD -> 扩展板 RXD
USB-TTL RXD <- 扩展板 TXD
USB-TTL GND --- 扩展板 GND
```

HA8 本体采用 S 单线半双工，**不要把本体 PH2.0 的 S 与两个独立 RX/TX 混淆**。让官方转接板负责半双工方向转换。先确认板载 USB 电平与供电定义，避免将电机电源直接接入 TTL 引脚。

## 软件

主程序选择官方转接板的 COM 端口；串口 115200 8N1，HA8 默认 ID 为 0。转接板端不需要 CAN 帧头、CAN ID、USB-CAN 20 字节封包，也不需要 F103 固件。

Ping 示例：

```text
TX: 12 4C 01 01 00 60
RX: 05 1C 01 01 00 23
```

串口是字节流，接收的一次 `read()` 不保证恰好是一帧；程序使用 HA8 响应的 `05 1C`、LEN 和 CHECKSUM 重组。

## 现有代码

- `HA8_UpperComputer.py`: GUI、操作逻辑
- `ha8_protocol.py`: HA8 请求/响应
- `ha8_serial.py`: 115200 8N1 串口收发和后台读取
- `usb_can_cdc.py`、`f103_uart_bridge.py`: 历史实现，V3 不再使用

## 安全

调试动作先空载、低功率、小角度运行；设置原点、重置圈数、写寄存器、恢复出厂需确认设备状态。原厂 SDK 对同步/异步可能要求特定固件版本，本机尚未实测；不要在未知机械限位下测试大角度运动。
