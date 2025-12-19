# OmniLocation

**分布式多设备定位模拟系统**

OmniLocation 是一个基于 **地瓜机器人 RDK X5** 构建的无头定位模拟基站。系统采用 B/S 架构，通过 Web 界面统一管理，支持对多台 iOS 和 Android 设备进行同步或独立的 GPS 轨迹模拟。

## 核心功能

*   **集中管理**: 通过 Web 控制台统一调度所有连接设备
*   **iOS 支持**: 适配 iOS 17+，利用 Tunneld/RSD 实现无线与 USB 的自动发现及控制
*   **Android 支持**: 基于 ADB 实现控制与定位模拟
*   **智能模拟**:
    *   支持 GPX 路径解析与回放
    *   支持设定目标时长与倍速播放
    *   内置防作弊 Jitter 算法（高斯分布随机偏移）
*   **可视化**: 集成天地图，实时展示设备轨迹与当前位置

## 快速开始

### 一键安装

本系统支持 **macOS**（开发/测试）和 **Ubuntu/RDK X5**（生产环境）

在终端中运行以下命令即可完成环境配置、依赖安装及服务启动：

```bash
curl -sSL https://raw.githubusercontent.com/JasperXzy/OmniLocation/main/install.sh | bash
```

*   **macOS**: 自动配置 Python 虚拟环境并注册 LaunchAgent 服务
*   **Linux**: 自动编译底层驱动 (Netmuxd)，配置 Systemd 服务并设置开机自启

### 安装后配置

1.  **修改配置**:
    安装完成后，请编辑安装目录下的 `.env` 文件，填入地图 API 密钥
    ```bash
    TIANDITU_KEY=天地图API密钥
    HOST=0.0.0.0
    PORT=5005
    ```

2.  **重启服务**:
    *   **macOS**: `launchctl kickstart -k gui/$(id -u)/com.omnilocation.web`
    *   **Linux**: `sudo systemctl restart omni-web`

3.  **访问控制台**:
    在浏览器中打开 `http://localhost:5005` 或 `http://<设备IP>:5005`

## 服务管理

### macOS

*   **停止服务**:
    ```bash
    launchctl unload ~/Library/LaunchAgents/com.omnilocation.web.plist
    sudo launchctl unload /Library/LaunchDaemons/com.omnilocation.tunneld.plist
    ```
*   **查看日志**:
    ```bash
    tail -f ~/Projects/OmniLocation/logs/web.stderr.log
    ```

### Linux

*   **停止服务**:
    ```bash
    sudo systemctl stop omni-web omni-tunneld
    ```
*   **查看日志**:
    ```bash
    journalctl -u omni-web -f
    ```

### 卸载

如需移除本系统及所有相关服务，在安装目录下运行卸载脚本：

```bash
./uninstall.sh
```
