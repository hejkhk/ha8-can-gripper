# HA8-U35H-M 机械臂侧 CAN 通讯说明（基础版）

> 本文只整理机械臂控制程序最需要的几项：**读取当前角度、发送目标角度、调零/设置原点**。  
> 舵机 ID 以下均按当前默认值 **ID = 0** 举例。

---

## 1. 当前通讯链路

```text
机械臂主控 / 上位机
        │
        │  Classical CAN 2.0
        │  1 Mbps
        │  11-bit 标准数据帧
        ▼
      CTS100M
        │
        │  UART 115200 8N1
        ▼
   HA8 舵机扩展板
        │
        ▼
 HA8-U35H-M
```

CAN ID 固定分配：

| 方向 | CAN ID | 用途 |
|---|---:|---|
| 主控 → HA8 | `0x6A0` | 发送 HA8 指令字节流 |
| HA8 → 主控 | `0x6A1` | 接收 HA8 返回字节流 |

### 重要规则

1. CAN 使用 **1 Mbps、11-bit 标准帧、数据帧**。
2. HA8 一条完整指令如果超过 8 字节，需要按原始顺序拆成多个 CAN 帧发送。
3. 所有分片都使用同一个 CAN ID `0x6A0`。
4. 一条 HA8 指令的多个 CAN 分片之间**不要插入其他指令**。
5. 接收端将连续的 `0x6A1` DATA 按顺序拼接，再按 HA8 响应格式解析。

---

## 2. HA8 基本帧格式

### 2.1 发送给舵机

```text
12 4C | CMD | LEN | CONTENT... | CHECKSUM
```

- 固定帧头：`12 4C`
- `CMD`：指令编号
- `LEN`：CONTENT 字节数
- `CHECKSUM`：前面所有字节累加后取低 8 位

计算方式：

```text
CHECKSUM = sum(12 4C CMD LEN CONTENT...) & 0xFF
```

### 2.2 舵机返回

```text
05 1C | CMD | LEN | CONTENT... | CHECKSUM
```

返回帧头固定为：

```text
05 1C
```

---

# 3. 读取当前角度

## 3.1 读取单圈角度

发送 HA8 指令：

```text
12 4C 0A 01 00 69
```

直接放进一帧 CAN：

```text
CAN ID   = 0x6A0
DLC      = 6
DATA     = 12 4C 0A 01 00 69
```

舵机返回走 `0x6A1`。

返回格式：

```text
05 1C 0A 03 [ID] [ANGLE_L] [ANGLE_H] [CHECKSUM]
```

角度字段：

```text
angle_raw = int16 little-endian
当前角度(°) = angle_raw / 10.0
```

例如目前实机曾返回：

```text
05 1C 0A 03 00 FD FF 2A
```

其中：

```text
FD FF = int16(-3)
当前角度 = -3 / 10 = -0.3°
```

---

## 3.2 读取多圈角度

如果机械臂夹爪使用的是多圈位置，建议读取多圈角度。

发送：

```text
12 4C 10 01 00 6F
```

CAN：

```text
CAN ID   = 0x6A0
DLC      = 6
DATA     = 12 4C 10 01 00 6F
```

返回 CONTENT：

```text
ID        : uint8
angle_raw : int32 little-endian
turn      : int16 little-endian
```

计算：

```text
当前多圈角度(°) = angle_raw / 10.0
```

---

# 4. 发送目标角度

## 4.1 推荐：多圈绝对角度控制

夹爪由蜗杆机构驱动时，建议机械臂侧直接使用 **多圈绝对角度**。

基础指令：

```text
CMD = 0x0D
```

CONTENT：

```text
ID          uint8
angle_raw   int32 little-endian
interval    uint32 little-endian，单位 ms
power       uint16 little-endian，单位 mW
```

其中：

```text
angle_raw = 目标角度(°) × 10
```

### 示例：目标角度 600°，运动时间 2000 ms，功率上限 5000 mW

