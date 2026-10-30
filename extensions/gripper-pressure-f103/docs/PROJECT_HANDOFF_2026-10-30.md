# STM32F103 夹爪薄膜压力监测项目——完整交接文档（V3）

> 快照日期：**2026-10-30**  
> 仓库：[`hejkhk/ha8-can-gripper`](https://github.com/hejkhk/ha8-can-gripper)  
> 模块目录：[`extensions/gripper-pressure-f103/`](../)  
> 当前工作版本：**压力监测 V3（免砝码电路理论估算，Rf 默认 158kΩ）**  
> 项目定位：夹爪末端薄膜传感器受力趋势监测与**理论受力估计**；不直接驱动 HA8 舵机、不提供安全急停、不构成已标定的测力仪。  
> 交接规则：“已编写”只表示仓库存在代码；“用户实物已观察”只代表当时屏幕/操作证据；“待验证”不可写成已完成。

---

## 0. 三分钟交接摘要（下一位开发者优先读）

**当前已跑通的通信链路：**

`IMS003-C10A-1KG（两线 FSR） → 5V 线性电压转换板 AO → STM32F103C8T6 PA1/ADC1 → USART1(115200) → USB-TTL → Windows Python/Tkinter 上位机`

用户已展示 Windows COM4 连通，界面约 **100 帧/秒、丢帧显示为 0**，手动加压时 ADC 与 AO 电压同步上升，某时刻显示 **ADC 1744、1405mV**。这些仅证明**采集与通信方向正确**；并非已知法向力下的测量精度验证。

**V3 的关键区别：**此前 V1 要求多点实测，V2 使用厂家电导曲线 + 一个已知受力点；V3 根据新取得的**电压转换模块用户手册**，直接使用运放公式 `Uo=0.1*(1+Rf/Rx)`，与传感器原厂电导—受力数据结合，计算**理论**受力。用户当前要求软件**按 Rf=158kΩ** 计算，这不是我们确认“已用万用表实测到 158kΩ”的证据。

**尚未完成：**实物验证 Rf/ADC 参考电压、已知法向受力误差测试、1～2kg 的可靠性验证、压力监测与 HA8 主程序统一 UI，以及任何以压力为反馈的安全闭环。

---

## 1. 两条物理链路必须严格区分

### A. 本模块：压力监测

```text
FSR 两线 → 电压转换板 → AO → F103 PA1
转换板：5V 供电，GND 与 F103 共地
F103 PA9(TX) ──→ USB-TTL RXD ──USB──→ PC（压力监测 GUI）
F103 PA10(RX) ←── USB-TTL TXD（已初始化，当前不解析命令）
F103 GND     ──── USB-TTL GND
```

- 供电前核对板载丝印，模块 **VCC 5V**、AO 标称输出 **0.1～3.3V**；实际要用万用表核实，在任何正常操作下 AO 不得超过 F103 模拟输入允许范围。
- USB-TTL 信号需采用与 MCU 兼容的 **3.3V TTL 电平**；注意 USB-TTL 的供电端与 TXD 实际高电平不一定相同；共地，不要把两路独立供电直接硬并。
- `DO` 当前**未使用**，其电位器 `DO-RES` 仅调整数字比较阈值；实际模拟受力换算使用 `AO-RES`。
- 调试/烧录使用 ST-LINK SWD（PA13/PA14，按板子要求接 GND、VTref/NRST），`BOOT0=0` 正常从用户 Flash 运行。

### B. 原 HA8 控制系统（本模块不接管）

```text
PC → HA8 官方 USB 串口扩展/转接板 → HA8-U35H-M 12V 串口舵机 → 蜗轮蜗杆夹爪
```

主程序是仓库根目录 `HA8_UpperComputer.py`，其 `ha8_protocol.py` / `ha8_serial.py` 处理舵机原生协议。**不要**误将本项目的 F103/USB-TTL 压力串口写成 HA8 的舵机控制链路。早年的 CAN、CTS100M、STM32 透明桥方案为历史资料，不是当前推荐链路。原 HA8 交接：[doc/PROJECT_HANDOFF_2026-10-16.md](../../../doc/PROJECT_HANDOFF_2026-10-16.md)。

---

## 2. 核心硬件、资料与物理限制

| 部件 | 已知参数/作用 | 核对要求 |
|---|---|---|
| FSR | `IMS003-C10A-1KG`，两线可变电阻，受力越大阻值越低 | 固定贴片、压头形状/接触面积、预紧、剪切力都会改变响应 |
| AO 转换模块 | 5V 供电；卖家手册 AO 0.1～3.3V；AO-RES（反馈电阻）可调，标称 0～300kΩ | **当前代码预设 Rf=158kΩ**，必须和实际反馈电阻一致 |
| STM32 | `STM32F103C8T6`，12位 ADC1_IN1/PA1、USART1 PA9/PA10 | 目前 ADC 电压用名义 `VDDA=3.3V` 换算，未做电压基准精度标定 |
| USB-TTL | Windows 虚拟 COM 串口，115200 8N1 | 使用 3.3V 信号电平并共地；当前接入的 COM 口号可能变化 |

原厂规格书第一页：**标称 1kg、最小测力 50g、重复性约 5%、迟滞约 10%、90% 满量程下 1 小时蠕变约 20%**；第二页虽然给出 2kg 处电阻/电导参考点，但**不代表 1～2kg 区间已获精度、寿命或可靠性保证**。

**资料来源（文件由用户在聊天中提供，本仓库未归档这两个 PDF 原件）：**
- `产品规格书-IMS003-C10A-1KG V1.0.pdf`：第 1 页规格，第 2 页电阻/受力/电导参考表与曲线；
- `电压转换模块用户手册8.30+.pdf`：第 3 页模块参数，第 4～5 页运放公式、AO-RES 推荐值及 R2 测量方法。

转换板手册第 4 页对 IMS-C10A 小量程列有 **300kΩ 推荐反馈阻值**，并说明断电后可测未焊 R2 两端判断 AO-RES 的当前电阻；**300kΩ 不是用户本次设置的值，158kΩ 也不是已证实的实际硬件测量值。**

---

## 3. 仓库目录与职责

```text
ha8-can-gripper/
├─ HA8_UpperComputer.py                  # 原 HA8 控制 GUI；此压力模块未接入
├─ ha8_protocol.py / ha8_serial.py      # 原 HA8 舵机协议、通信；不要混用
├─ doc/PROJECT_HANDOFF_2026-10-16.md     # 原 HA8 项目的历史交接
└─ extensions/gripper-pressure-f103/
   ├─ README.md                           # 模块快速入口
   ├─ Gripper_Pressure_F103.ioc            # STM32CubeMX 配置源
   ├─ Core/
   │  ├─ Src/main.c                       # ADC采样、滤波、UART发帧
   │  └─ Src/... / Inc/...                # F103 初始化、中断及头文件
   ├─ MDK-ARM/
   │  ├─ Gripper_Pressure_F103.uvprojx     # Keil 工程
   │  └─ startup_stm32f103xb.s            # 启动代码
   ├─ PC_UpperComputer/
   │  ├─ gripper_monitor.py               # Tkinter GUI/串口读线程/实时图/CSV/配置
   │  ├─ protocol.py                      # 帧解析、厂家表、三种受力换算
   │  └─ requirements.txt                 # pyserial（Tkinter 随标准 Python 安装通常附带）
   ├─ tests/test_protocol.py              # 协议、插值和电路模型的单元测试
   └─ docs/
      ├─ PROJECT_HANDOFF_2026-10-30.md    # 本交接
      ├─ ao_converter_v3.md               # 转换模块数学模型
      ├─ factory_curve_v2.md              # V2 原厂曲线单点方案历史
      ├─ initial_release_v1.md            # V1 初始工程说明
      └─ changes_v1.md                    # V1 更改日志
```

GitHub 目录**刻意未收录大量 STM32CubeF1 HAL/CMSIS `Drivers/` 文件和 Keil 临时编译产物**。不能把 GitHub 子目录当成“无须下载固件包即可直接 Keil 编译”的完整独立包；CubeMX 生成/安装所需驱动后才可构建。生成前备份代码，生成后对比 `Core/Src/main.c` 自定义逻辑。

---

## 4. F103 固件配置与实际协议

### CubeMX 配置（以 `.ioc` 和 `Core/Src/main.c` 为准）

| 项目 | 当前实现 |
|---|---|
| MCU | STM32F103C8Tx，LQFP48 |
| SYS | Serial Wire，SysTick |
| 时钟 | HSI SYSCLK 8MHz，ADC 时钟 /2 为 4MHz |
| ADC | ADC1 Channel 1 = PA1，12位、单次软件启动 |
| 采样时间 | `ADC_SAMPLETIME_239CYCLES_5` |
| 采集 | 每 10ms 一轮，16 次 ADC 平均 |
| 滤波 | Q8 整数 EMA，alpha=1/4 |
| 电压换算 | `mv=round(adc*3300/4095)`，仅使用名义 3.3V |
| UART | USART1 PA9 TX、PA10 RX，115200 8N1；当前只主动发送 |
| 校准 | 上电执行 `HAL_ADCEx_Calibration_Start`，失败上报标志 |

发送的 ASCII 行格式：

```text
P,seq,mcu_ms,adc,mv,flags\r\n
```

**示例（协议结构演示，不是真实测量记录）：** `P,42,10025,1744,1405,0`

| 字段 | 含义 |
|---|---|
| `P` | 数据帧类型 |
| `seq` | 递增序列号，32 位回绕 |
| `mcu_ms` | 单片机 HAL_GetTick 上电毫秒 |
| `adc` | 16次平均 + EMA 后的 ADC（0～4095） |
| `mv` | 名义毫伏数（依赖假定 3.3V） |
| `flags` | bit0=1 ADC失败；bit1=2 读数>=4090接近满量程；bit2=4 ADC上电校准失败 |

固件若 ADC 读失败，会复用**上次有效值**并设置 bit0，不要当新鲜有效样本。串口帧**没有 CRC**，主机仅解析 CSV 字段并基于 `seq` 统计帧号跳变。UART 发送采用 HAL 阻塞方式，约 100Hz 是目标而不是硬实时保障。

---

## 5. 理论受力模型与 158kΩ 配置

### 5.1 两份厂家资料如何组合

压力传感器表给出 `Rx(F)` 或 `G(F)=1/Rx(F)`；转换模块手册第 5 页给出：

```text
Uo = 0.1 * (1 + Rf / Rx)
G  = (Uo - 0.1) / (0.1 * Rf)
```

`Uo` 单位 V，`Rf` 和 `Rx` 都用 **kΩ**，`G` 单位 **1/kΩ**。上位机 `protocol.py::estimate_circuit_force_g` 将 ADC 换算到电压，再从电导厂家表做**分段线性插值**，返回克力 `gf`，另计算 `N = gf * 0.00980665`。超过厂家表的 2kg 点不做外推。

若点击“无负载采集零点”，程序会用记录的 `Uzero` 替代理论的 `0.100V`：

```text
Uo    ≈ ADC * 3.3 / 4095
G_est = (Uo - Uzero) / (0.1 * Rf)
```

这只是**偏置校正**，**不能**自动校正错误的反馈电阻、供电基准误差或传感器自身的迟滞/蠕变。零点刚采集时要求串口已有稳定数据；必须在夹爪接触面无载、最终安装位置下采集。

### 5.2 厂家表格与 Rf=158kΩ 理论值

| 受力 gf | 厂家传感器 Rx | 理论 Uo（158kΩ，理想0.1V偏置） |
|---:|---:|---:|
| 0 | >2MΩ（以无载理论零电导近似） | 0.100V |
| 50 | 160kΩ | 0.199V |
| 100 | 90kΩ | 0.276V |
| 200 | 49kΩ | 0.422V |
| 500 | 18kΩ | 0.978V |
| 1000 | 9.8kΩ | 1.712V |
| 2000 | 5kΩ | 3.260V |

理论 2kg 时输出 3.260V，距离板子标称 3.3V 上限只有 **40mV**。在实际板子上可能提前饱和，且固件 bit1 仅在 ADC>=4090 时触发，**不会识别所有近上限失真**。超出规格书标称 1kg 的数据**仅参考/风险自负，不是已验证工作量程**。

### 5.3 三种 GUI 模式及优先级

1. **免砝码 · 电路（V3 默认）**：需要当前 Rf（本次默认填 158kΩ），推荐额外采集无载零点，估计受力；无需已知受力，但没有实测精度保证。
2. **单点参考**：无载零点 + 一个“已知实际法向受力”，用厂家电导曲线确定增益；适合有可靠受力参考时使用。
3. **多点实测**：至少两组单调的已知受力—ADC 点，分段插值；可在实际安装结构下提高针对性。

**警告：** “用夹爪夹住一个 500g 物品”不等于传感器承受 500gf 法向夹紧力。不能用物品质量直接冒充夹紧法向力。

---

## 6. Windows 上位机运行、持久化与测试

### 首次运行

在 Windows PowerShell 中：

```powershell
git clone https://github.com/hejkhk/ha8-can-gripper.git
cd ha8-can-gripper\extensions\gripper-pressure-f103
py -3 -m pip install -r PC_UpperComputer\requirements.txt
py -3 PC_UpperComputer\gripper_monitor.py
```

运行后：
1. 插入压力系统 USB-TTL，选择其对应 COM 端口（此前用户看到 COM4，**不能写死 COM4**），点击连接。
2. 观察每秒约 100 帧、ADC 与电压随按压增大。仅此步骤不需要标定。
3. 在“免砝码 · 电路”选项卡核对 Rf 为 **158**（单位 kΩ）；**旧 `calibration.json` 会覆盖程序默认 158**，若显示其他值，手动改 158。
4. 松开夹爪、确认压力片无载，保持静止至少约 1 秒，点击“无负载采集零点”。
5. 点击“保存当前标定/模式”；以后启动会读回零点和 Rf。可点击清峰值，或开始/停止 CSV 记录。
6. 验证压力增加与减小时趋势正常，极值附近读数不进入不可解释的饱和。不要让此值独立参与安全相关动作。

GUI 提供实时 ADC/mV、估算 gf/N、峰值、约 60 秒曲线、串口速率/丢帧统计和 CSV。

### 文件和数据格式

- `PC_UpperComputer/calibration.json`：启动自动加载，保存模式、厂家零点/参考、实测点及 V3 电路 `rf_kohm` / `zero_adc`；**被 .gitignore 排除，属于用户设备私有参数，不上传仓库**。
- CSV 数据列：`pc_time,sequence,mcu_ms,adc,voltage_mv,force_g,force_N,status,calibration_mode`；也是本地文件，不应提交。
- 后台串口读线程仅做读取/帧解析，Tkinter 主线程刷新控件；`protocol.py` 是可独立测试的纯算法模块。
- 当状态 bit0/bit1/bit2 异常或模型超出区间，GUI 不应把不可用数据作为可信受力显示。

### 开发者测试

从模块目录运行：

```powershell
py -3 -m py_compile PC_UpperComputer\protocol.py PC_UpperComputer\gripper_monitor.py tests\test_protocol.py
py -3 -m unittest discover -s tests -v
```

当前仓库 `tests/test_protocol.py` 包含帧格式、边界、单点/多点插值、电路公式、Rf=158kΩ 理论 2kg 的单测。**这次文档交接没有重新烧录、Keil 实机编译或实际施加标准力做精度验收；不要据此标注“实测通过”。** 根仓库的 HA8 测试与此子目录测试相互独立，后续应把子目录也接入 CI。

### 重新编译固件

- 打开 `Gripper_Pressure_F103.ioc`（仓库配置基于 STM32Cube FW_F1 V1.8.7，CubeMX 6.17.0），安装/选择对应 STM32CubeF1 Pack，选择 `MDK-ARM V5.32` 等合适工具链，保留 USER CODE；
- 重新生成依赖并**逐项对比** `Core/Src/main.c` 与 `.ioc`，确认 239.5 周期 ADC、上电校准、16 次平均/EMA/发帧代码未丢；
- Keil 打开 `MDK-ARM/Gripper_Pressure_F103.uvprojx`，配置芯片和 Flash 算法，ST-LINK SWD 低速先连，再烧录；`Drivers/` 不在仓库，需要 CubeMX 补齐。

---

## 7. 验证分级（不要混淆）

| 检查项 | 当前证据与状态 |
|---|---|
| STM32 串口→电脑 | **用户已观察**：COM4 已连接，显示约 100 帧/s，丢 0 |
| 按压→模拟电压上升 | **用户已观察**：静态低电压，按压后 ADC/AO 明显上升 |
| V3 数学公式与查表 | **代码已实现**，有自动化用例；无实际砝码/力标准验收 |
| Rf=158kΩ | **软件按此值配置**；当前没有独立实测阻值证据 |
| 绝对受力 gf/N 精度 | **尚未验证** |
| 50g 以下及 1～2kg | **未验证**；2kg 超过首页标称量程 |
| 与 HA8 控制上位机融合 | **尚未实现** |
| 按压力自动停止夹爪 | **尚未实现，更不是硬件急停** |
| 供电/异常断线/迟滞/蠕变长期测试 | **尚未完成完整验收** |

---

## 8. 已知限制、故障排查和后续工作

### 主要技术债务（按优先级）

- **P0 硬件确认**：断电测未焊 R2 焊盘实际反馈阻值，确认是否为 158kΩ；万用表对比 AO 与串口 mV；确认 MCU VDDA，压片安全接线与 3.3V 上限；更新现场记录。
- **P0 力值可信度**：至少选择两种安全且可复现的已知法向力验证残差；夹持接触面积/预紧/加载与卸载曲线要分别记录。无已知力装置时，只能报告**趋势与理论估算**，不得承诺“精确测力”。
- **P1 稳定性**：ADC 接近上限/串口断线/帧损坏监测，评估滤波延迟对短时峰值的影响；目前只有 bit1 在 ADC>=4090 时触发，高端接近饱和并不总是被识别。
- **P1 统一界面**：未来可将 `protocol.py` 复用/抽离，增加独立压力串口服务与 HA8 主界面的只读压力卡、峰值和曲线。**HA8 舵机 COM 与 F103 压力 COM 必须独立管理**，不得用同一解析器/同一串口混发指令。
- **P2 闭环研究**：在完成法向力标定、机械限位、串口失联策略、独立硬件停机后，再单独设计接触检测和夹紧限力控制；不得把当前估计值直接接入自动停机安全路径。
- **P2 自动化**：给根仓库 CI 增加子模块 `tests/` 的 unittest 和 GUI 导入/界面烟雾测试，按需增加协议异常输入测试。

### 常见问题速查

| 现象 | 处理建议 |
|---|---|
| 没有 COM 数据 | 检查 PA9→TTL RXD、共地、115200 8N1、BO​​OT0、供电、固件、是否被其他软件占用 |
| 有 ADC 却没有克力 | 核对选中“免砝码 · 电路”、Rf>0 且<=300kΩ；异常帧与超范围不显示值 |
| 无载仍显示正受力 | 完全卸载后重新采集“无负载零点”；排除机械预紧和漂移 |
| 更换板子/调电位器后偏差 | 重新核实 Rf、ADC基准并采零点；无已知力时无法证明新精度 |
| 受力很大但电压不再上升 | 输出可能饱和，尤其 2kg 时理论 3.26V 已接近上限 |
| Keil Flash Download failed | 核对 SWD/芯片供电/Flash 算法/Boot0，降低 SWD Clock；必要时 ST 官方 CubeProgrammer Under Reset |
| 上位机打开后仍不是 158 | 已存在的 `PC_UpperComputer/calibration.json` 可覆盖默认值；改 158 并保存 |

### 下一个 Agent 接手的最小行动序列

1. 先读本交接及 `README.md`、`docs/ao_converter_v3.md`。
2. 执行 `git status`，确认基线；阅读本模块的 `Core/Src/main.c`、`PC_UpperComputer/protocol.py`、`gripper_monitor.py`，禁止只凭历史版 V1/V2 文档下结论。
3. 执行 Python 语法和 `unittest`，查看 GUI 线程/串口/保存配置差异，必要时写针对性回归测试。
4. 若改固件，留意 MCU 64KB Flash / 20KB RAM、HAL 包依赖、实际 BOOT/SWD 条件。若改 HA8 控制，先单独看其最新主分支与原交接。
5. 在新分支/PR 中提交代码和测试，明确是否触碰 HA8 控制路径。不要将尚无实机证据的推测写成“已验证”。
6. 任何影响压力实际单位的改动必须附计算公式、单位、饱和处理和重新采零点策略。

---

**交接边界：**至 2026-10-30，项目已实现并观测到“压力变化→ADC→USB-TTL→GUI”链路，V3 基于 **158kΩ 假设/配置**进行理论受力显示。机械夹爪末端真实力校准、与 HA8 一体化、安全闭环均为后续工作。
