# 文档索引（当前为官方 USB 串口直连）

**[项目完整交接文档（2026-10-16，V3.2-beta）](PROJECT_HANDOFF_2026-10-16.md)**：新开发者接手首先阅读；含硬件、代码、协议、夹持与自动抓取、安全风险、实机验收和后续任务。\n\n**当前接线优先查看：[direct_usb_serial_mode.md](direct_usb_serial_mode.md)**。现在不再经过 CAN/CTS100M/STM32。以下 CAN 文档保留用于历史集成参考，不作为当前 V3 调试配置。

这个目录集中保存机械臂集成和夹爪控制相关资料：

- [CAN_protocol_robot_arm.md](CAN_protocol_robot_arm.md)：机械臂集成端发送帧、角度查询、运动指令、调零。
- [CTS100M_configuration.md](CTS100M_configuration.md)：CTS100M 波特率、标准帧、滤波和终端连接。
- [HA8_official_reference.md](HA8_official_reference.md)：舵机官方资料、参数、原厂链接以及已上传手册索引。
- [torque_current_notes.md](torque_current_notes.md)：电流与扭矩估算的限制与抓稳检测建议。\n- [grip_current_torque.md](grip_current_torque.md)：V3.1 实验性动态扭矩插值、夹持状态机、阈值与操作步骤。

## 原始 PDF 归档

本项目此前使用过以下原厂 PDF：

- `HA8-U35H-M_官方技术文档.pdf`（HA8 官方特性曲线和通信协议）
- `FashionStar_Python_UART_SDK.pdf`（UART SDK）
- `CTS100M_应用手册_V1.04.pdf`（CTS100M 配置）
- `CTS100M_数据手册_V1.05.pdf`（CTS100M 硬件接口）

**说明：**当前 GitHub 连接仅提供文本上传及字符串形式的 Git blob 写入。本次首批 GitHub 提交收录了可直接使用的 Markdown 文档和参考链接；**上述原始 PDF 尚未写入仓库**，但在原工作文件中已经整理好，待具备二进制上传能力后补充。请勿把 Markdown 误认为 PDF 原件。

## 全功能测试进度

- [测试功能矩阵与固件兼容性说明](FEATURE_MATRIX.md)
- `v2.0-beta` 新增同步/异步、原始指令、寄存器写入和恢复用户数据的安全确认。
- 所有新功能只完成离线与模拟检查；在 HA8 实机上正式验收之前不得视为全部通过。

## 新增扩展：F103 薄膜压力监测

**[压力监测模块完整交接（2026-10-30，V3）](../extensions/gripper-pressure-f103/docs/PROJECT_HANDOFF_2026-10-30.md)**：包含 IMS003-C10A、AO 转换器、158kΩ 电路理论模型、PA1/USART1、独立 Windows 上位机、验证进度、安全限制与后续 HA8 集成计划。

此项目**当前不是** HA8 控制通路中的 STM32/CAN 桥；它是另一路独立的压力读取设备。
