# 统一错误处理系统

## 概述

OmniLocation 有统一的错误处理系统，提供：
- 分层异常类体系
- 全局 Flask 错误处理器
- 标准化的 JSON 错误响应
- 区分用户错误（4xx）和系统错误（5xx）

## 异常类层次结构

### 基础异常

```python
from core.exceptions import OmniLocationError

# 所有自定义异常的基类
raise OmniLocationError("Something went wrong", code="ERROR_CODE", status_code=500)
```

### 用户输入错误 (4xx)

#### ValidationError
用于表单验证失败、缺少必填字段等场景

```python
from core.exceptions import ValidationError

# 基本验证错误
raise ValidationError("Invalid email format", field="email")

# 缺少字段
raise ValidationError("Missing required field: username", field="username")
```

**响应示例:**
```json
{
  "error": "VALIDATION_ERROR",
  "message": "Invalid email format",
  "status": 400,
  "field": "email"
}
```

#### ResourceNotFoundError
请求的资源不存在时使用

```python
from core.exceptions import ResourceNotFoundError

raise ResourceNotFoundError("GPX file", "route_test.gpx")
raise ResourceNotFoundError("Device", "abc123def")
```

**响应示例:**
```json
{
  "error": "RESOURCE_NOT_FOUND",
  "message": "GPX file 'route_test.gpx' not found",
  "status": 404
}
```

#### InvalidFileError
文件上传验证失败时使用

```python
from core.exceptions import InvalidFileError

raise InvalidFileError("Only .gpx files are allowed", filename="test.txt")
raise InvalidFileError("File size exceeds limit", filename="large.gpx")
```

### 设备错误

#### DeviceNotFoundError
设备未找到或已断开连接

```python
from core.exceptions import DeviceNotFoundError

raise DeviceNotFoundError("abc123def456")
```

#### DeviceConnectionError
无法连接到设备

```python
from core.exceptions import DeviceConnectionError

raise DeviceConnectionError("abc123def", "Connection timeout")
raise DeviceConnectionError("xyz789abc", "Device is locked")
```

#### DeviceControlError
无法控制设备（如设置位置失败）

```python
from core.exceptions import DeviceControlError

raise DeviceControlError("abc123def", "set location", "Service unavailable")
```

#### NoDevicesAvailableError
没有可用设备进行模拟

```python
from core.exceptions import NoDevicesAvailableError

raise NoDevicesAvailableError()
```

### GPX 处理错误

#### GPXParseError
GPX 文件解析失败

```python
from core.exceptions import GPXParseError

raise GPXParseError("route.gpx", "Invalid XML format")
raise GPXParseError("track.gpx", "Missing required elements")
```

#### GPXEmptyError
GPX 文件不包含轨迹点

```python
from core.exceptions import GPXEmptyError

raise GPXEmptyError("empty_track.gpx")
```

### 模拟错误

#### SimulationAlreadyRunningError
尝试启动已在运行的模拟

```python
from core.exceptions import SimulationAlreadyRunningError

if self.active:
    raise SimulationAlreadyRunningError()
```

**响应示例:**
```json
{
  "error": "SIMULATION_ALREADY_RUNNING",
  "message": "Simulation is already running. Stop it before starting a new one.",
  "status": 409
}
```

#### SimulationNotRunningError
尝试停止未运行的模拟

```python
from core.exceptions import SimulationNotRunningError

if not self.active:
    raise SimulationNotRunningError()
```

### 系统错误 (5xx)

#### DatabaseError
数据库操作失败

```python
from core.exceptions import DatabaseError

raise DatabaseError("connection", "Unable to connect to database")
raise DatabaseError("query", "Timeout during SELECT operation")
```

#### ConfigurationError
系统配置错误

```python
from core.exceptions import ConfigurationError

raise ConfigurationError("Missing API key: TIANDITU_KEY", config_key="TIANDITU_KEY")
```

#### ServiceUnavailableError
依赖的服务不可用

```python
from core.exceptions import ServiceUnavailableError

raise ServiceUnavailableError("ADB Server", "Connection refused on port 5037")
```

## 全局错误处理器

系统会自动捕获所有异常并返回标准格式的 JSON 响应：

### 处理自定义异常
```python
@app.errorhandler(OmniLocationError)
def handle_omnilocation_error(error: OmniLocationError):
    return jsonify(error.to_dict()), error.status_code
```

