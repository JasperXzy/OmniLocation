# OmniLocation

**分布式多设备定位模拟系统**

基于 **地瓜机器人 RDK X5** 构建的便携式无头基站，通过 Web 界面统一管理，支持多台 iOS/Android 设备的高并发 GPS 轨迹模拟。

## 核心特性

*   **集中管理**: B/S 架构，通过 Web 控制台统一调度
*   **iOS 支持**: 适配 iOS 17+，利用 Tunneld/RSD 实现无线/USB 自动发现与控制
*   **Android 支持**: 基于 ADB 实现控制
*   **智能模拟**:
    *   GPX 路径解析与回放
    *   目标时间与时间倍率调整
    *   防作弊 Jitter 算法 (高斯分布随机偏移)
*   **可视化**: 集成天地图，实时展示设备轨迹与位置

## 快速开始

### 环境要求
*   Python 3.8+
*   iOS/Android 设备需开启开发者模式

### 安装依赖
```bash
pip install -r requirements.txt
```

### 启动服务
1. 确保 `tunneld` 守护进程已运行 (用于 iOS 发现):
   ```bash
   sudo python3 -m pymobiledevice3 remote tunneld
   ```

2. 启动 OmniLocation Web 服务:
   ```bash
   sudo python3 run.py
   ```

3. 访问浏览器: `http://localhost:5000` 或 `http://<IP>:5000`
