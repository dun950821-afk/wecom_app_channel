---
name: wecom-app-channel
description: 企业微信自建应用 Channel
---

# 企业微信 Channel

让 CoPaw 通过企业微信与你对话。

## 安装

```bash
cd /home/wecon-copaw/wecom_app_channel
python3 install.py
```

## 配置

编辑 `~/.copaw/config.json`：

```json
{
  "channels": {
    "wecom-app": {
      "enabled": true,
      "corpId": "你的企业ID",
      "corpSecret": "你的应用Secret",
      "agentId": 1000001,
      "token": "你的Token",
      "encodingAESKey": "你的EncodingAESKey"
    }
  },
  "show_tool_details": false
}
```

## 企业微信后台

1. 创建自建应用
2. 配置回调 URL: `http://IP:8088/wecom-app`
3. 设置 Token 和 EncodingAESKey

## 启动

```bash
pkill -f "copaw app"
/root/.copaw/venv/bin/copaw app --host 0.0.0.0 --port 8088 &
```

## 测试

发送：`你好`

详细说明见 [README.md](README.md)
