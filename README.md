# 企业微信 Channel for CoPaw

让 CoPaw AI 助手通过企业微信与你对话。

---

## 🚀 快速开始

### 1. 安装

```bash
cd /home/wecon-copaw/wecom_app_channel
python3 install.py
```

### 2. 企业微信配置

1. 登录 [企业微信管理后台](https://work.weixin.qq.com/)
2. 创建自建应用，获取 `AgentId` 和 `Secret`
3. 配置回调 URL：
   - **URL**: `http://你的服务器IP:8088/wecom-app`
   - **Token**: 自定义字符串
   - **EncodingAESKey**: 随机生成

### 3. CoPaw 配置

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
      "encodingAESKey": "你的EncodingAESKey",
      "webhookPath": "/wecom-app"
    }
  },
  "show_tool_details": false
}
```

**配置项说明**：

| 字段 | 说明 | 来源 |
|------|------|------|
| `corpId` | 企业 ID | 企业微信后台 → 我的企业 |
| `corpSecret` | 应用 Secret | 应用详情页 → Secret |
| `agentId` | 应用 ID | 应用详情页 → AgentId |
| `token` | 回调 Token | 步骤 2 自定义的 |
| `encodingAESKey` | 加密密钥 | 步骤 2 随机生成的 |

### 4. 启动服务

```bash
pkill -f "copaw app"
/root/.copaw/venv/bin/copaw app --host 0.0.0.0 --port 8088 &
```

### 5. 测试

在企业微信应用中发送：`你好`

---

## ✨ 功能特性

- ✅ 消息收发
- ✅ 工具调用（文件操作、命令行、网络请求等）
- ✅ 自动过滤 thinking 内容
- ✅ 隐藏工具调用详情（只显示最终回复）

---

## ❓ 常见问题

**Q: 验证失败？**
- 检查 URL 是否正确
- 确认服务已启动
- 查看日志：`tail -f /tmp/copaw.log`

**Q: 收不到回复？**
- 检查 `enabled` 是否为 `true`
- 确认配置正确
- 查看日志错误

**Q: 显示工具调用详情？**
- 确认 `show_tool_details: false`
- 重启服务

---

## 📁 文件说明

```
/home/wecon-copaw/wecom_app_channel/
├── wecom_app.py      # Channel 主模块
├── install.py        # 安装脚本
├── README.md         # 本文档
└── SKILL.md          # 技能说明
```

---

## 📖 详细文档

完整安装指南、配置说明和故障排查见：[GitHub 仓库](#)

---

**版本**: 2.0.0  
**更新日期**: 2026-03-03
