# CTS100M 联合机械臂总线配置

## 已实测参数

| 项目 | 配置 |
|---|---|
| CAN | Classical CAN 2.0, `1 Mbps`, 标准数据帧 (11-bit) |
| CAN→UART | 双向透明转换，输出 CAN DATA 原始字节，不添加帧信息和 CAN ID |
| UART | `115200 8N1`, 3.3V TTL |
| 串口→CAN 发送标识符 | `0x6A1`（十进制1697）|
| CTS 接收滤波 | 只允许标准数据帧 `0x6A0`（十进制1696）|
| CTS 模块供电 | **3.3V**（不能直接接 5V/12V/24V）|
| CFG | 配置时拉低；正常转换时拉高至3.3V |

## 滤波器

CTS 的“单滤波（标识符列表）→ 标准帧 → 数据帧 → 只接收 n 个 ID”的两个 ID 槽都填 **1696**；曾在实机得到：

```text
FilterIdHigh     = 0xD400
FilterIdLow      = 0x0000
FilterMaskIdHigh = 0xD400
FilterMaskIdLow  = 0x0000
```

这里采用**列表模式**，后两个 Mask 字段实际上是第二个 ID 槽；列表重复填 `0x6A0` 是允许的。接收滤波不要加入 `0x6A1`：`0x6A1` 是 CTS 从 UART 收到 HA8 回复后自行向 CAN 发出的反馈标识符。

## 总线集成

六关节 RobStride CAN 使用扩展帧；夹爪使用标准帧 `0x6A0`/`0x6A1`，能够共存于同一条 1 Mbps Classical CAN 总线。保证线性拓扑和总线两端终端电阻，断电测 CANH-CANL 应接近 60 Ω（两端各 120 Ω）。