### 处理 HTTP 异常
```python
@app.errorhandler(HTTPException)
def handle_http_exception(error: HTTPException):
    return jsonify({
        'error': error.name.upper().replace(' ', '_'),
        'message': error.description,
        'status': error.code
    }), error.code or 500
```

### 处理未预期的异常
```python
@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    logger.exception("Unexpected error: %s", str(error))
    return jsonify({
        'error': 'INTERNAL_SERVER_ERROR',
        'message': 'An unexpected error occurred.',
        'status': 500
    }), 500
```

## 客户端错误处理示例

### JavaScript

```javascript
async function startSimulation(params) {
    try {
        const response = await axios.post('/api/start', params);
        console.log('Success:', response.data);
    } catch (error) {
        if (error.response) {
            const { error: code, message, status } = error.response.data;
            
            // 根据错误代码处理
            switch (code) {
                case 'VALIDATION_ERROR':
                    alert(`验证错误: ${message}`);
                    break;
                case 'RESOURCE_NOT_FOUND':
                    alert(`资源未找到: ${message}`);
                    break;
                case 'SIMULATION_ALREADY_RUNNING':
                    alert('模拟已在运行，请先停止当前模拟');
                    break;
                case 'NO_DEVICES_AVAILABLE':
                    alert('没有可用设备，请连接设备后重试');
                    break;
                default:
                    alert(`错误: ${message}`);
            }
        }
    }
}
```

## 最佳实践

### 1. 选择正确的异常类型
- 用户输入问题 → `ValidationError`
- 资源不存在 → `ResourceNotFoundError`
- 设备问题 → `DeviceError` 系列
- 文件问题 → `GPXParseError` 或 `InvalidFileError`
- 系统问题 → `DatabaseError`、`ConfigurationError` 等

### 2. 提供清晰的错误消息
```python
# 不好
raise ValidationError("Invalid input")

# 好
raise ValidationError("Email must be in valid format (e.g., user@example.com)", field="email")
```

### 3. 包含上下文信息
```python
# 包含设备 ID
raise DeviceConnectionError(device_udid, "Connection timeout after 30 seconds")

# 包含文件名
raise GPXParseError(filename, "Missing required <trk> element")
```

### 4. 记录日志
```python
try:
    # 操作...
except Exception as e:
    logger.error("Failed to process GPX file %s: %s", filename, e)
    raise GPXParseError(filename, str(e))
```

## 测试

运行测试脚本验证错误处理系统：

```bash
python3 test_error_handling.py
```

## 错误代码参考表

| 错误代码 | HTTP状态 | 说明 |
|---------|---------|------|
| `VALIDATION_ERROR` | 400 | 用户输入验证失败 |
| `RESOURCE_NOT_FOUND` | 404 | 请求的资源不存在 |
| `INVALID_FILE` | 400 | 上传的文件无效 |
| `DEVICE_NOT_FOUND` | 404 | 设备未找到 |
| `DEVICE_CONNECTION_ERROR` | 500 | 设备连接失败 |
| `DEVICE_CONTROL_ERROR` | 500 | 设备控制失败 |
| `NO_DEVICES_AVAILABLE` | 500 | 无可用设备 |
| `GPX_PARSE_ERROR` | 400 | GPX文件解析失败 |
| `GPX_EMPTY` | 400 | GPX文件无轨迹点 |
| `SIMULATION_ALREADY_RUNNING` | 409 | 模拟已在运行 |
| `SIMULATION_NOT_RUNNING` | 400 | 模拟未运行 |
| `DATABASE_ERROR` | 500 | 数据库操作失败 |
| `CONFIGURATION_ERROR` | 500 | 系统配置错误 |
| `SERVICE_UNAVAILABLE` | 503 | 服务不可用 |
| `INTERNAL_SERVER_ERROR` | 500 | 未预期的错误 |
| `FILE_TOO_LARGE` | 413 | 文件超过大小限制 |

## 迁移指南

### 更新现有代码

1. **导入异常类**
   ```python
   from core.exceptions import ValidationError, ResourceNotFoundError, GPXParseError
   ```

2. **替换返回语句**
   ```python
   # 旧代码
   return jsonify({'error': 'File not found'}), 404
   
   # 新代码
   raise ResourceNotFoundError('GPX file', filename)
   ```

3. **处理异常传播**
   ```python
   # 旧代码
   try:
       handler.parse()
   except Exception as e:
       return jsonify({'error': str(e)}), 500
   
   # 新代码
   handler.parse()  # GPXParseError 会被自动捕获和处理
   ```
