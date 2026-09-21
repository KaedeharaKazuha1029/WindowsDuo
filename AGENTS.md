# AGENTS.md — AI 协作指南

面向在本仓库工作的 AI 编码代理（与人类贡献者）。改动前请先读完本文件，避免踩已知的坑。

## 项目是什么

本仓库是 WindowsDuo 的另一实现，当前贡献目标是把 Surface 定制版合并到上游 `KaedeharaKazuha1029/WindowsDuo` 的 `surface` 分支。

- `surface/`：面向 Surface Pro 等 Windows 二合一设备的纯 Windows 版本。
  - Windows 侧使用 PyQt6 QOpenGLWidget 全屏置顶悬浮层，通过 Windows 内置 Inclinometer 读取绝对姿态，GLSL 着色器实现逆投影 Duo 折叠效果（铰链=屏幕底边，间隙越大越模糊越暗，视线出界纯黑）。
  - 不依赖 ESP32 + MPU6050 外部硬件。
- `win/`：原 Windows + ESP32 实现，保留，勿删勿改。
- `esp32/`：ESP32 硬件版本，保留，勿删勿改。
- 需要 ESP32 + MPU6050 方案，请查看 `win/` 和 `esp32/` 目录。

## 目录结构
