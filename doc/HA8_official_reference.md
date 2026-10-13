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

## 当前项目连接

实际主机使用 `USB-CAN → CAN → CTS100M → UART TXD/RXD → 舵机扩展板 → HA8 本体单线SIGNAL`，不要把 HA8 本体 3Pin 的 S 信号误认为独立 TXD/RXD。