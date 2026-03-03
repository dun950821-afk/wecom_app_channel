#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信 Channel 安装脚本
自动安装 wecom-app channel 到 CoPaw
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path


def get_copaw_dir() -> Path:
    return Path(os.environ.get("COPAW_WORKING_DIR", "~/.copaw")).expanduser().resolve()


def get_copaw_venv() -> Path:
    return get_copaw_dir() / "venv"


def get_custom_channels_dir() -> Path:
    return get_copaw_dir() / "custom_channels"


def install_dependencies():
    """安装依赖"""
    print("📦 安装依赖...")
    venv = get_copaw_venv()

    if not venv.exists():
        print(f"❌ CoPaw 虚拟环境不存在：{venv}")
        return False

    pip = venv / "bin" / "pip"
    if not pip.exists():
        pip = venv / "Scripts" / "pip.exe"

    try:
        subprocess.run([str(pip), "install", "pycryptodome"], check=True)
        print("   ✅ pycryptodome 安装成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 依赖安装失败：{e}")
        return False


def install_channel_module():
    """安装 Channel 模块"""
    print("\n📁 安装 Channel 模块...")
    script_dir = Path(__file__).parent.resolve()
    src_file = script_dir / "wecom_app.py"

    if not src_file.exists():
        print(f"❌ 找不到源文件：{src_file}")
        return False

    target_dir = get_custom_channels_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "wecom_app.py"
    shutil.copy2(src_file, target_file)

    print(f"   ✅ 已复制到：{target_file}")
    return True


def patch_copaw_app():
    """修改 CoPaw 应用代码添加 webhook 路由"""
    print("\n🔧 配置 Webhook 路由...")
    venv = get_copaw_venv()
    app_file = venv / "lib" / "python3.12" / "site-packages" / "copaw" / "app" / "_app.py"

    if not app_file.exists():
        for py_ver in ["python3.11", "python3.10", "python3.9"]:
            alt_path = venv / "lib" / py_ver / "site-packages" / "copaw" / "app" / "_app.py"
            if alt_path.exists():
                app_file = alt_path
                break

    if not app_file.exists():
        print(f"❌ 找不到 CoPaw 应用文件")
        return False

    with open(app_file, 'r', encoding='utf-8') as f:
        content = f.read()

    if "wecom-webhook" in content or "wecom_webhook_get" in content:
        print("   ✅ Webhook 路由已配置")
        return True

    backup_file = app_file.with_suffix(".py.bak")
    shutil.copy2(app_file, backup_file)
    print(f"   📄 已备份到：{backup_file}")

    # 添加导入
    content = content.replace(
        "from fastapi import FastAPI, HTTPException",
        "from fastapi import FastAPI, HTTPException, Request\nfrom fastapi.responses import PlainTextResponse"
    )

    # 添加 webhook 路由
    fastapi_section = '''app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)'''

    webhook_code = '''
# ========================================
# 企业微信 webhook 路由
# ========================================
_wecom_channel_instance = None

@app.get("/wecom-app")
async def wecom_webhook_get(request: Request):
    """处理企业微信 URL 验证。"""
    global _wecom_channel_instance
    if _wecom_channel_instance is None:
        return PlainTextResponse("Channel not initialized", status_code=500)
    query = dict(request.query_params)
    status_code, body = await _wecom_channel_instance.handle_webhook(
        method="GET", path="/wecom-app", query=query, body=b""
    )
    return PlainTextResponse(content=body, status_code=status_code)

@app.post("/wecom-app")
async def wecom_webhook_post(request: Request):
    """处理企业微信消息回调。"""
    global _wecom_channel_instance
    if _wecom_channel_instance is None:
        return PlainTextResponse("Channel not initialized", status_code=500)
    query = dict(request.query_params)
    body = await request.body()
    status_code, resp_body = await _wecom_channel_instance.handle_webhook(
        method="POST", path="/wecom-app", query=query, body=body
    )
    return PlainTextResponse(content=resp_body, status_code=status_code)

'''
    content = content.replace(fastapi_section, fastapi_section + webhook_code)

    # 在 lifespan 中设置 channel 实例
    yield_old = '''    try:
        yield
    finally:'''

    yield_new = '''    # 设置 wecom-app channel 实例
    global _wecom_channel_instance
    for ch in channel_manager.channels:
        if getattr(ch, "channel", None) == "wecom-app":
            _wecom_channel_instance = ch
            logger.info("wecom-webhook: channel set, enabled=%s", ch.enabled)
            break

    try:
        yield
    finally:'''

    content = content.replace(yield_old, yield_new)

    with open(app_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"   ✅ 已配置 Webhook 路由")
    return True


