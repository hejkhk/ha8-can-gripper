# HA8-CAN 全功能测试上位机 v2.0-beta

面向 **HA8-U35H-M**（配原厂扩展板）和 **QK-CTS100M** 的独立 Windows/Tkinter 测试软件，适合机械臂夹爪调试。`ha8_protocol.py` 只负责 HA8 控制指令构造与反馈解析，`usb_can_cdc.py` 只负责 USB-CAN 的 CAN 帧收发。

## 运行环境

- Windows 10/11，Python 3.10+
- USB-CAN 适配器：已经逆向验证的 **CAN_LIN_Tool_V6.0 USB CDC 型号**（不是所有 USB-CAN 都通用）
- CTS100M：3.3V 供电、CAN 1 Mbps、UART 115200 8N1，CAN 发送标准 ID `0x6A1`、接收过滤只允许 `0x6A0`
- HA8 舵机：额定型号电压供电，默认 ID=0

```powershell
pip install -r requirements.txt
python HA8_UpperComputer.py
```

原厂 CAN_LIN_Tool 不能和本程序同时占用 COM 口。

## 功能页

1. **位置控制**：单圈/多圈，简易时间/梯形时间/梯形速度三种模式，读取角度。
2. **数据监控**：定时回读电压、电流、功率、温度 ADC、状态字、角度、圈数，导出 CSV。
3. **停止/标定**：失锁释放、保持、阻尼、设置原点、重置多圈；标定自动先解除锁力。
4. **通讯检测**：单舵机 Ping、指定范围内的 ID 扫描（单次最多 32 个）。
5. **参数读写**：读/写寄存器原始字节，恢复用户数据（两次确认）。
6. **同步/异步**：6 种同步角度模式、同步监控、异步缓存/执行/取消，**固件兼容性需先确认**；保留专家原始载荷入口。
7. **HA8 原始协议**：输入 CMD + CONTENT，自动计算 LEN/校验，预览并发送。
8. **CAN 调试**：逐帧显示实际发出的 CAN 分片和接收 CAN 帧，手动发送标准数据帧。

详细状态见 [`doc/FEATURE_MATRIX.md`](doc/FEATURE_MATRIX.md)。

## 安全与已验证范围

- 当前硬件链路实际 Ping：
  - `TX CAN 0x6A0`: `12 4C 01 01 00 60`
  - `RX CAN 0x6A1`: `05 1C 01 01 00 23`
- 基础角度读取已在先前版本实测；V2 新增指令**只做了静态/模拟测试，还未进行舵机实机验证**。
- 正式硬件测试顺序：Ping → 角度读取 → 监控 → 空载单圈小角度 → 多圈 → 停止模式 → 零位 → 数据表 → 同步/异步。
- 恢复用户数据可能将舵机 ID 重置到 0；此操作仅允许单颗舵机独立测试。
- 同步/异步需确认 HA8 使用的固件兼容官方所述的无刷磁编码 V316+，否则不要启用。
- 本程序不提供独立的硬件急停。实际负载测试必须保留机械臂急停和独立断电手段。

## 测试

```powershell
python -m unittest discover -s tests -v
```

## 官方参考

- [官方 HA8 Wiki](https://fashionstar.com.cn/wiki/uart-servo/ha8-u35h-m/)
- [官方 Python SDK](https://fashionstar.com.cn/wiki/sdk/servo/python-sdk/)
- [官方同步指令源码](https://github.com/servodevelop/servo-uart-rs485-sdk/blob/main/micro-python/src/uservo.py)

## V2.1-beta：USB-CAN 与 F103C8T6 双模式

上位机在连接前可选择：
- **USB-CAN CDC**：保留原来的 \`usb_can_cdc.py\`；20 字节 USB-CAN 封包；COM 115200 8N1。
- **STM32F103 串口桥接**：新增 \`f103_uart_bridge.py\`；PC 串口以指定波特率直接发送 HA8 原始字节，由 F103 负责打包 CAN 0x6A0，CAN 0x6A1 反馈经 F103 转回 UART。

注意：F103 透明桥接串口**不**接受 USB-CAN 的 20 字节命令；固定 CAN ID 由 MCU 固件决定，串口无法回传实际 CAN 帧边界。参见 [F103 桥接模式说明](doc/STM32F103_bridge_mode.md)。

本版同时修复 V2.0-beta 中 \`IndentationError: unexpected indent\` 的启动错误。新增 F103 后端已做离线测试，尚待用户实机验收。