完整 HA8 指令：

```text
12 4C 0D 0B 00 70 17 00 00 D0 07 00 00 88 13 6F
```

这条指令共 16 字节，需要拆成两帧 CAN：

第一帧：

```text
CAN ID = 0x6A0
DLC    = 8
DATA   = 12 4C 0D 0B 00 70 17 00
```

第二帧：

```text
CAN ID = 0x6A0
DLC    = 8
DATA   = 00 D0 07 00 00 88 13 6F
```

注意：

```text
必须先发第一帧，再立即发第二帧。
中间不要发送其他 CAN 指令。
```

---

## 4.2 单圈角度控制（可选）

单圈角度范围：

```text
-180° ~ +180°
```

CMD：

```text
0x08
```

CONTENT：

```text
ID          uint8
angle_raw   int16 little-endian
interval    uint16 little-endian，单位 ms
power       uint16 little-endian，单位 mW
```

例如：

```text
目标：30°
时间：1000 ms
功率：5000 mW
```

完整 HA8 指令：

```text
12 4C 08 07 00 2C 01 E8 03 88 13 20
```

因为超过 8 字节，也需要按 8 字节顺序拆成多帧 `0x6A0`。

---

# 5. 调零 / 设置机械原点

设置原点前，先让舵机进入**失锁释放**状态。

## 第一步：失锁释放

完整 HA8 指令：

```text
12 4C 18 04 00 10 00 00 8A
```

该指令共 9 字节，因此拆成：

第一帧：

```text
CAN ID = 0x6A0
DLC    = 8
DATA   = 12 4C 18 04 00 10 00 00
```

第二帧：

```text
CAN ID = 0x6A0
DLC    = 1
DATA   = 8A
```

建议等待：

```text
约 50 ms
```

---

## 第二步：设置当前位置为机械原点

发送：

```text
12 4C 17 02 00 00 77
```

CAN：

```text
CAN ID = 0x6A0
DLC    = 7
DATA   = 12 4C 17 02 00 00 77
```

完成后，当前位置被作为新的机械原点。

---

# 6. 最简机械臂侧接口建议

机械臂程序只需要封装下面 3 个接口即可：

```text
get_angle()
set_target_angle(target_deg)
set_zero()
```

建议逻辑：

```text
get_angle()
    -> 发送多圈角度读取 0x10
    -> 等待 0x6A1
    -> 解析 angle_raw / 10.0

set_target_angle(target_deg)
    -> 构造 0x0D 多圈角度控制
    -> 超过 8 字节自动拆 CAN 帧
    -> 按顺序发送到 0x6A0

set_zero()
    -> 发送失锁释放 0x18
    -> 等待约 50 ms
    -> 发送设置原点 0x17
```

---

# 7. 接收端必须注意

CTS 返回的 CAN ID 固定：

```text
0x6A1
```

每收到一个 `0x6A1`：

```text
把 CAN DATA 追加到接收缓存
```

在缓存中寻找：

```text
05 1C
```

然后读取：

```text
CMD = buf[2]
LEN = buf[3]
整帧长度 = 5 + LEN
```

整帧：

```text
05 1C CMD LEN CONTENT... CHECKSUM
```

校验：

```text
sum(frame[:-1]) & 0xFF == frame[-1]
```

通过后再交给上层解析。

---

# 8. 当前项目固定参数汇总

```text
CAN 类型       : Classical CAN 2.0
CAN 波特率     : 1 Mbps
CAN 帧格式     : 11-bit 标准数据帧

命令 CAN ID    : 0x6A0
反馈 CAN ID    : 0x6A1

HA8 UART       : 115200 8N1
HA8 默认 ID    : 0

请求帧头       : 12 4C
响应帧头       : 05 1C
角度单位       : 0.1°
```

对于机械臂侧，最核心的就是：

```text
读取位置：0x10
目标位置：0x0D
失锁释放：0x18
设置原点：0x17
```