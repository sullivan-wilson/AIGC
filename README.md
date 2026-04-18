# 🌌 AIGC 空间重构工作台 (AIGC Spatial Reconstruction System)

> 基于 Stable Diffusion XL 与 Segment Anything Model (SAM) 的端到端智能图像局部重绘工作流。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)
[![Vue.js](https://img.shields.io/badge/Vue.js-3.x-4FC08D.svg)](https://vuejs.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.x-EE4C2C.svg)](https://pytorch.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 📖 项目简介

本项目是一款**“零门槛、高精度、端到端”**的 Web 级 AIGC 图像重构平台。
有别于传统的矩形框选或粗糙的画笔涂抹，本系统引入了 Meta **SAM 视觉大模型**进行像素级智能图像分割，并以 **Stable Diffusion XL 1.0** 为生成基座，通过自研的前端图层混合引擎与后端的显存动态调度机制，实现了在普通消费级显卡上的双大模型本地并发。

支持**极端地貌重写**（如草地转沙漠）、**物理光影重构**（如夜景转白天）等高难度图像语义转换任务。

## ✨ 核心特性 (Core Features)

- 🎯 **一键智能感知 (SAM Integration):** 抛弃传统抠图，鼠标单点即可让 AI 瞬间计算出复杂物体的精准边缘遮罩 (Mask)。
- 🎨 **专业级图层引擎 (Advanced Masking):** 独创基于 HTML5 Canvas `Composite Operation` 的多层遮罩混合算法，支持**多点追加点选**与**橡皮擦微调**，彻底解决多次重叠导致的半透明颜色加深及渲染死锁问题。
- 🚀 **算力极限压榨 (VRAM Optimization):** 针对 8GB 显存的消费级显卡进行了极致优化。采用 `float16` 半精度量化与 `CPU Offload` 动态显存卸载技术，彻底解决双大模型并发导致的 OOM 及 `WinError 1450` 系统资源枯竭问题。
- 🌗 **暗黑极客 UI 与滑动对比 (Geek UX):** 采用原生 Glassmorphism (毛玻璃) 悬浮面板设计。内置**“原图 vs 重绘图”无缝滑动对比组件**，提供比肩商业级产品的极致视觉体验。
- 🔌 **前后端一体化极简部署:** 前端 Vue 静态化后由 FastAPI 直接挂载托管，单端口 (`8000`) 对外服务，完美适配局域网共享与 Ngrok/cpolar 内网穿透。

## 🏗️ 架构与技术栈

* **前端 (Frontend):** Vue 3, HTML5 Canvas API (Fabric.js), 原生 CSS 毛玻璃特效。
* **后端 (Backend):** FastAPI, Uvicorn, Python-multipart。
* **AIGC 引擎 (AI Models):** * 生成基座：`diffusers/stable-diffusion-xl-1.0-inpainting-0.1` (基于 HuggingFace Diffusers 管道)
    * 视觉分割：`facebook/sam-vit-base` (基于 Transformers 架构)

## ⚙️ 安装与运行指南

### 1. 环境准备
确保您的计算机具备以下基础环境：
* OS: Windows 10/11 或 Ubuntu 22.04
* GPU: NVIDIA RTX 3060 及以上级别（显存 >= 8GB）
* RAM: 系统内存 >= 16GB
* 环境: Python 3.10+

### 2. 克隆与依赖安装
```bash
# 克隆仓库
git clone [https://github.com/YourUsername/AIGC-Spatial-Reconstruction.git](https://github.com/YourUsername/AIGC-Spatial-Reconstruction.git)
cd AIGC-Spatial-Reconstruction

# 安装 Python 依赖
pip install -r requirements.txt
```
*(注：核心模型权重文件体积超 8GB，系统将在首次启动时自动通过 HuggingFace API 拉取并缓存，无需手动下载。)*

### 3. 一键启动服务
本项目已实现前端打包与后端挂载的融合，请直接在项目根目录运行：

```bash
# 务必不要添加 --reload 参数，以保障极限显存调度
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

启动成功后，在浏览器中访问：http://localhost:8000 即可进入工作台。

### 4. 公网演示部署 (内网穿透)
如需向异地用户或在移动端演示，推荐使用 cpolar/Ngrok：

```bash
# 在保持服务运行的情况下，开启新终端执行：
cpolar http 8000
```
复制终端输出的 HTTPS 链接即可进行全球公网访问。

## 🕹️ 使用工作流 (Workflow)
* **载入底图：** 在左侧工作区上传需要处理的图像。

* **AI 点选：** 点击开启智能识图，在画面中需要重绘的物体（例如建筑、天空）上点击，生成精准红色遮罩。

* **人工接管：** 使用左侧面板的【画笔】追加遮罩，或使用【橡皮擦】擦除多余的识别区域。

* **注入灵魂：** 输入英文的正向提示词 (Positive Prompt) 与反向提示词 (Negative Prompt)。

* **火力全开：** 调整参数。针对日夜转换等剧烈变化，建议将【重绘强度 (Strength)】拉满至 1.0，【服从度 (CFG Scale)】调至 10+。

* **见证奇迹：** 点击获取重绘数据，在右侧区域拖拽幕布，滑动对比生成前后的极度反差。

## 🤝 团队成员与致谢
感谢 Stability AI 提供的强大图像生成开源基座。

感谢 Meta AI 提供 Segment Anything 视觉分割模型。

本项目为 南京航空航天大学 AIGC 课程结项成果。


## 🚀 AIGC 项目快速启动与内网穿透指南

> 本文档用于记录从零启动项目并完成公网发布的标准流程。

### 🛠️ 第一步：启动核心后端服务（FastAPI）

在 IDE（如 Cursor / VS Code）中打开项目，开启一个新的终端。

1. 激活虚拟环境（如果尚未激活）：

```powershell
# Windows 环境
.\.venv312\Scripts\activate
```

2. 启动 Uvicorn 服务：

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

验证标准：终端显示 `Uvicorn running on http://0.0.0.0:8000`。  
本地测试：浏览器访问 `http://localhost:8000`，应能看到完整的 Vue 前端界面。

### 🌐 第二步：建立公网隧道（Cloudflare）

不要关闭后端终端，开启第二个终端并执行：

```powershell
.\cloudflared tunnel --url http://localhost:8000
```

在输出日志中寻找如下信息：

```text
Your quick Tunnel has been created! Visit it at:
https://your-unique-name.trycloudflare.com
```

将该 `https://...trycloudflare.com` 链接发送至手机或评委端进行测试。

### ⚠️ 开发者必读（保命守则）

1. **路由冲突检查（422 报错预警）**
   - 现象：访问根目录出现 `{"detail": ...}`。
   - 原因：`main.py` 中根路径路由（`@app.get("/")`）与静态挂载逻辑冲突，或被错误绑定到需要请求体的处理函数。
   - 解决：检查根路径处理逻辑，仅保留正确的根路由/静态挂载。

2. **静态文件导入（NameError 预警）**
   - 现象：报错 `NameError: name 'StaticFiles' is not defined`。
   - 解决：在 `main.py` 顶部确认包含：
     `from fastapi.staticfiles import StaticFiles`。

3. **环境稳定性（路演关键）**
   - 防止休眠：电脑设置为高性能模式，关闭自动睡眠。
   - 终端保护：运行 `cloudflared` 的窗口不要按 `Ctrl+C`。
   - 前端更新：修改 Vue 代码后，需重新执行 `npm run build`，再重启后端服务。

### 📁 核心路径说明

- 前端静态资源：`./dist`（由 `npm run build` 生成）
- 后端核心逻辑：`./main.py`
- 穿透执行程序：`./cloudflared.exe`（当前目录运行）
