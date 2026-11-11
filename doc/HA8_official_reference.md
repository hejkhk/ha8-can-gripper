# HA8-U35H-M 官方技术资料与参数

## 厂家资料

- 型号技术文档：<https://fashionstar.com.cn/wiki/uart-servo/ha8-u35h-m/>
- 原厂 PDF 示例入口：<https://fashionstar.com.hk/wiki/servo/uart/datasheet/pdf/Fashion-Star-HA8-U35H-M.pdf>（如失效请从官网产品页进入）

之前提供的《HA8-U35H-M UART 总线舵机技术文档》PDF 包含 **T-N 特性曲线（PDF 第4页）**、机械尺寸、接口及通信控制协议。文档以**12V型号**为主要参考。

## 已核对参数

| 参数 | 数值 |
|---|---|
| 舵机本体接口 | PH2.0 3Pin: `- GND / + VDD / S SIGNAL` |
| 波特率 | 可设置，当前使用 `115200 8N1` |
| 默认 ID | `0` |
| HA8 协议请求帧头 | `12 4C` |
| HA8 协议响应帧头 | `05 1C` |
| 静态堵转扭矩 | 约 3.43 N·m |
| 最大动态扭矩 | 约 1.27 N·m |
| 额定扭矩 | 约 0.54 N·m |
| 峰值电流 | 约 3 A |
| 空载电流 | < 0.2 A |

请注意上述堵转/动态/额定工况**不同**，不能直接拿峰值电流和堵转扭矩除出常数作为动态转矩系数。

## 当前项目连接（修订：2026-11-11）

**当前实际推荐链路是两条独立 USB COM，而不是历史 CAN/CTS100M。**

```text
Windows → USB → HA8 官方 USB 转接板 → HA8-U35H-M 的 VIN / IO(S) / GND
Windows ← USB-TTL ← STM32F103 USART1 ← 压力转换板 AO ← 指尖 FSR
```

此前“USB-CAN → CTS100M → 舵机”的描述为**历史方案**，不再作为当前接线。官方转接板最新一页原理图给出 CN1/CN2 **1=VIN、2=IO、3=GND**（连接器物理方向仍需实物核实）。

完整交接：[PROJECT_HANDOFF_FULL_2026-11-11.md](PROJECT_HANDOFF_FULL_2026-11-11.md)。下一阶段拟由 STM32 通过受保护的单线半双工收发器直接连接 HA8 S，**该功能尚未开发/验证**。
