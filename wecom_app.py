# -*- coding: utf-8 -*-
"""
企业微信自建应用 Channel for CoPaw

功能：
- 接收企业微信回调消息
- 主动发送消息给用户
- 自动过滤 thinking 内容和工具调用详情

配置示例 (config.json):
{
  "channels": {
    "wecom-app": {
      "enabled": true,
      "corpId": "your_corp_id",
      "corpSecret": "your_secret",
      "agentId": 1000001,
      "token": "your_token",
      "encodingAESKey": "your_aes_key",
      "webhookPath": "/wecom-app"
    }
  },
  "show_tool_details": false
}
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import struct
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import unquote

import aiohttp
import ssl as ssl_module
from Crypto.Cipher import AES

from copaw.app.channels.base import (
    BaseChannel,
    ContentType,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)
from copaw.app.channels.schema import ChannelType
from agentscope_runtime.engine.schemas.agent_schemas import TextContent

if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

logger = logging.getLogger(__name__)


class PKCS7Encoder:
    """PKCS7 编码/解码器"""
    block_size = 32

    @classmethod
    def encode(cls, data: bytes) -> bytes:
        pcount = cls.block_size - len(data) % cls.block_size
        return data + bytes([pcount] * pcount)

    @classmethod
    def decode(cls, data: bytes) -> bytes:
        pcount = data[-1]
        return data[:-pcount]


class WeComAppChannel(BaseChannel):
    """企业微信自建应用 Channel"""

    channel: ChannelType = "wecom-app"
    display_name = "企业微信自建应用"
    uses_manager_queue: bool = False

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool = False,
        corpId: str = "",
        corpSecret: str = "",
        agentId: int = 0,
        token: str = "",
        encodingAESKey: str = "",
        webhookPath: str = "/wecom-app",
        receiveId: str = "",
        welcomeText: str = "",
        bot_prefix: str = "",
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = False,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
        )
        self.enabled = enabled
        self.corpId = corpId
        self.corpSecret = corpSecret
        self.agentId = agentId
        self.token = token
        self.encodingAESKey = encodingAESKey
        self.webhookPath = webhookPath
        self.receiveId = receiveId or corpId
        self.welcomeText = welcomeText
        self.bot_prefix = bot_prefix or ""

        self._http: Optional[aiohttp.ClientSession] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._token_lock = asyncio.Lock()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        # AES 解密密钥
        self._aes_key = None
        if encodingAESKey:
            try:
                key_b64 = encodingAESKey + "=" * (4 - len(encodingAESKey) % 4)
                self._aes_key = base64.b64decode(key_b64)
            except Exception as e:
                logger.error(f"Failed to decode encodingAESKey: {e}")

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Any,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = False,
    ) -> "WeComAppChannel":
        """从配置创建实例"""
        cfg = config.__dict__ if hasattr(config, "__dict__") else (config if isinstance(config, dict) else {})

        return cls(
            process=process,
            enabled=cfg.get("enabled", False),
            corpId=cfg.get("corpId", ""),
            corpSecret=cfg.get("corpSecret", ""),
            agentId=cfg.get("agentId", 0),
            token=cfg.get("token", ""),
            encodingAESKey=cfg.get("encodingAESKey", ""),
            webhookPath=cfg.get("webhookPath", "/wecom-app"),
            receiveId=cfg.get("receiveId", ""),
            welcomeText=cfg.get("welcomeText", ""),
            bot_prefix=cfg.get("bot_prefix", ""),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
        )

    @classmethod
    def from_env(cls, process: ProcessHandler, on_reply_sent: OnReplySent = None) -> "WeComAppChannel":
        """从环境变量创建实例"""
        return cls(
            process=process,
            enabled=os.getenv("WECOM_APP_ENABLED", "0") == "1",
            corpId=os.getenv("WECOM_APP_CORP_ID", ""),
            corpSecret=os.getenv("WECOM_APP_CORP_SECRET", ""),
            agentId=int(os.getenv("WECOM_APP_AGENT_ID", "0")),
            token=os.getenv("WECOM_APP_TOKEN", ""),
            encodingAESKey=os.getenv("WECOM_APP_ENCODING_AES_KEY", ""),
            webhookPath=os.getenv("WECOM_APP_WEBHOOK_PATH", "/wecom-app"),
            receiveId=os.getenv("WECOM_APP_RECEIVE_ID", ""),
            welcomeText=os.getenv("WECOM_APP_WELCOME_TEXT", ""),
            bot_prefix=os.getenv("WECOM_APP_BOT_PREFIX", ""),
            on_reply_sent=on_reply_sent,
        )

    def resolve_session_id(self, sender_id: str, channel_meta: Optional[Dict[str, Any]] = None) -> str:
        """生成 session_id"""
        return f"wecom-app:{sender_id}"

    def build_agent_request_from_native(self, native_payload: Any) -> "AgentRequest":
        """从原生消息构建 AgentRequest"""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = dict(payload.get("meta") or {})
        session_id = self.resolve_session_id(sender_id, meta)

        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        if hasattr(request, "channel_meta"):
            request.channel_meta = meta
        return request

    # ==================== 企业微信消息加解密 ====================

    def _verify_signature(self, signature: str, timestamp: str, nonce: str, echostr: str = "") -> bool:
        """验证企业微信签名"""
        if not self.token:
            return False
        items = [self.token, timestamp, nonce, echostr]
        items.sort()
        return hashlib.sha1("".join(items).encode()).hexdigest() == signature

    def _decrypt_message(self, encrypted: str) -> Optional[str]:
        """解密企业微信消息"""
        if not self._aes_key:
            logger.error("AES key not initialized")
            return None
        try:
            encrypted_bytes = base64.b64decode(encrypted)
            cipher = AES.new(self._aes_key, AES.MODE_CBC, self._aes_key[:16])
            decrypted = cipher.decrypt(encrypted_bytes)
            decrypted = PKCS7Encoder.decode(decrypted)
            msg_len = struct.unpack(">I", decrypted[16:20])[0]
            return decrypted[20:20 + msg_len].decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to decrypt message: {e}")
            return None

    def _encrypt_message(self, message: str) -> Optional[str]:
        """加密企业微信消息"""
        if not self._aes_key:
            return None
        try:
            random_bytes = secrets.token_bytes(16)
            msg_bytes = message.encode("utf-8")
            msg_len = struct.pack(">I", len(msg_bytes))
            receive_id = self.receiveId.encode("utf-8")
            content = PKCS7Encoder.encode(random_bytes + msg_len + msg_bytes + receive_id)
            cipher = AES.new(self._aes_key, AES.MODE_CBC, self._aes_key[:16])
            encrypted = cipher.encrypt(content)
            return base64.b64encode(encrypted).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to encrypt message: {e}")
            return None

    def _generate_signature(self, timestamp: str, nonce: str, encrypted: str) -> str:
        """生成签名"""
        items = [self.token, timestamp, nonce, encrypted]
        items.sort()
        return hashlib.sha1("".join(items).encode()).hexdigest()

    # ==================== Webhook 处理 ====================

    async def handle_webhook(self, method: str, path: str, query: Dict[str, str], body: bytes) -> tuple[int, bytes]:
        """处理 webhook 请求"""
        if not self.enabled or path != self.webhookPath:
            return 404, b"Not Found"

        if method == "GET":
            return await self._handle_verification(query)
        elif method == "POST":
            return await self._handle_callback(query, body)
        return 405, b"Method Not Allowed"

    async def _handle_verification(self, query: Dict[str, str]) -> tuple[int, bytes]:
        """处理企业微信 URL 验证"""
        msg_signature = query.get("msg_signature", "")
        timestamp = query.get("timestamp", "")
        nonce = query.get("nonce", "")
        echostr = query.get("echostr", "")

        logger.info(f"wecom-app verification: signature={msg_signature[:20]}...")

        if not self._verify_signature(msg_signature, timestamp, nonce, echostr):
            logger.warning("wecom-app verification: signature mismatch")
            return 403, b"Signature verification failed"

        decrypted = self._decrypt_message(unquote(echostr))
        if decrypted:
            logger.info(f"wecom-app verification success")
            return 200, decrypted.encode("utf-8")

        logger.error("wecom-app verification: failed to decrypt echostr")
        return 500, b"Decryption failed"

    async def _handle_callback(self, query: Dict[str, str], body: bytes) -> tuple[int, bytes]:
        """处理企业微信消息回调"""
        msg_signature = query.get("msg_signature", "")
        timestamp = query.get("timestamp", "")
        nonce = query.get("nonce", "")

        try:
            root = ET.fromstring(body.decode("utf-8"))
            encrypt = root.find("Encrypt")
            if encrypt is None:
                return 200, b"success"
            encrypted = encrypt.text
        except ET.ParseError as e:
            logger.error(f"wecom-app callback: XML parse error: {e}")
            return 400, b"Invalid XML"

        if not self._verify_signature(msg_signature, timestamp, nonce, encrypted):
            logger.warning("wecom-app callback: signature mismatch")
            return 403, b"Signature verification failed"

        decrypted = self._decrypt_message(encrypted)
        if not decrypted:
            logger.error("wecom-app callback: decryption failed")
            return 500, b"Decryption failed"

        try:
            msg_root = ET.fromstring(decrypted)
            msg_type = msg_root.find("MsgType")
            from_user = msg_root.find("FromUserName")
            to_user = msg_root.find("ToUserName")

            msg_type = msg_type.text if msg_type is not None else ""
            from_user = from_user.text if from_user is not None else ""
            to_user = to_user.text if to_user is not None else ""

            logger.info(f"wecom-app message: type={msg_type} from={from_user}")

            if msg_type == "text":
                content_elem = msg_root.find("Content")
                content = content_elem.text if content_elem is not None else ""

                native = {
                    "channel_id": self.channel,
                    "sender_id": from_user,
                    "content_parts": [{"type": "text", "text": content}],
                    "meta": {"msg_type": msg_type, "to_user": to_user},
                }

                if self._loop:
                    asyncio.run_coroutine_threadsafe(self._process_message(native), self._loop)

            elif msg_type == "event":
                event_elem = msg_root.find("Event")
                event = event_elem.text if event_elem is not None else ""
                logger.info(f"wecom-app event: {event}")
                # 进入应用事件已禁用欢迎语

        except ET.ParseError as e:
            logger.error(f"wecom-app callback: message XML parse error: {e}")

        return 200, b"success"

    def _message_to_content_parts(self, message: Any) -> List[OutgoingContentPart]:
        """将消息转换为内容部件，过滤 thinking 内容"""
        parts = super()._message_to_content_parts(message)
        filtered_parts = []

        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT:
                text = getattr(p, "text", "") or ""
                if text.strip().startswith("<thinking>") or text.strip().startswith("💭"):
                    continue
                if "</thinking>" in text:
                    after_thinking = text.split("</thinking>")[-1].strip()
                    if after_thinking:
                        filtered_parts.append(TextContent(text=after_thinking))
                    continue
            filtered_parts.append(p)

        return filtered_parts

    async def _process_message(self, native: Dict[str, Any]) -> None:
        """处理接收到的消息"""
        try:
            request = self.build_agent_request_from_native(native)
            parts: List[OutgoingContentPart] = []

            async for event in self._process(request):
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)
                if obj == "message" and status:
                    from agentscope_runtime.engine.schemas.agent_schemas import RunStatus
                    if status == RunStatus.Completed:
                        msg_parts = self._message_to_content_parts(event)
                        parts.extend(msg_parts)

            if parts:
                sender_id = native.get("sender_id", "")
                await self.send_content_parts(sender_id, parts, native.get("meta"))

        except Exception as e:
            logger.error(f"wecom-app process message error: {e}")

    # ==================== 主动发送消息 ====================

    async def _get_access_token(self) -> Optional[str]:
        """获取企业微信 access_token"""
        if not self.corpId or not self.corpSecret:
            logger.error("wecom-app: corpId or corpSecret not configured")
            return None

        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        async with self._token_lock:
            now = time.time()
            if self._access_token and now < self._token_expires_at:
                return self._access_token

            url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.corpId}&corpsecret={self.corpSecret}"

            try:
                async with self._http.get(url) as resp:
                    data = await resp.json()
                    if data.get("errcode", 0) != 0:
                        logger.error(f"wecom-app gettoken error: {data}")
                        return None

                    self._access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 7200)
                    self._token_expires_at = now + expires_in - 300
                    logger.info("wecom-app: access_token obtained")
                    return self._access_token
            except Exception as e:
                logger.error(f"wecom-app gettoken failed: {e}")
                return None

    async def send(self, to_handle: str, text: str, meta: Optional[Dict[str, Any]] = None) -> None:
        """主动发送消息给用户"""
        if not self.enabled or self._http is None:
            return

        access_token = await self._get_access_token()
        if not access_token:
            logger.error("wecom-app: failed to get access_token")
            return

        user_id = to_handle.split(":")[-1] if ":" in to_handle else to_handle
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"

        payload = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": self.agentId,
            "text": {"content": text},
            "safe": 0,
        }

        logger.info(f"wecom-app send: user={user_id} text_len={len(text)}")

        try:
            async with self._http.post(url, json=payload) as resp:
                data = await resp.json()
                if data.get("errcode", 0) != 0:
                    logger.error(f"wecom-app send error: {data}")
                else:
                    logger.info(f"wecom-app send success: msgid={data.get('msgid')}")
        except Exception as e:
            logger.error(f"wecom-app send failed: {e}")

    async def send_content_parts(
        self, to_handle: str, parts: List[OutgoingContentPart], meta: Optional[Dict[str, Any]] = None
    ) -> None:
        """发送多条内容"""
        text_parts = []

        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
            elif t == ContentType.IMAGE:
                url = getattr(p, "image_url", "") or ""
                text_parts.append(f"[图片: {url[:50]}...]")
            elif t == ContentType.FILE:
                text_parts.append("[文件]")

        body = "\n".join(text_parts) if text_parts else ""
        if self.bot_prefix and body:
            body = self.bot_prefix + body

        if body:
            await self.send(to_handle, body, meta)

    # ==================== 生命周期 ====================

    async def start(self) -> None:
        """启动 channel"""
        if not self.enabled:
            logger.info("wecom-app: channel disabled")
            return

        if not self.corpId or not self.corpSecret:
            logger.warning("wecom-app: corpId or corpSecret not configured")

        self._loop = asyncio.get_running_loop()
        ssl_context = ssl_module.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl_module.CERT_NONE
        self._http = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context))

        logger.info(f"wecom-app channel started: webhook={self.webhookPath} agentId={self.agentId}")

    async def stop(self) -> None:
        """停止 channel"""
        if self._http:
            await self._http.close()
            self._http = None
        logger.info("wecom-app channel stopped")

    def get_webhook_path(self) -> Optional[str]:
        """返回 webhook 路径"""
        return self.webhookPath if self.enabled and self.webhookPath else None


def get_channel_class():
    """返回 Channel 类"""
    return WeComAppChannel
