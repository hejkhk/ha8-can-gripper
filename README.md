# HA8-U35H-M 官方 USB 串口直连测试上位机（V3.0-beta）

本项目现以 **官方舵机扩展板 / 官方 USB 串口转接板直连** 为主，不再依赖 STM32F103、USB-CAN、CTS100M 或 CAN 标识符。

```text
Windows 电脑 ─USB→ 官方舵机转接板 ─→ HA8-U35H-M
                                           ↑
                                 按型号要求单独供电（如 12V）
```

- COM 端口：由 Windows 设备管理器确认，历史上直连曾使用 COM6，但不固定。
- HA8：115200、8 数据位、无校验、1 停止位（8N1）。
- 发送：`12 4C CMD LEN CONTENT CHECKSUM`。
- 接收：`05 1C CMD LEN CONTENT CHECKSUM`。
- Ping ID 0：`12 4C 01 01 00 60` → `05 1C 01 01 00 23`。
- 长指令通过 UART **一次连续发送完整请求**，不按 CAN 的 8 字节拆帧。
- `ha8_protocol.py` 独立维护控制指令和回包解析，`ha8_serial.py` 只处理串口通信。
- 保留既有八个测试模块：位置控制、数据监控、停止与标定、通讯检测、参数读写、同步/异步、HA8 原始协议、串口调试。
- 高级同步/异步仍有固件版本限制；仅凭发出请求不能认为执行成功。
- 曾经使用的 CAN/F103 文件暂留作为历史兼容参考，**V3 主程序不再导入、也不再调用**。

## 运行

```powershell
pip install -r requirements.txt
python HA8_UpperComputer.py
```

先关闭官方串口调试软件，避免占用同一 COM 端口。正确连接扩展板与舵机并上电后，执行 Ping → 读取角度 → 数据监控 → 空载小角度运动。

详见 [doc/direct_usb_serial_mode.md](doc/direct_usb_serial_mode.md)。保留的 CAN 文档只是历史集成资料，并非 V3 的当前接线要求。

## 验证范围
过去已通过官方转接板 + USB-TTL 直接串口 Ping 验证；本次 V3 直连代码尚未在用户当前设备上验收。请依次测试运动、原点设置和高级指令。