def patch_renderer():
    """修改 renderer.py 过滤 thinking 和工具调用详情"""
    print("\n🔧 配置 Renderer 过滤...")
    venv = get_copaw_venv()
    renderer_file = venv / "lib" / "python3.12" / "site-packages" / "copaw" / "app" / "channels" / "renderer.py"

    if not renderer_file.exists():
        for py_ver in ["python3.11", "python3.10", "python3.9"]:
            alt_path = venv / "lib" / py_ver / "site-packages" / "copaw" / "app" / "channels" / "renderer.py"
            if alt_path.exists():
                renderer_file = alt_path
                break

    if not renderer_file.exists():
        print(f"❌ 找不到 renderer.py 文件")
        return False

    with open(renderer_file, 'r', encoding='utf-8') as f:
        content = f.read()

    if "show_tool_details=False 时，完全隐藏工具调用" in content:
        print("   ✅ Renderer 已配置")
        return True

    backup_file = renderer_file.with_suffix(".py.bak")
    if not backup_file.exists():
        shutil.copy2(renderer_file, backup_file)
        print(f"   📄 已备份到：{backup_file}")

    # 1. 注释掉 thinking block
    thinking_old = '''if btype == "thinking" and b.get("thinking"):
                    result.append(TextContent(text=b["thinking"]))'''
    thinking_new = '''# 注释掉 thinking 内容的发送
                # if btype == "thinking" and b.get("thinking"):
                #     result.append(TextContent(text=b["thinking"]))'''
    content = content.replace(thinking_old, thinking_new)

    # 2. 添加 REASONING 过滤
    reasoning_old = '''if msg_type in (
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL_OUTPUT,
        ):
            parts = _parts_for_tool_output(content)'''
    reasoning_new = '''# 跳过 REASONING 类型的消息（thinking 内容）
        if msg_type == MessageType.REASONING:
            return []

        if msg_type in (
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL_OUTPUT,
        ):
            parts = _parts_for_tool_output(content)'''
    content = content.replace(reasoning_old, reasoning_new)

    with open(renderer_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"   ✅ 已配置 Renderer 过滤")
    return True


def print_config_guide():
    """打印配置指南"""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║                    🎉 安装完成！                                  ║
╠══════════════════════════════════════════════════════════════════╣
║  接下来请完成以下步骤：                                           ║
║                                                                   ║
║  1. 在 ~/.copaw/config.json 中添加配置：                         ║
║     "channels": {                                                 ║
║       "wecom-app": {                                              ║
║         "enabled": true,                                          ║
║         "corpId": "你的企业ID",                                  ║
║         "corpSecret": "你的应用Secret",                          ║
║         "agentId": 你的 AgentId,                                 ║
║         "token": "你的 Token",                                   ║
║         "encodingAESKey": "你的 EncodingAESKey"                  ║
║       }                                                           ║
║     },                                                            ║
║     "show_tool_details": false                                    ║
║                                                                   ║
║  2. 在企业微信后台配置回调地址：                                  ║
║     URL: http://你的服务器IP:8088/wecom-app                      ║
║                                                                   ║
║  3. 重启 CoPaw 服务：                                            ║
║     pkill -f "copaw app"                                         ║
║     /root/.copaw/venv/bin/copaw app --host 0.0.0.0 --port 8088 & ║
║                                                                   ║
╚══════════════════════════════════════════════════════════════════╝
""")


def main():
    print("=" * 60)
    print("   企业微信 Channel for CoPaw - 安装程序")
    print("=" * 60)

    copaw_dir = get_copaw_dir()
    if not copaw_dir.exists():
        print(f"❌ CoPaw 目录不存在：{copaw_dir}")
        sys.exit(1)

    print(f"📂 CoPaw 目录：{copaw_dir}")

    if not install_dependencies():
        sys.exit(1)

    if not install_channel_module():
        sys.exit(1)

    if not patch_copaw_app():
        sys.exit(1)

    if not patch_renderer():
        sys.exit(1)

    print_config_guide()


if __name__ == "__main__":
    main()
