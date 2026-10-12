# HA8-CAN 夹爪独立上位机

基于 HA8-U35H-M UART 总线舵机、CTS100M UART↔CAN 模块与 USB-CAN 适配器的夹爪调试上位机。代码从此前验证的 **V1.1** 整理，**本次仓库化不修改舵机协议或控制算法**。

## 通讯架构

```text
Windows PC → USB-CAN(CDC COM, 115200 8N1)
  → Classical CAN 1 Mbps, 11-bit standard data frames
  → CTS100M (CAN ↔ UART 115200 8N1)
  → 舵机扩展板 → HA8-U35H-M
```

- CAN 命令：`0x6A0`（主控 → 夹爪）
- CAN 反馈：`0x6A1`（夹爪 → 主控）
- CTS CAN 过滤：只接收标准数据帧 `0x6A0`，UART→CAN 发送标识符仍为 `0x6A1`
- HA8 默认舵机 ID：`0`
- 单帧 CAN 8 字节，长 HA8 指令拆成多帧，接收按 HA8 帧头/长度/校验重组

## 文件分工

| 文件 | 作用 |
|---|---|
| `HA8_UpperComputer.py` | Tkinter GUI 与业务流程 |
| `ha8_protocol.py` | HA8 控制指令编码、返回解析、校验（独立模块） |
| `usb_can_cdc.py` | USB-CAN CDC 串口协议、CAN 发送与接收 |
| `doc/` | 机械臂侧通讯说明、设备手册及参考资料 |

## 运行

```powershell
pip install -r requirements.txt
python HA8_UpperComputer.py
```

连接原厂 USB-CAN 对应的 COM 口，先使用 Ping / 读取角度验证，再进行空载小角度动作测试。**关闭原厂 CAN_LIN_TOOL_V6.0，避免串口占用**。

## 已验证与待验证

- 已实测：`0x6A0` Ping `12 4C 01 01 00 60`，`0x6A1` 返回 `05 1C 01 01 00 23`；角度回读成功。
- V1.1 修复了多帧运动指令 USB CDC 分包方式；请根据实际机构逐项验证运动控制、保持与调零。
- 电流→扭矩目前 **尚未完成标定**；官方动态曲线不能直接作为静止夹持力标定模型。

> 正式机械臂接入时请检查同一总线的电气连接、120Ω 终端以及关节帧与夹爪帧隔离。请勿将“电流升高”单独作为可靠抓稳的判据。

## 资料

参见 [`doc/`](doc/) 与 [`doc/torque_current_notes.md`](doc/torque_current_notes.md)。