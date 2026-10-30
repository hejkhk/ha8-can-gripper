# 历史通信驱动（保留原功能与测试）

- `usb_can_cdc.py`：早期 USB-CAN CDC 适配器、20 字节 CAN 数据记录及初始化指令。
- `f103_uart_bridge.py`：早期 F103 UART→CAN 透明桥，引用本目录的 `usb_can_cdc.py`。
- 这两个模块由 `tests/test_transport.py` 和 `tests/test_f103_bridge.py` 验证，**当前 HA8 上位机不导入它们**。
- 旧项目需要时可用 `from legacy.usb_can_cdc import UsbCanCdc` 和 `from legacy.f103_uart_bridge import F103UartBridge` 单独导入；不要与当前官方串口和 F103 压力串口混用。

相关历史资料仍在 `doc/`；历史提交可从 GitHub 查阅。本目录不作为统一 GUI 的日常运行入口。
