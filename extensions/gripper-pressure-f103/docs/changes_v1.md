# v1 工程修改清单

## 原工程检查
- STM32F103C8T6、HSI 8MHz、ADC1_IN1/PA1、USART1 TX PA9/RX PA10、115200 8N1、SWD PA13/14：均与计划一致。
- 原工程 `MX_ADC1_Init()` 的 `ADC_SAMPLETIME_1CYCLE_5` 对输入源阻抗不确定的压力转换板偏短，改为 239.5 周期；同步更新 `.ioc`。
- 原主循环为空。原 `MDK-ARM` 有历史 0 error/0 warning 编译日志（仅代表**修改前**项目的编译结果）。

## 固件新增（`Core/Src/main.c` 中 USER CODE 区域）
1. 采集周期 `SAMPLE_PERIOD_MS=10`，目标 100Hz。
2. `HAL_ADCEx_Calibration_Start()` 启动时校准；失败保留异常标志。
3. ADC 逐次软件触发、16 次平均；采样失败不伪造零电压。
4. EMA 指数平滑滤波（Q8整数，alpha=1/4）。
5. 帧式 ASCII 协议 `P,seq,mcu_ms,adc,mv,flags`，以 CRLF 结束。仅发 ADC/电压，不在固件中未经标定直接计算 g。
6. 无 printf 浮点与动态内存，适配 F103C8T6 资源规模。

## PC 端新增
- Tkinter 上位机，依赖 `pyserial`：COM 端口、读取速率、实时 ADC/mV、约60秒曲线、标定与 CSV 记录。
- 同时显示 g（克力）和 N，只有实际标定通过后才显示压力估计。
- 严格单调分段标定曲线；超出标定范围不外推。
- 录入 0g 点对应软件清零；储存 `calibration.json`，调节模拟模块增益后重新标定。

## 测试层级
- Python 协议/标定单元测试：6 项通过。
- Clang ARM Cortex-M3 对 19 个 C/汇编文件进行编译检查，通过；用于本地交叉编译验证，**不是 Keil ARMCC5 原厂编译结果**。
- 截至当前版本尚未实物上电、测试串口或验证压力精度；实际硬件仍需要测试。
