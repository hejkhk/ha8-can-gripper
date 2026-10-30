# 文档索引

## 当前使用（2026-10-30）

- [统一 HA8 + 压力 UI、自动识别 COM、仓库结构](UNIFIED_APP_AND_COM_DISCOVERY_2026-10-30.md)
- [贴片压力验证与舵机电流—压力曲线](PRESSURE_HA8_INTEGRATION_2026-10-30.md)
- [官方 HA8 USB 串口连接](direct_usb_serial_mode.md)
- [F103 压力模块完整交接](../extensions/gripper-pressure-f103/docs/PROJECT_HANDOFF_2026-10-30.md)
- [F103 厂家电导与 AO 转换模型](../extensions/gripper-pressure-f103/docs/ao_converter_v3.md)

## HA8 算法与原理

- [夹持电流、动态扭矩与候选状态机](grip_current_torque.md)
- [电流和扭矩假设、验证限制](torque_current_notes.md)
- [官方 HA8 参考索引](HA8_official_reference.md)
- [功能/固件版本矩阵](FEATURE_MATRIX.md)

## 历史版本存档（不是当前接线和主程序）

- [原 HA8 V3.2 交接](PROJECT_HANDOFF_2026-10-16.md)
- [机械臂 CAN 旧接口](CAN_protocol_robot_arm.md)
- [CTS100M 旧桥配置](CTS100M_configuration.md)
- [STM32F103 旧 CAN 透明桥](STM32F103_bridge_mode.md)

**当前设备链路是两个独立 USB COM：HA8 官方转接板 + F103 压力 USB-TTL。** 不再把 STM32/CAN 当作 HA8 控制中间层。旧通信驱动已归档到仓库根目录 `legacy/`；历史记录保留。此前整理使用的若干原厂 PDF 未存进 GitHub（仅有描述、链接和摘录），请勿误认为原件存在。

- [一次实验会话标定、移除 FSR 后离线估算与蜗杆/夹口力学限制](ONE_TIME_FORCE_CALIBRATION_2026-10-30.md)：当前 V3.6 实验入口；注意仍不是安全闭环。
