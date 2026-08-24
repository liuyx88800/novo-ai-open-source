# -*- coding: utf-8 -*-
"""VOZEB 兼容后端路由（vz_studio 前端移植）。

依赖 main.py 的基础设施（LLM / 图片 / 视频 / 计费 / 存储），在 main.py 末尾
`import vz_routes` 注册。请勿独立运行。
"""

import asyncio
import base64
import functools
import io
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
import hashlib
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, Response, StreamingResponse

from main import (
    app,
    DATA_DIR,
    CANVAS_DIR,
    AGENT_IMAGE_DEFAULT_MODEL,
    AGENT_VIDEO_DEFAULT_MODEL,
    AGENT_PLAN_SYSTEM_PROMPT,
    CHAT_REQUEST_TIMEOUT,
    SSE_HEADERS,
    AIReference,
    CanvasLLMRequest,
    CanvasVideoRequest,
    OnlineImageRequest,
    _agent_asset_url,
    _agent_image_step,
    _agent_poll_image_task,
    _agent_ratio_to_size,
    _agent_text_step,
    _agent_video_step,
    authenticated_account_email,
    author_follower_count,
    author_following_count,
    canvas_case_cover,
    canvas_record,
    canvas_video,
    case_display_title,
    case_is_live,
    charge_chat_billing,
    clean_billing_email,
    create_canvas_image_task,
    ensure_billing_user,
    extract_canvas_assets,
    followed_emails,
    friendly_chat_error_detail,
    is_apimart_provider,
    list_canvases,
    load_auth_users,
    load_api_providers,
    load_billing_users,
    load_canvas_any,
    mirror_local_url_to_cos,
    normalize_case_category,
    normalize_case_tags,
    output_path_for,
    output_url_for,
    precheck_chat_billing,
    provider_env_key_value,
    public_billing_user,
    read_json_store,
    resolve_managed_chat_provider,
    save_canvas_light,
    set_follow,
    sse_event,
    text_from_chat_response,
    unwrap_apimart_response,
    write_json_store,
)

VZ_DATA_DIR = os.path.join(DATA_DIR, "vz")
VZ_CREATIVE_FILE = os.path.join(VZ_DATA_DIR, "creative.json")
VZ_DRAMA_FILE = os.path.join(VZ_DATA_DIR, "drama.json")
VZ_LOCKS = {"creative": __import__("threading").Lock(), "drama": __import__("threading").Lock()}

# 内存态：活动 Agent run（含 asyncio 队列）与生成任务缓存
VZ_RUNS: Dict[str, Dict[str, Any]] = {}
VZ_RUNS_LOCK = asyncio.Lock()
VZ_TASKS: Dict[str, Dict[str, Any]] = {}
VZ_TASKS_LOCK = asyncio.Lock()

_PLAN_SYSTEM_PROMPT = (
    AGENT_PLAN_SYSTEM_PROMPT
    + "\n\n这是『AI 创作』会话（无画布）。若用户需要图像/视频，请产出 kind=image / kind=video 步骤；"
    "若只是文案/创意/短剧剧本，产出 kind=text 步骤。请遵守现有 JSON 输出格式。"
    "\n\n[已选择技能]：当用户在本会话明确选择了创作技能（见 user 消息末尾的「已选择技能」清单）时，"
    "必须按该技能执行并产出完整产物：文案创作/短剧剧本技能必须产出 kind=text 步骤，把完整正文写入该步骤的 prompt；"
    "图像生成技能必须产出 kind=image 步骤；视频生成技能必须产出 kind=video 步骤。"
    "不得把明确要求生成完整内容（如“完整剧本”“完整文案”）的需求仅当作对话回复（action=chat 且无步骤）。"
)

_SKILLS = [
    {"id": "text-writer", "name": "文案创作", "description": "生成营销文案、短剧剧本、创意脚本等文本内容。", "action": "generate", "workspaces": ["chat", "drama"]},
    {"id": "image-creation", "name": "图像生成", "description": "根据描述生成匹配的图像（分镜、海报、概念图等）。", "action": "generate", "workspaces": ["chat", "drama"]},
    {"id": "video-creation", "name": "视频生成", "description": "根据描述生成短视频片段。", "action": "generate", "workspaces": ["chat", "drama"]},
    {"id": "drama-script", "name": "短剧剧本", "description": "把灵感扩展成短剧剧本并拆解分镜。", "action": "generate", "workspaces": ["drama"]},
]


def _vz_uuid(prefix: str = "vz") -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _vz_creative() -> Dict[str, Any]:
    os.makedirs(VZ_DATA_DIR, exist_ok=True)
    data = read_json_store(VZ_CREATIVE_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("conversations", {})
    data.setdefault("messages", {})
    data.setdefault("assets", {})
    data.setdefault("runs", {})
    data.setdefault("seq", {})
    return data


def _vz_save_creative(data: Dict[str, Any]):
    with VZ_LOCKS["creative"]:
        write_json_store(VZ_CREATIVE_FILE, data)


def _vz_drama() -> Dict[str, Any]:
    os.makedirs(VZ_DATA_DIR, exist_ok=True)
    data = read_json_store(VZ_DRAMA_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("projects", {})
    data.setdefault("versions", {})
    return data


def _vz_save_drama(data: Dict[str, Any]):
    with VZ_LOCKS["drama"]:
        write_json_store(VZ_DRAMA_FILE, data)


def _points_headers(email: str) -> Dict[str, str]:
    try:
        with __import__("main").BILLING_LOCK:
            data = load_billing_users()
            user = ensure_billing_user(data, email)
        balance = int(round(max(0.0, float(user.get("balance") or 0))))
    except Exception:
        balance = 0
    return {"x-vozeb-pro-points-remaining": str(balance)}


def _public_user(email: str) -> Dict[str, Any]:
    auth_user = None
    for u in load_auth_users():
        if clean_billing_email(u.get("email") or "") == clean_billing_email(email):
            auth_user = u
            break
    try:
        with __import__("main").BILLING_LOCK:
            data = load_billing_users()
            b_user = ensure_billing_user(data, email)
        bill = public_billing_user(b_user)
    except Exception:
        bill = {}
    username = str((auth_user or {}).get("username") or (auth_user or {}).get("name") or email.split("@")[0] or "user")
    return {
        "id": str((auth_user or {}).get("id") or clean_billing_email(email)),
        "accountId": clean_billing_email(email),
        "username": username,
        "displayName": str((auth_user or {}).get("display_name") or (auth_user or {}).get("nickname") or username),
        "bio": str((auth_user or {}).get("bio") or ""),
        "avatarUrl": str((auth_user or {}).get("avatar_url") or ""),
        "email": email,
        "role": "admin" if (auth_user or {}).get("is_admin") or bill.get("vip_level", 0) >= 9 else "user",
        "adminPermissions": [],
        "status": "disabled" if bill.get("disabled") or (auth_user or {}).get("disabled") else "active",
        "planId": "vip" if bill.get("vip_level", 0) else "free",
        "planName": "VIP" if bill.get("vip_level", 0) else "免费版",
        "hasActivePlan": bool(bill.get("vip_level", 0)),
        # VOZEB calls this field pointsBalance, but Novo AI stores a CNY wallet.
        # Preserve cents so the embedded studio shows the same balance as the host.
        "pointsBalance": round(max(0.0, float(bill.get("balance") or 0)), 2),
        "mfaEnabled": False,
    }


def _vz_model_name(value: str) -> str:
    """前端逻辑模型 id 形如 channel::model，发给上游时只需真实模型名。"""
    text = str(value or "").strip()
    if "::" in text:
        return text.rsplit("::", 1)[1].strip()
    return text


def _vz_resolve_video_provider(model: str) -> str:
    """按视频模型名解析承载它的 API 渠道（provider id）。

    短剧/创作会话提交视频时 config 里只有模型名（如 seedance-2.0），
    provider_id 传空会被 canvas_video 解析成首选渠道——而首选渠道常是
    纯文本/图片渠道，导致上游报 "Videos API is not supported"。
    这里从真实 video_models 里反查：模型形如 channel::model 时直接用渠道段，
    否则找第一个含该模型且已配置 Key 的启用渠道；找不到返回空串沿用旧逻辑。
    """
    text = str(model or "").strip()
    if not text:
        return ""
    if "::" in text:
        return text.split("::", 1)[0].strip()
    requested = _vz_model_name(text)
    providers = [p for p in load_api_providers() if p.get("enabled", True)]
    with_key = [
        p for p in providers
        if requested in (p.get("video_models") or []) and provider_env_key_value(str(p.get("id") or ""))
    ]
    if with_key:
        return str(with_key[0].get("id") or "")
    no_key = [p for p in providers if requested in (p.get("video_models") or [])]
    if no_key:
        return str(no_key[0].get("id") or "")
    return ""


def _unique_model_names(models: List[str]) -> List[str]:
    seen = set()
    out = []
    for m in models or []:
        v = str(m or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _model_display_name(provider: Dict[str, Any], model: str, capability: str) -> str:
    if capability == "image":
        return str((provider.get("image_model_display_names") or {}).get(model) or "").strip() or model
    if capability == "video":
        return str((provider.get("video_model_display_names") or {}).get(model) or "").strip() or model
    return str((provider.get("chat_model_display_names") or {}).get(model) or "").strip() or model


def _public_settings() -> Dict[str, Any]:
    """从画布真实 API 渠道生成系统设置，让前端模型下拉展示实际部署的模型。"""
    providers = [p for p in load_api_providers() if p.get("enabled", True)]
    channels = []
    logical = []
    provider_by_id = {}
    default_models = {"textModel": "", "imageModel": "", "videoModel": ""}
    for provider in providers:
        pid = str(provider.get("id") or "").strip()
        if not pid:
            continue
        chat_models = _unique_model_names(provider.get("chat_models") or [])
        image_models = _unique_model_names(provider.get("image_models") or [])
        video_models = _unique_model_names(provider.get("video_models") or [])
        all_models = chat_models + image_models + video_models
        if not all_models:
            continue
        has_key = bool(provider_env_key_value(pid))
        protocol = str(provider.get("protocol") or "openai").strip().lower()
        api_format = "openai"
        channel = {
            "id": pid,
            "name": str(provider.get("name") or pid)[:40],
            "baseUrl": f"/api/ai/system/{pid}",
            "apiFormat": api_format,
            "enabled": True,
            "hasApiKey": has_key,
            "models": all_models,
            "advancedConfig": {
                "protocol": protocol if protocol in ("openai", "gemini", "apimart") else "auto",
                "textModel": str(provider.get("default_chat_model") or (chat_models[0] if chat_models else "")),
                "imageModel": str(provider.get("default_image_model") or (image_models[0] if image_models else "")),
                "videoModel": str(provider.get("default_video_model") or (video_models[0] if video_models else "")),
                "createPath": "/image/tasks",
                "queryPath": "/image/tasks/{{id}}",
            },
        }
        channels.append(channel)
        provider_by_id[pid] = provider
        for cap, models in (("text", chat_models), ("image", image_models), ("video", video_models)):
            if not models:
                continue
            if not default_models[f"{cap}Model"]:
                default_models[f"{cap}Model"] = models[0]
            for idx, model in enumerate(models):
                logical.append({
                    "id": f"{pid}::{model}",
                    "name": _model_display_name(provider, model, cap),
                    "capability": cap,
                    "enabled": True,
                    "bindings": [{"id": f"b-{pid}-{idx}", "channelId": pid, "upstreamModel": model, "enabled": True, "priority": 1}],
                })
    if not channels:
        fallback_model = AGENT_IMAGE_DEFAULT_MODEL
        channels = [{
            "id": "comfly", "name": "默认渠道", "baseUrl": "/api/ai/system/comfly",
            "apiFormat": "openai", "enabled": True, "hasApiKey": True, "models": [fallback_model],
            "advancedConfig": {"protocol": "auto", "textModel": "", "imageModel": fallback_model, "videoModel": "", "createPath": "/image/tasks", "queryPath": "/image/tasks/{{id}}"},
        }]
        default_models = {"textModel": "", "imageModel": fallback_model, "videoModel": ""}
    point_costs = {}
    for model in default_models.values():
        if model:
            point_costs[model] = 1
    return {
        "site": {"title": "NOVO AI"},
        "systemChannels": channels,
        "logicalModels": logical,
        "defaultModels": default_models,
        "modelPointCosts": point_costs,
        "generationConcurrency": {"agent": 2, "image": 4, "video": 1, "audio": 2, "text": 4, "render": 1},
        "generationDefaults": {"canvasImageCount": 1, "imageSize": "1:1", "imageQuality": "high", "imageCount": 1, "videoQuality": "720", "videoSeconds": 5},
    }


def _stable_url(value: Any) -> str:
    for key in ("serverUrl", "remoteUrl", "url", "dataUrl"):
        v = str((value or {}).get(key) or "")
        if v and not v.startswith("blob:") and not v.startswith("data:"):
            return v
    return ""


# ---------------------------------------------------------------- Auth / Session

@app.get("/api/auth/session")
async def vz_auth_session(request: Request):
    email = authenticated_account_email(request, required=False)
    payload: Dict[str, Any] = {"user": None, "install": {"firstAdminRequired": False, "database": {"healthy": True}}, "settings": _public_settings()}
    if email:
        payload["user"] = _public_user(email)
    return payload


@app.get("/api/auth/me")
async def vz_auth_me(request: Request):
    email = authenticated_account_email(request, required=False)
    return {"user": _public_user(email)}


# ---------------------------------------------------------------- Skills

@app.get("/api/agent/skills")
async def vz_agent_skills(request: Request, workspace: str = "all"):
    authenticated_account_email(request, required=False)
    skills = _SKILLS
    if workspace and workspace != "all":
        skills = [s for s in skills if workspace in (s.get("workspaces") or [])]
    return {"code": 0, "data": {"skills": skills}, "msg": "ok"}


# ---------------------------------------------------------------- System channel proxy
# 前端把每个系统渠道的 baseUrl 指向 /api/ai/system/{channel_id}，所有 OpenAI 兼容请求
# （chat/completions、images/generations、videos 等）都打到这个前缀。这里把请求按渠道
# 路由到画布真实 provider，并注入真实 API Key。


def _system_provider_by_channel(channel_id: str) -> Optional[Dict[str, Any]]:
    for provider in load_api_providers():
        if str(provider.get("id") or "").strip() == channel_id and provider.get("enabled", True):
            return provider
    return None


def _provider_openai_base(provider: Dict[str, Any]) -> str:
    base = str(provider.get("base_url") or "").strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=502, detail=f"渠道 {provider.get('id')} 未配置 Base URL")
    protocol = str(provider.get("protocol") or "openai").strip().lower()
    if protocol == "volcengine":
        return base if base.endswith("/api/v3") else base + "/api/v3"
    if protocol == "gemini":
        return base if base.endswith("/v1beta") else base + "/v1beta"
    return base if base.endswith("/v1") else base + "/v1"


def _provider_auth_headers(provider: Dict[str, Any]) -> Dict[str, str]:
    key = provider_env_key_value(str(provider.get("id") or "").strip())
    if not key:
        raise HTTPException(status_code=502, detail=f"渠道 {provider.get('name') or provider.get('id')} 未配置 API Key")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


@app.api_route("/api/ai/system/{channel_id}/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def vz_system_channel_proxy(channel_id: str, rest: str, request: Request):
    authenticated_account_email(request, required=False)
    provider = _system_provider_by_channel(channel_id)
    if not provider:
        raise HTTPException(status_code=404, detail="默认接口未配置或已停用")
    base = _provider_openai_base(provider)
    headers = _provider_auth_headers(provider)
    body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
    path = rest.strip("/")
    if not path:
        raise HTTPException(status_code=400, detail="缺少接口路径")
    # 前端 buildApiUrl 会在 baseUrl 后拼 /v1，这里剥掉协议前缀，避免与 base 的 /v1 重复
    for prefix in ("v1beta/", "v1beta", "v1/", "v1"):
        if path.startswith(prefix):
            path = path[len(prefix):].lstrip("/")
            break
    # 媒体代理路径 /api/ai/system/{cid}/_media?url=...
    if path == "_media":
        media_url = str(request.query_params.get("url") or "").strip()
        if not media_url:
            raise HTTPException(status_code=400, detail="缺少媒体地址")
        if media_url.startswith("/"):
            target = base.split("/v1")[0].rstrip("/") + media_url
        else:
            target = media_url
        timeout = httpx.Timeout(60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(request.method, target, headers={"Authorization": headers.get("Authorization", "")}, follow_redirects=True)
        return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type", "application/octet-stream"))
    target = f"{base}/{path}"
    if request.url.query:
        target += "?" + request.url.query
    timeout = httpx.Timeout(CHAT_REQUEST_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.request(request.method, target, headers=headers, content=body)
    proxy_headers = {}
    for key in ("content-type", "cache-control", "content-disposition"):
        if resp.headers.get(key):
            proxy_headers[key] = resp.headers.get(key)
    return Response(content=resp.content, status_code=resp.status_code, headers=proxy_headers)


# ---------------------------------------------------------------- Prompt optimization

async def _vz_llm_text(messages: List[Dict[str, Any]], email: str, request: Request, model: str = "", provider: str = "", ms_model: str = "") -> str:
    chat_base, chat_hdrs, resolved_model, llm_provider = resolve_managed_chat_provider(provider, model, ms_model)
    bill_prompt = "\n".join(str(m.get("content") or "") for m in messages)[:4000]
    bill_email = ""
    if email and email.strip():
        bill_email = precheck_chat_billing(request, bill_prompt, CanvasLLMRequest(message=bill_prompt or "ping", provider=provider, model=model, ms_model=ms_model, request_id=_vz_uuid("vzllm")), 1)
    async with httpx.AsyncClient(timeout=CHAT_REQUEST_TIMEOUT) as client:
        req_body: Dict[str, Any] = {"model": resolved_model, "messages": messages}
        if is_apimart_provider(llm_provider):
            req_body["stream"] = False
        response = await client.post(f"{chat_base}/chat/completions", headers=chat_hdrs, json=req_body)
        response.raise_for_status()
    raw = response.json()
    text = text_from_chat_response(raw).strip() if isinstance(raw, dict) else ""
    if bill_email:
        assistant_message = {
            "id": uuid.uuid4().hex,
            "role": "assistant",
            "content": text or "",
            "created_at": _now_ms(),
            "model": resolved_model,
            "provider": str(llm_provider.get("id") or ""),
            "raw_usage": (unwrap_apimart_response(raw) if isinstance(raw, dict) else {}).get("usage"),
        }
        charge_chat_billing(bill_email, assistant_message, llm_provider, bill_prompt, "creative", _vz_uuid("vzllm"))
    return text


def _extract_json_object(text: str) -> Dict[str, Any]:
    text = str(text or "")
    match = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    text = text.strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


@app.post("/api/agent/prompt-optimization")
async def vz_prompt_optimization(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    prompt = str(payload.get("prompt") or "")
    mode = str(payload.get("mode") or "agent")
    if not prompt:
        return {"data": {"prompt": prompt}, "msg": "ok"}
    mode_desc = {"agent": "AI 创作助手", "image": "图像生成", "video": "视频生成", "audio": "语音合成"}.get(mode, "AI 创作助手")
    messages = [
        {"role": "system", "content": f"你是专业的提示词优化助手（面向 {mode_desc}）。请把用户的描述改写成更精确、更有表现力的提示词，只输出优化后的提示词正文，不要任何解释。"},
        {"role": "user", "content": prompt},
    ]
    try:
        optimized = await _vz_llm_text(messages, email, request)
    except Exception:
        optimized = prompt
    return {"data": {"prompt": optimized.strip() or prompt}, "msg": "ok"}


# ---------------------------------------------------------------- Creative conversations

@app.get("/api/creative/conversations")
async def vz_conversations_list(request: Request, surface: str = "chat", source: str = "agent", status: str = "active", limit: int = 50, offset: int = 0, projectId: str = ""):
    email = authenticated_account_email(request, required=False)
    data = _vz_creative()
    items = list(data["conversations"].values())
    if email:
        items = [c for c in items if clean_billing_email(c.get("userId") or "") == clean_billing_email(email)]
    if surface and surface != "all":
        items = [c for c in items if c.get("surface") == surface]
    if source and source != "all":
        items = [c for c in items if c.get("source") == source]
    if status == "active":
        items = [c for c in items if c.get("status") == "active"]
    if projectId:
        items = [c for c in items if c.get("projectId") == projectId]
    items.sort(key=lambda c: float(c.get("updatedAt") or 0), reverse=True)
    total = len(items)
    page = items[offset:offset + limit]
    return {"code": 0, "data": {"conversations": page, "hasMore": offset + len(page) < total}, "msg": "ok"}


@app.get("/api/creative/conversations/{cid}")
async def vz_conversation_get(cid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_creative()
    conv = data["conversations"].get(cid)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"code": 0, "data": {"conversation": conv}, "msg": "ok"}


@app.get("/api/creative/conversations/{cid}/messages")
async def vz_conversation_messages(cid: str, request: Request, limit: int = 100, beforeSequence: int = 0):
    email = authenticated_account_email(request, required=False)
    data = _vz_creative()
    messages = list(data["messages"].get(cid) or [])
    if beforeSequence and beforeSequence > 0:
        messages = [m for m in messages if m.get("sequence", 0) < beforeSequence]
    messages.sort(key=lambda m: int(m.get("sequence") or 0))
    messages = messages[-int(limit):]
    return {"code": 0, "data": {"messages": messages}, "msg": "ok"}


@app.get("/api/creative/conversations/{cid}/assets")
async def vz_conversation_assets(cid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_creative()
    assets = list(data["assets"].get(cid) or [])
    assets.sort(key=lambda a: int(a.get("ordinal") or 0))
    return {"code": 0, "data": {"assets": assets}, "msg": "ok"}


@app.post("/api/creative/conversations")
async def vz_conversation_create(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    cid = _vz_uuid("con")
    now = _now_ms()
    conv = {
        "id": cid,
        "userId": email,
        "surface": str(payload.get("surface") or "chat"),
        "source": str(payload.get("source") or "agent"),
        "projectId": str(payload.get("projectId") or "") or None,
        "title": str(payload.get("title") or "新会话"),
        "status": "active",
        "contextSummary": "",
        "contextSummaryThroughSequence": 0,
        "createdAt": now,
        "updatedAt": now,
        "lastMessageAt": now,
    }
    data = _vz_creative()
    data["conversations"][cid] = conv
    data["seq"].setdefault(cid, 0)
    _vz_save_creative(data)
    return {"code": 0, "data": {"conversation": conv}, "msg": "ok"}


@app.patch("/api/creative/conversations/{cid}")
async def vz_conversation_patch(cid: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_creative()
    conv = data["conversations"].get(cid)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if "title" in payload and payload["title"] is not None:
        conv["title"] = str(payload["title"])
    if "status" in payload and payload["status"] in ("active", "archived"):
        conv["status"] = payload["status"]
    conv["updatedAt"] = _now_ms()
    _vz_save_creative(data)
    return {"code": 0, "data": {"conversation": conv}, "msg": "ok"}


@app.delete("/api/creative/conversations")
async def vz_conversations_delete(request: Request, ids: str = ""):
    email = authenticated_account_email(request, required=False)
    id_list = [x for x in str(ids or "").split(",") if x.strip()]
    data = _vz_creative()
    deleted = 0
    for cid in id_list:
        if cid in data["conversations"]:
            del data["conversations"][cid]
            data["messages"].pop(cid, None)
            data["assets"].pop(cid, None)
            deleted += 1
    _vz_save_creative(data)
    return {"code": 0, "data": {"deleted": deleted}, "msg": "ok"}


@app.post("/api/creative/assets")
async def vz_asset_upload(cid: str = Form(""), file: UploadFile = File(...), request: Request = None):
    email = authenticated_account_email(request, required=False)
    if not cid:
        raise HTTPException(status_code=400, detail="缺少会话编号")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件超过 25MB")
    fname = str(file.filename or "").strip() or f"asset_{uuid.uuid4().hex[:12]}"
    ext = os.path.splitext(fname)[1].lower() or ".bin"
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".mp3", ".wav", ".m4a", ".txt", ".md"):
        ext = ".bin"
    mime = (file.content_type or "").lower() or "application/octet-stream"
    storage_name = f"vz_asset_{uuid.uuid4().hex[:16]}{ext}"
    path = output_path_for(storage_name, "input")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)
    local_url = output_url_for(storage_name, "input")
    remote_url = await mirror_local_url_to_cos(local_url)
    url = remote_url or local_url
    asset_type = "text" if ext in (".txt", ".md") else "image" if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif") else "video" if ext in (".mp4", ".webm", ".mov") else "audio"
    data = _vz_creative()
    seq = data["seq"].setdefault(cid, 0) + 1
    data["seq"][cid] = seq
    now = _now_ms()
    asset = {
        "id": _vz_uuid("ast"),
        "userId": email,
        "conversationId": cid,
        "messageId": None,
        "sourceRunId": None,
        "sourceTaskId": None,
        "parentAssetId": None,
        "ordinal": seq,
        "type": asset_type,
        "status": "ready",
        "title": fname,
        "storageKind": "object",
        "storageKey": storage_name,
        "remoteUrl": url,
        "serverUrl": url,
        "mimeType": mime,
        "bytes": len(content),
        "metadata": {},
        "createdAt": now,
        "updatedAt": now,
    }
    data["assets"].setdefault(cid, []).append(asset)
    _vz_save_creative(data)
    return {"code": 0, "data": {"asset": asset}, "msg": "ok"}


# ---------------------------------------------------------------- Agent runs

def _vz_run_snapshot(run: Dict[str, Any]) -> Dict[str, Any]:
    tasks = []
    for t in run.get("tasks") or []:
        tasks.append({
            "id": t.get("id"),
            "title": t.get("title") or "",
            "type": t.get("type") or "text",
            "model": t.get("model") or "",
            "status": t.get("status") or "ready",
            "error": t.get("error") or "",
            "result_url": t.get("result_url") or "",
        })
    return {
        "id": run.get("id"),
        "email": run.get("email") or "",
        "conversationId": run.get("conversation_id") or "",
        "inputMessageId": run.get("input_message_id") or "",
        "assistantMessageId": run.get("assistant_message_id") or "",
        "status": run.get("status"),
        "surface": run.get("surface") or "chat",
        "projectId": run.get("project_id") or "",
        "prompt": run.get("prompt") or "",
        "referencedAssetIds": run.get("asset_ids") or [],
        "selectedSkillIds": run.get("skill_ids") or [],
        "requestedModelIds": run.get("model_ids") or [],
        "generationPreferences": run.get("preferences") or {},
        "createdAt": run.get("created_at"),
        "updatedAt": run.get("updated_at"),
        "assetIds": run.get("result_asset_ids") or [],
        "tasks": tasks,
        "cancellation": run.get("cancellation") or None,
        "error": run.get("error") or "",
    }


def _vz_run_emit(run: Dict[str, Any], ev_type: str, data: Any):
    event = {"type": ev_type, "data": data}
    run["event_log"].append(event)
    if "queue" in run:
        try:
            run["queue"].put_nowait(event)
        except Exception:
            pass


async def _vz_run_save(run: Dict[str, Any]):
    data = _vz_creative()
    data["runs"][run["id"]] = _vz_run_snapshot(run)
    _vz_save_creative(data)


async def _vz_run_persist_conversation(run: Dict[str, Any], status: str, reply: str):
    try:
        cid = run.get("conversation_id") or ""
        if not cid:
            return
        data = _vz_creative()
        seq = data["seq"].setdefault(cid, 0) + 1
        data["seq"][cid] = seq
        now = _now_ms()
        if not run.get("input_message_id"):
            run["input_message_id"] = _vz_uuid("msg")
            msg = {
                "id": run["input_message_id"], "conversationId": cid, "sequence": seq, "role": "user",
                "status": "completed", "content": run.get("prompt") or "", "runId": run["id"],
                "metadata": {}, "createdAt": now, "updatedAt": now,
            }
            data["messages"].setdefault(cid, []).append(msg)
        seq = data["seq"].setdefault(cid, 0) + 1
        data["seq"][cid] = seq
        run["assistant_message_id"] = _vz_uuid("msg")
        astatus = "completed" if status == "completed" else "failed" if status == "failed" else "cancelled"
        amsg = {
            "id": run["assistant_message_id"], "conversationId": cid, "sequence": seq, "role": "assistant",
            "status": astatus, "content": reply or (run.get("error") or ""), "runId": run["id"],
            "metadata": {}, "createdAt": now, "updatedAt": now,
        }
        data["messages"].setdefault(cid, []).append(amsg)
        if cid in data["conversations"]:
            data["conversations"][cid]["lastMessageAt"] = now
            data["conversations"][cid]["updatedAt"] = now
        else:
            data["conversations"][cid] = {
                "id": cid, "userId": run.get("email") or "", "surface": run.get("surface") or "chat",
                "source": "drama" if (run.get("surface") or "") == "drama" else "agent",
                "projectId": run.get("project_id") or None, "title": (run.get("prompt") or "")[:40],
                "status": "active", "contextSummary": "", "contextSummaryThroughSequence": 0,
                "createdAt": now, "updatedAt": now, "lastMessageAt": now,
            }
        _vz_save_creative(data)
    except Exception:
        pass


async def _vz_run_add_result_asset(run: Dict[str, Any], task: Dict[str, Any], url: str = "", text: str = ""):
    try:
        cid = run.get("conversation_id") or ""
        if not cid:
            return None
        data = _vz_creative()
        seq = data["seq"].setdefault(cid, 0) + 1
        data["seq"][cid] = seq
        now = _now_ms()
        task_type = task.get("type") or "text"
        if task_type == "text":
            asset = {
                "id": _vz_uuid("ast"), "userId": run.get("email") or "", "conversationId": cid,
                "messageId": None, "sourceRunId": run["id"], "sourceTaskId": task.get("id"),
                "parentAssetId": None, "ordinal": seq, "type": "text", "status": "ready",
                "title": task.get("title") or "文案", "textContent": text,
                "storageKind": "local", "storageKey": "", "remoteUrl": "", "serverUrl": "",
                "mimeType": "text/plain", "metadata": {}, "createdAt": now, "updatedAt": now,
            }
        else:
            asset = {
                "id": _vz_uuid("ast"), "userId": run.get("email") or "", "conversationId": cid,
                "messageId": None, "sourceRunId": run["id"], "sourceTaskId": task.get("id"),
                "parentAssetId": None, "ordinal": seq, "type": task_type, "status": "ready",
                "title": task.get("title") or "素材",
                "storageKind": "object", "storageKey": "", "remoteUrl": url, "serverUrl": url,
                "mimeType": "video/mp4" if task_type == "video" else "image/png",
                "metadata": {"ratio": task.get("ratio") or ""},
                "createdAt": now, "updatedAt": now,
            }
        data["assets"].setdefault(cid, []).append(asset)
        run.setdefault("result_asset_ids", []).append(asset["id"])
        _vz_save_creative(data)
        return asset
    except Exception:
        return None


async def _vz_run_mark_terminal(run: Dict[str, Any]):
    run["updated_at"] = _now_ms()
    _vz_run_emit(run, "run.snapshot", _vz_run_snapshot(run))
    await _vz_run_save(run)
    # 让 SSE 流能退出
    run.setdefault("status_finalized", True)


async def _vz_run_execute(run: Dict[str, Any]):
    email = run["email"]
    request = run["stub"]
    payload_obj = run["payload_obj"]
    try:
        _vz_run_emit(run, "run.planning", {})
        _vz_run_emit(run, "skills.selected", {"skills": run.get("skill_ids") or []})
        # 构造规划消息
        ref_notes = []
        data = _vz_creative()
        for aid in (run.get("asset_ids") or []):
            for cid, assets in data["assets"].items():
                for a in assets:
                    if a.get("id") == aid:
                        ref_notes.append(f"- 参考素材[{a.get('type')}]: {a.get('title')} {_stable_url(a) or a.get('textContent') or ''}")
                        break
        pref = run.get("preferences") or {}
        pref_note = ""
        if pref.get("mode"):
            pref_note = f"\n生成偏好：模式={pref.get('mode')}，图片偏好={json.dumps(pref.get('image') or {}, ensure_ascii=False)}，视频偏好={json.dumps(pref.get('video') or {}, ensure_ascii=False)}。"
        user_msg = run.get("prompt") or ""
        if ref_notes:
            user_msg += "\n\n参考素材：\n" + "\n".join(ref_notes)
        if pref_note:
            user_msg += pref_note
        # 携带当前短剧项目快照（drama 入口），让 Agent 理解项目上下文
        run_snapshot = run.get("snapshot") or None
        if isinstance(run_snapshot, dict) and run_snapshot:
            try:
                snap_json = json.dumps(run_snapshot, ensure_ascii=False)
                if len(snap_json) <= 12000:
                    user_msg += "\n\n当前短剧项目快照（JSON）：\n" + snap_json
            except Exception:
                pass
        # 携带本会话历史消息，让 Agent 理解上下文（排除 running、仅保留最近 24 条）
        history_msgs = []
        cid = run.get("conversation_id") or ""
        if cid:
            for m in (data.get("messages", {}).get(cid) or []):
                role = m.get("role")
                status = m.get("status")
                content = (m.get("content") or "").strip()
                if role in ("user", "assistant") and content and status != "running":
                    history_msgs.append({"role": role, "content": content[:2000]})
            history_msgs = history_msgs[-24:]
        # 携带用户选择的创作技能定义，让 Planner 知道按哪个技能产出步骤
        selected_skill_ids = run.get("skill_ids") or []
        skill_notes = []
        for sk in _SKILLS:
            if sk.get("id") in selected_skill_ids:
                skill_notes.append(f"- {sk.get('name')}（id={sk.get('id')}）：{sk.get('description') or ''}")
        if skill_notes:
            user_msg += "\n\n已选择技能：\n" + "\n".join(skill_notes) + "\n必须按所选技能执行并产出完整产物。"
        messages = [{"role": "system", "content": _PLAN_SYSTEM_PROMPT}]
        messages.extend(history_msgs)
        messages.append({"role": "user", "content": user_msg})
        raw_plan_text = await _vz_llm_text(messages, email, request, model=_vz_model_name(run.get("plan_model") or ""), provider=run.get("provider") or "comfly", ms_model=run.get("ms_model") or "")
        plan = _extract_json_object(raw_plan_text)
        reply_plan = str(plan.get("reply") or raw_plan_text or "已理解你的需求，开始创作。")
        steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
        if not steps and str(plan.get("action") or "").lower() != "steps":
            steps = []
        # 建立任务列表
        tasks = []
        for idx, s in enumerate(steps):
            if not isinstance(s, dict):
                continue
            kind = str(s.get("kind") or "text").lower()
            if kind not in ("text", "image", "video"):
                kind = "text"
            tasks.append({
                "id": _vz_uuid("task"),
                "index": idx,
                "title": str(s.get("title") or "") or ("文案" if kind == "text" else "图像" if kind == "image" else "视频"),
                "kind": kind,
                "type": kind,
                "def": s,
                "status": "ready",
                "error": "",
                "result_url": "",
                "result_text": "",
                "model": str(s.get("model") or s.get("image_model") or s.get("video_model") or ""),
                "ratio": str(s.get("ratio") or ""),
            })
        if not tasks:
            # 无生成步骤：直接返回对话回复
            _vz_run_emit(run, "run.planned", {"reply": reply_plan})
            run["reply"] = reply_plan
            run["status"] = "completed"
            run["stage"] = "finalizing"
            await _vz_run_persist_conversation(run, "completed", reply_plan)
            _vz_run_emit(run, "run.completed", {"reply": reply_plan})
            await _vz_run_mark_terminal(run)
            return
        run["tasks"] = tasks
        run["status"] = "running"
        run["stage"] = "executing"
        _vz_run_emit(run, "run.planned", {"reply": reply_plan})
        # 执行每个任务
        ref_urls = []
        for aid in (run.get("asset_ids") or []):
            for cid, assets in data["assets"].items():
                for a in assets:
                    if a.get("id") == aid:
                        u = _stable_url(a)
                        if u:
                            ref_urls.append(u)
                        break
        completed_texts = []
        result_summary = []
        for task in tasks:
            if run.get("cancelled"):
                task["status"] = "cancelled"
                continue
            task["status"] = "running"
            _vz_run_emit(run, "task.running", {"taskId": task["id"], "title": task["title"], "kind": task["kind"]})
            try:
                step_def = task["def"]
                if task["kind"] == "text":
                    text_out = await _agent_text_step(payload_obj, step_def, request)
                    task["result_text"] = text_out
                    task["status"] = "completed"
                    completed_texts.append(text_out)
                    _vz_run_emit(run, "task.completed", {"taskId": task["id"], "title": task["title"], "kind": "text", "message": f"「{task['title']}」已完成。", "text": text_out, "result_url": ""})
                    await _vz_run_add_result_asset(run, task, "", text_out)
                elif task["kind"] == "video":
                    url, provider_id = await _agent_video_step(payload_obj, step_def, "", "", request, email, ref_urls)
                    task["result_url"] = url
                    task["status"] = "completed"
                    result_summary.append(url)
                    _vz_run_emit(run, "task.completed", {"taskId": task["id"], "title": task["title"], "kind": "video", "message": f"「{task['title']}」已生成。", "text": "", "result_url": url})
                    await _vz_run_add_result_asset(run, task, url)
                else:
                    urls, size = await _agent_image_step(payload_obj, step_def, "", "", request, email, ref_urls, run)
                    task["result_url"] = urls[0] if urls else ""
                    task["status"] = "completed"
                    result_summary.extend(urls)
                    _vz_run_emit(run, "task.completed", {"taskId": task["id"], "title": task["title"], "kind": "image", "message": f"「{task['title']}」已生成。", "text": "", "result_url": task["result_url"]})
                    await _vz_run_add_result_asset(run, task, task["result_url"])
                run["updated_at"] = _now_ms()
            except HTTPException as exc:
                task["status"] = "failed"
                task["error"] = str(exc.detail)[:300]
                _vz_run_emit(run, "task.failed", {"taskId": task["id"], "title": task["title"], "error": str(exc.detail)[:300]})
                _vz_run_emit(run, "run.failed", {"message": str(exc.detail)[:300]})
                run["status"] = "failed"
                run["error"] = str(exc.detail)[:300]
                await _vz_run_persist_conversation(run, "failed", "")
                await _vz_run_mark_terminal(run)
                return
            except Exception as exc:
                task["status"] = "failed"
                task["error"] = str(exc)[:300]
                _vz_run_emit(run, "task.failed", {"taskId": task["id"], "title": task["title"], "error": str(exc)[:300]})
                _vz_run_emit(run, "run.failed", {"message": str(exc)[:300]})
                run["status"] = "failed"
                run["error"] = str(exc)[:300]
                await _vz_run_persist_conversation(run, "failed", "")
                await _vz_run_mark_terminal(run)
                return
        # 汇总回复
        parts = [reply_plan]
        if result_summary:
            parts.append(f"已生成 {len(result_summary)} 个素材，可在右侧查看。")
        if completed_texts:
            parts.append("\n\n" + "\n\n".join(completed_texts[:3]))
        reply = "\n".join(parts)
        run["reply"] = reply
        # project.handoff（drama 场景）
        if (run.get("surface") or "") == "drama":
            try:
                handoff_assets = []
                for cid, assets in data["assets"].items():
                    if cid == run.get("conversation_id"):
                        handoff_assets = assets
                        break
                handoff = {
                    "id": _vz_uuid("handoff"),
                    "sourceRunId": run["id"],
                    "conversationId": run.get("conversation_id") or "",
                    "surface": "drama",
                    "title": str(run.get("prompt") or "短剧")[:80],
                    "summary": reply_plan[:200],
                    "style": (pref.get("style") or "写实电影感"),
                    "ratio": (pref.get("ratio") or "9:16"),
                    "assetIds": [a.get("id") for a in handoff_assets if a.get("id")],
                    "assets": [{"id": a.get("id"), "type": a.get("type"), "title": a.get("title"), "textContent": a.get("textContent"), "serverUrl": a.get("serverUrl"), "remoteUrl": a.get("remoteUrl"), "storageKey": a.get("storageKey"), "mimeType": a.get("mimeType"), "width": a.get("width"), "height": a.get("height")} for a in handoff_assets],
                }
                _vz_run_emit(run, "project.handoff", handoff)
            except Exception:
                pass
        run["status"] = "completed"
        run["stage"] = "finalizing"
        _vz_run_emit(run, "run.review.passed", {"status": "passed", "issueCount": 0})
        await _vz_run_persist_conversation(run, "completed", reply)
        _vz_run_emit(run, "run.completed", {"reply": reply})
        await _vz_run_mark_terminal(run)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        run["status"] = "failed"
        run["error"] = str(exc)[:300]
        _vz_run_emit(run, "run.failed", {"message": str(exc)[:300]})
        await _vz_run_persist_conversation(run, "failed", "")
        await _vz_run_mark_terminal(run)


@app.post("/api/agent/runs")
async def vz_run_create(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    client_request_id = str(payload.get("clientRequestId") or "")
    surface = str(payload.get("surface") or "chat")
    if surface not in ("chat", "canvas", "drama"):
        surface = "chat"
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="创作需求不能为空")
    if len(prompt) > 4000:
        raise HTTPException(status_code=400, detail="创作需求过长")
    conversation_id = str(payload.get("conversationId") or "").strip()
    project_id = str(payload.get("projectId") or "").strip()
    if surface == "chat":
        project_id = ""
    asset_ids = []
    seen = set()
    for x in (payload.get("assetIds") or []):
        s = str(x or "")
        if s and s not in seen:
            asset_ids.append(s)
            seen.add(s)
    skill_ids = [str(x) for x in (payload.get("skillIds") or []) if str(x or "").strip()][:6]
    model_ids = [str(x) for x in (payload.get("modelIds") or []) if str(x or "").strip()][:6]
    preferences = payload.get("preferences") or {}
    if not isinstance(preferences, dict):
        preferences = {}
    snapshot = payload.get("snapshot") or None
    if snapshot is not None and not isinstance(snapshot, dict):
        snapshot = None
    # 找到或创建会话
    data = _vz_creative()
    if not conversation_id:
        cid = _vz_uuid("con")
        now = _now_ms()
        conversation = {
            "id": cid, "userId": email, "surface": surface, "source": "drama" if surface == "drama" else "agent",
            "projectId": project_id or None, "title": prompt[:40], "status": "active",
            "contextSummary": "", "contextSummaryThroughSequence": 0,
            "createdAt": now, "updatedAt": now, "lastMessageAt": now,
        }
        data["conversations"][cid] = conversation
        data["seq"].setdefault(cid, 0)
        _vz_save_creative(data)
        conversation_id = cid
    else:
        conversation = data["conversations"].get(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="会话不存在")
    # 建 run
    run_id = _vz_uuid("run")
    model_ids_join = _vz_model_name(model_ids[0]) if model_ids else ""
    payload_obj = CanvasLLMRequest(
        message=prompt, provider="comfly", model=model_ids_join, ms_model="",
        canvas_id="", conversation_id=conversation_id, request_id=run_id,
        skill_ids=skill_ids, model_ids=model_ids, preferences=preferences,
        references=[{"url": u} for u in []],
    )
    run = {
        "id": run_id,
        "email": email,
        "conversation_id": conversation_id,
        "surface": surface,
        "project_id": project_id,
        "prompt": prompt,
        "asset_ids": asset_ids,
        "skill_ids": skill_ids,
        "model_ids": model_ids,
        "preferences": preferences,
        "snapshot": snapshot,
        "provider": "comfly",
        "plan_model": model_ids_join,
        "ms_model": "",
        "payload_obj": payload_obj,
        "stub": request,
        "status": "planning",
        "stage": "planning",
        "stage_text": "正在理解你的创作需求",
        "paused": False,
        "cancelled": False,
        "queue": asyncio.Queue(),
        "event_log": [],
        "tasks": [],
        "error": "",
        "reply": "",
        "input_message_id": "",
        "assistant_message_id": "",
        "result_asset_ids": [],
        "cancellation": None,
        "created_at": _now_ms(),
        "updated_at": _now_ms(),
    }
    async with VZ_RUNS_LOCK:
        VZ_RUNS[run_id] = run
    asyncio.create_task(_vz_run_execute(run))
    return {"code": 0, "data": {"run": _vz_run_snapshot(run), "conversation": conversation, "created": True}, "msg": "ok"}


@app.get("/api/agent/runs/{run_id}")
async def vz_run_get(run_id: str, request: Request):
    email = authenticated_account_email(request, required=False)
    async with VZ_RUNS_LOCK:
        run = VZ_RUNS.get(run_id)
    if not run:
        data = _vz_creative()
        snap = data["runs"].get(run_id)
        if not snap:
            raise HTTPException(status_code=404, detail="任务不存在或已过期")
        if (snap.get("email") or "") != email:
            raise HTTPException(status_code=404, detail="任务不存在或已过期")
        return {"code": 0, "data": {"run": snap}, "msg": "ok"}
    if run["email"] != email:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return {"code": 0, "data": {"run": _vz_run_snapshot(run)}, "msg": "ok"}


@app.get("/api/agent/runs")
async def vz_run_list(request: Request, surface: str = "chat", status: str = "active", limit: int = 100, projectId: str = "", conversationId: str = ""):
    email = authenticated_account_email(request, required=False)
    data = _vz_creative()
    items = list(data["runs"].values())
    if email:
        items = [r for r in items if (r.get("email") or "") == email]
    else:
        items = [r for r in items if not (r.get("email") or "")]
    if surface and surface != "all":
        items = [r for r in items if r.get("surface") == surface]
    if status == "active":
        items = [r for r in items if r.get("status") in ("planning", "running", "paused")]
    if projectId:
        items = [r for r in items if r.get("projectId") == projectId]
    if conversationId:
        items = [r for r in items if r.get("conversationId") == conversationId]
    items.sort(key=lambda r: float(r.get("createdAt") or 0), reverse=True)
    return {"code": 0, "data": {"runs": items[:int(limit)]}, "msg": "ok"}


@app.post("/api/agent/runs/{run_id}/{action}")
async def vz_run_control(run_id: str, action: str, request: Request):
    email = authenticated_account_email(request, required=False)
    if action not in ("cancel", "pause", "resume", "retry"):
        raise HTTPException(status_code=400, detail="不支持的控制动作")
    async with VZ_RUNS_LOCK:
        run = VZ_RUNS.get(run_id)
    if not run or run["email"] != email:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if action == "cancel":
        run["cancelled"] = True
        _vz_run_emit(run, "run.cancelled", {})
        run["status"] = "cancelled"
        run["stage"] = "cancelled"
    elif action == "pause":
        if run["status"] in ("planning", "running") and not run["paused"]:
            run["paused"] = True
            _vz_run_emit(run, "run.paused", {})
    elif action == "resume":
        run["paused"] = False
        _vz_run_emit(run, "run.resumed", {})
    elif action == "retry":
        run["cancelled"] = False
        if run["status"] not in ("failed", "cancelled"):
            raise HTTPException(status_code=400, detail="该任务尚未结束，无法重试")
        async with VZ_RUNS_LOCK:
            new_run = dict(run)
            new_run["id"] = _vz_uuid("run")
            new_run["status"] = "planning"
            new_run["stage"] = "planning"
            new_run["paused"] = False
            new_run["cancelled"] = False
            new_run["tasks"] = []
            new_run["event_log"] = []
            new_run["queue"] = asyncio.Queue()
            new_run["created_at"] = _now_ms()
            new_run["updated_at"] = _now_ms()
            VZ_RUNS[new_run["id"]] = new_run
        asyncio.create_task(_vz_run_execute(new_run))
        return {"code": 0, "data": {"run": _vz_run_snapshot(new_run)}, "msg": "ok"}
    return {"code": 0, "data": {"run": _vz_run_snapshot(run)}, "msg": "ok"}


@app.post("/api/agent/runs/{run_id}/tasks/{task_id}/retry")
async def vz_run_task_retry(run_id: str, task_id: str, request: Request):
    email = authenticated_account_email(request, required=False)
    async with VZ_RUNS_LOCK:
        run = VZ_RUNS.get(run_id)
    if not run or run["email"] != email:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    task = next((t for t in run.get("tasks") or [] if t.get("id") == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] not in ("failed", "completed"):
        raise HTTPException(status_code=400, detail="该任务尚未结束，无法重试")
    payload_obj = run["payload_obj"]
    ref_urls = []
    data = _vz_creative()
    for aid in (run.get("asset_ids") or []):
        for cid, assets in data["assets"].items():
            for a in assets:
                if a.get("id") == aid:
                    u = _stable_url(a)
                    if u:
                        ref_urls.append(u)
    task["status"] = "running"
    _vz_run_emit(run, "task.running", {"taskId": task["id"], "title": task["title"], "kind": task["kind"]})
    try:
        if task["kind"] == "text":
            text_out = await _agent_text_step(payload_obj, task["def"], request)
            task["result_text"] = text_out
            task["status"] = "completed"
            _vz_run_emit(run, "task.completed", {"taskId": task["id"], "title": task["title"], "kind": "text", "message": "重试成功。", "text": text_out, "result_url": ""})
            await _vz_run_add_result_asset(run, task, "", text_out)
        elif task["kind"] == "video":
            url, provider_id = await _agent_video_step(payload_obj, task["def"], "", "", request, email, ref_urls)
            task["result_url"] = url
            task["status"] = "completed"
            _vz_run_emit(run, "task.completed", {"taskId": task["id"], "title": task["title"], "kind": "video", "message": "重试成功。", "text": "", "result_url": url})
            await _vz_run_add_result_asset(run, task, url)
        else:
            urls, size = await _agent_image_step(payload_obj, task["def"], "", "", request, email, ref_urls, run)
            task["result_url"] = urls[0] if urls else ""
            task["status"] = "completed"
            _vz_run_emit(run, "task.completed", {"taskId": task["id"], "title": task["title"], "kind": "image", "message": "重试成功。", "text": "", "result_url": task["result_url"]})
            await _vz_run_add_result_asset(run, task, task["result_url"])
        run["status"] = "completed"
    except Exception as exc:
        task["status"] = "failed"
        task["error"] = str(exc)[:300]
        _vz_run_emit(run, "task.failed", {"taskId": task["id"], "title": task["title"], "error": str(exc)[:300]})
        run["status"] = "failed"
        run["error"] = str(exc)[:300]
    await _vz_run_mark_terminal(run)
    return {"code": 0, "data": {"run": _vz_run_snapshot(run)}, "msg": "ok"}


@app.get("/api/agent/runs/{run_id}/events")
async def vz_run_events(run_id: str, request: Request):
    def vz_sse(ev):
        return "event: %s\ndata: %s\n\n" % (str(ev.get("type") or "message"), json.dumps(ev, ensure_ascii=False))
    email = authenticated_account_email(request, required=False)
    async with VZ_RUNS_LOCK:
        run = VZ_RUNS.get(run_id)
    if not run or run["email"] != email:
        data = _vz_creative()
        snap = data["runs"].get(run_id)
        if not snap:
            raise HTTPException(status_code=404, detail="任务不存在或已过期")
        async def static_stream():
            yield vz_sse({"type": "run.snapshot", "data": snap})
            reply = snap.get("error") or ""
            if snap.get("status") == "completed":
                for _cid, msgs in data.get("messages", {}).items():
                    for m in msgs:
                        if m.get("runId") == run_id and m.get("role") == "assistant" and (m.get("content") or "").strip():
                            reply = m.get("content")
                            break
                    if reply:
                        break
            yield vz_sse({"type": "run.completed" if snap.get("status") == "completed" else "run.failed", "data": {"reply": reply, "message": snap.get("error") or ""}})
        return StreamingResponse(static_stream(), media_type="text/event-stream", headers=dict(SSE_HEADERS))

    async def stream():
        import sys as _sys
        for ev in run["event_log"]:
            print("VZSSE replay", ev.get("type"), file=_sys.stderr, flush=True)
            yield vz_sse(ev)
        while run["status"] not in ("completed", "failed", "cancelled"):
            try:
                ev = await asyncio.wait_for(run["queue"].get(), timeout=20)
                print("VZSSE got", ev.get("type"), file=_sys.stderr, flush=True)
                yield vz_sse(ev)
            except asyncio.TimeoutError:
                if run["status"] in ("completed", "failed", "cancelled"):
                    break
                yield ": keepalive\n\n"
            except asyncio.CancelledError:
                print("VZSSE cancelled", file=_sys.stderr, flush=True)
                break
            except Exception as exc:
                import traceback
                traceback.print_exc()
                break
        for ev in run["event_log"]:
            print("VZSSE replay2", ev.get("type"), file=_sys.stderr, flush=True)
            yield vz_sse(ev)
        yield vz_sse({"type": "run.snapshot", "data": _vz_run_snapshot(run)})
        print("VZSSE stream-end", file=_sys.stderr, flush=True)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=dict(SSE_HEADERS))


# ---------------------------------------------------------------- Drama projects

def _drama_summary(project: Dict[str, Any]) -> Dict[str, Any]:
    episodes = project.get("episodes") or []
    shots = [s for ep in episodes for s in (ep.get("shots") or [])]
    pending = sum(1 for s in shots if s.get("storyboardStatus") == "queued" or s.get("generationStatus") == "queued" or s.get("audioStatus") == "queued")
    failed = sum(1 for s in shots if s.get("storyboardStatus") == "error" or s.get("generationStatus") == "error" or s.get("audioStatus") == "error")
    return {
        "id": project.get("id"),
        "title": project.get("title") or "",
        "summary": project.get("summary") or "",
        "style": project.get("style") or "",
        "ratio": project.get("ratio") or "",
        "status": project.get("status") or "active",
        "createdAt": project.get("createdAt"),
        "updatedAt": project.get("updatedAt"),
        "episodeCount": len(episodes),
        "characterCount": len(project.get("characters") or []),
        "sceneCount": len(project.get("scenes") or []),
        "shotCount": len(shots),
        "pendingTaskCount": pending,
        "failedTaskCount": failed,
    }


@app.get("/api/drama/projects")
async def vz_drama_projects_list(request: Request, page: int = 1, pageSize: int = 12):
    email = authenticated_account_email(request, required=False)
    data = _vz_drama()
    items = [p for p in data["projects"].values()]
    if email:
        items = [p for p in items if clean_billing_email(p.get("ownerEmail") or "") == clean_billing_email(email)]
    items.sort(key=lambda p: str(p.get("updatedAt") or ""), reverse=True)
    total = len(items)
    start = (max(1, int(page)) - 1) * max(1, int(pageSize))
    page_items = items[start:start + max(1, int(pageSize))]
    return {"data": {"projects": [_drama_summary(p) for p in page_items], "total": total, "page": int(page), "pageSize": int(pageSize)}, "msg": "ok"}


@app.post("/api/drama/projects")
async def vz_drama_project_create(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    pid = _vz_uuid("dramap")
    now = _now_ms()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    initial_script = str(payload.get("initialScript") or "").strip()
    source_assets = payload.get("sourceAssets") or []
    if not isinstance(source_assets, list):
        source_assets = []
    episode_id = _vz_uuid("ep")
    episodes = []
    if initial_script:
        episodes.append({
            "id": episode_id,
            "title": "第一集",
            "script": initial_script,
            "outline": "",
            "hook": "",
            "nextPreview": "",
            "sourceRange": "",
            "reviewStatus": "draft",
            "shots": [],
        })
    project = {
        "id": pid,
        "ownerEmail": email,
        "sourceHandoffId": str(payload.get("sourceHandoffId") or "") or None,
        "title": str(payload.get("title") or "未命名短剧"),
        "summary": str(payload.get("summary") or ""),
        "style": str(payload.get("style") or "写实电影感"),
        "ratio": str(payload.get("ratio") or "9:16"),
        "status": "active",
        "creativeConversationId": str(payload.get("creativeConversationId") or "") or None,
        "activeEpisodeId": episode_id if episodes else None,
        "characters": [],
        "scenes": [],
        "props": [],
        "clues": [],
        "defaultVideoMode": str(payload.get("defaultVideoMode") or "storyboard"),
        "episodes": episodes,
        "sourceAssets": source_assets,
        "createdAt": now_iso,
        "updatedAt": now_iso,
    }
    data = _vz_drama()
    data["projects"][pid] = project
    _vz_save_drama(data)
    return {"data": {"project": project}, "msg": "ok"}


@app.get("/api/drama/projects/{pid}")
async def vz_drama_project_get(pid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_drama()
    project = data["projects"].get(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"data": {"project": project}, "msg": "ok"}


@app.patch("/api/drama/projects/{pid}")
async def vz_drama_project_patch(pid: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_drama()
    project = data["projects"].get(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if isinstance(payload, dict):
        for key, value in payload.items():
            project[key] = value
    if not project.get("updatedAt") or str(project.get("updatedAt")) == str(payload.get("updatedAt")):
        project["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    _vz_save_drama(data)
    return {"data": {"project": project}, "msg": "ok"}


@app.delete("/api/drama/projects/{pid}")
async def vz_drama_project_delete(pid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_drama()
    if pid not in data["projects"]:
        raise HTTPException(status_code=404, detail="项目不存在")
    del data["projects"][pid]
    data["versions"].pop(pid, None)
    _vz_save_drama(data)
    return {"data": {"deleted": True}, "msg": "ok"}


@app.delete("/api/drama/projects/{pid}/agent-conversations/{cid}")
async def vz_drama_project_conversation_delete(pid: str, cid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_drama()
    project = data["projects"].get(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    active = project.get("creativeConversationId") or ""
    if active == cid:
        project["creativeConversationId"] = None
    _vz_save_drama(data)
    return {"data": {"deleted": True, "activeConversationId": project.get("creativeConversationId") or "", "project": project}, "msg": "ok"}


@app.post("/api/drama/projects/{pid}/versions")
async def vz_drama_version_create(pid: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_drama()
    if pid not in data["projects"]:
        raise HTTPException(status_code=404, detail="项目不存在")
    versions = data["versions"].setdefault(pid, [])
    version_no = (versions[-1].get("version") if versions else 0) + 1
    snapshot = payload.get("snapshot") or {}
    vid = _vz_uuid("ver")
    if isinstance(snapshot, dict) and snapshot:
        try:
            creative = _vz_creative()
            snapshots = creative.setdefault("drama_snapshots", {})
            if not isinstance(snapshots, dict):
                snapshots = {}
                creative["drama_snapshots"] = snapshots
            snapshots[vid] = snapshot
            _vz_save_creative(creative)
        except Exception:
            pass
    version = {
        "id": vid,
        "projectId": pid,
        "version": version_no,
        "reason": str(payload.get("reason") or ""),
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
    }
    versions.append(version)
    _vz_save_drama(data)
    return {"data": {"version": version}, "msg": "ok"}


@app.get("/api/drama/projects/{pid}/versions")
async def vz_drama_versions_list(pid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_drama()
    versions = data["versions"].get(pid) or []
    versions.sort(key=lambda v: int(v.get("version") or 0))
    return {"data": {"versions": versions}, "msg": "ok"}


@app.post("/api/drama/projects/{pid}/versions/{vid}")
async def vz_drama_version_restore(pid: str, vid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_drama()
    if pid not in data["projects"]:
        raise HTTPException(status_code=404, detail="项目不存在")
    snapshot = None
    data2 = _vz_creative()
    stored_snapshots = data2.get("drama_snapshots") or {}
    stored_snapshots = stored_snapshots if isinstance(stored_snapshots, dict) else {}
    for ver in (data["versions"].get(pid) or []):
        if ver.get("id") == vid:
            snapshot = stored_snapshots.get(vid)
            break
    if snapshot is None:
        # 无快照内容时直接返回当前项目（幂等恢复）
        return {"data": {"project": data["projects"][pid]}, "msg": "ok"}
    data["projects"][pid] = snapshot
    _vz_save_drama(data)
    return {"data": {"project": snapshot}, "msg": "ok"}


@app.get("/api/drama/projects/{pid}/costs")
async def vz_drama_project_costs(pid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_drama()
    project = data["projects"].get(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    shots = [s for ep in (project.get("episodes") or []) for s in (ep.get("shots") or [])]
    by_type = {"image": {"tasks": 0, "estimatedPoints": 0, "actualPoints": 0}, "video": {"tasks": 0, "estimatedPoints": 0, "actualPoints": 0}, "audio": {"tasks": 0, "estimatedPoints": 0, "actualPoints": 0}}
    for s in shots:
        if s.get("storyboardStatus") == "success":
            by_type["image"]["tasks"] += 1
            by_type["image"]["actualPoints"] += 1
        if s.get("generationStatus") == "success":
            by_type["video"]["tasks"] += 1
            by_type["video"]["actualPoints"] += 1
        if s.get("audioStatus") == "success":
            by_type["audio"]["tasks"] += 1
            by_type["audio"]["actualPoints"] += 1
        for key in ("storyboardStatus", "generationStatus", "audioStatus"):
            if s.get(key) in ("queued", "running"):
                type_key = "image" if key == "storyboardStatus" else "video" if key == "generationStatus" else "audio"
                by_type[type_key]["estimatedPoints"] += 1
    total_tasks = sum(v["tasks"] for v in by_type.values())
    total_success = sum(v["actualPoints"] for v in by_type.values())
    total_failed = total_tasks - total_success
    summary = {
        "estimatedPoints": sum(v["estimatedPoints"] for v in by_type.values()),
        "actualPoints": sum(v["actualPoints"] for v in by_type.values()),
        "taskCount": total_tasks,
        "successCount": total_success,
        "failedCount": max(0, total_failed),
        "byType": by_type,
    }
    return {"data": {"summary": summary}, "msg": "ok"}


@app.get("/api/drama/render-capability")
async def vz_drama_render_capability(request: Request):
    email = authenticated_account_email(request, required=False)
    available = bool(shutil.which("ffmpeg"))
    return {"data": {"available": available}, "msg": "ok"}


async def _vz_drama_content_analyze(payload: Dict[str, Any], email: str, request: Request) -> Dict[str, Any]:
    script = str(payload.get("script") or "")
    summary = str(payload.get("summary") or "")
    style = str(payload.get("style") or "写实电影感")
    messages = [
        {"role": "system", "content": "你是资深短剧导演。请把短剧剧本拆解为内容分析 JSON（不要 markdown），格式："
         '{"episode":{"outline":"剧情梗概","hook":"开篇钩子","nextPreview":"下集预告","sourceRange":"全集"},"characters":[{"name":"角色名","description":"性格/外形描述","profile":null}],"scenes":[{"name":"场景名","description":"环境描述"}],"props":[{"name":"道具名","description":"描述"}],"clues":[{"name":"线索名","description":"描述","payoff":"收束"}],"shots":[{"title":"镜头标题","description":"画面描述","sourceText":"对应原文","shotBoundary":"起止句","dialogue":"对白","narration":"旁白","utterances":[{"id":"u1","order":1,"type":"dialogue","speaker":"角色","text":"台词"}],"duration":5,"characterNames":["角色名"],"propNames":[],"clueNames":[],"sceneName":"场景名"}]}'},
        {"role": "user", "content": f"剧本风格：{style}\n剧本简介：{summary}\n\n剧本：\n{script[:8000]}"},
    ]
    raw = await _vz_llm_text(messages, email, request)
    parsed = _extract_json_object(raw)
    if not parsed:
        raise HTTPException(status_code=502, detail="短剧分析未返回有效结果")
    return parsed


async def _vz_drama_visual_analyze(payload: Dict[str, Any], email: str, request: Request) -> Dict[str, Any]:
    episode = payload.get("episode") or {}
    shots = payload.get("shots") or []
    characters = payload.get("characters") or []
    scenes = payload.get("scenes") or []
    summary = str(payload.get("summary") or "")
    style = str(payload.get("style") or "")
    char_lines = "\n".join(f'- {c.get("name")}: {c.get("description", "")}' for c in characters if isinstance(c, dict))
    scene_lines = "\n".join(f'- {s.get("name")}: {s.get("description", "")}' for s in scenes if isinstance(s, dict))
    shot_lines = "\n".join(f'- {s.get("order", i)} {s.get("title", "")}: {s.get("description", "")} 对白:{s.get("dialogue", "")}' for i, s in enumerate(shots))
    messages = [
        {"role": "system", "content": "你是短剧视觉导演。请为每个镜头设计视觉方案，输出 JSON（不要 markdown）："
         '{"shots":[{"shotId":"镜头的id","imagePrompt":"起始帧图生图提示词，含主体/构图/光线/参考一致性","videoPrompt":"视频生成提示词，含运动/转场/节奏","cameraMotion":"运镜描述","startFramePrompt":"起始帧提示词","endFramePrompt":"结束帧提示词","negativePrompt":"负面提示词","continuity":{"shotSize":"景别","cameraAngle":"机位","composition":"构图","characterBlocking":"走位","gazeDirection":"视线","actionStart":"动作起点","actionEnd":"动作终点","screenDirection":"屏幕方向","axisRule":"轴线规则","continuityNotes":"连续性备注"}}]}' + ("" if not shots else " 镜头 id 必须取给定 shots 的 id 字段。")},
        {"role": "user", "content": f"风格：{style}\n剧情：{summary}\n\n角色：\n{char_lines}\n\n场景：\n{scene_lines}\n\n镜头列表：\n{shot_lines}\n\n剧本标题：{episode.get('title', '')}"},
    ]
    raw = await _vz_llm_text(messages, email, request)
    parsed = _extract_json_object(raw)
    if not parsed:
        raise HTTPException(status_code=502, detail="视觉分析未返回有效结果")
    return parsed


@app.post("/api/drama/analyze")
async def vz_drama_analyze(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    phase = str(payload.get("phase") or "content")
    try:
        if phase == "visual":
            result = await _vz_drama_visual_analyze(payload, email, request)
        else:
            result = await _vz_drama_content_analyze(payload, email, request)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"短剧分析失败：{str(exc)[:200]}")
    return {"data": result, "msg": "ok"}


@app.post("/api/drama/review")
async def vz_drama_review(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    project = payload.get("project") or {}
    episode = payload.get("episode") or {}
    shots = episode.get("shots") or []
    try:
        raw = await _vz_llm_text([
            {"role": "system", "content": "你是短剧质检导演。请评估分镜脚本的质量，输出 JSON（不要 markdown）："
             '{"mode":"text","status":"passed 或 needs_revision","score":0,"summary":"一句话总评","issues":[{"category":"问题类别","severity":"low/medium/high","message":"问题描述","correction":"建议"}],"retryTaskIds":[]}'},
            {"role": "user", "content": f"短剧《{project.get('title')}》风格{project.get('style')}，共{len(shots)}个镜头，请评估剧本与分镜质量。"},
        ], email, request)
        review = _extract_json_object(raw)
    except Exception:
        review = {"mode": "unavailable", "status": "unavailable", "summary": "质检服务暂时不可用。", "issues": [], "retryTaskIds": []}
    return {"data": {"review": review}, "msg": "ok"}


@app.post("/api/drama/render")
async def vz_drama_render(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    shots = payload.get("shots") or []
    render_id = _vz_uuid("render")
    task = {"id": render_id, "status": "pending", "result": {}, "error": ""}
    VZ_TASKS[render_id] = task
    asyncio.create_task(_vz_drama_render_worker(render_id, payload))
    return {"data": task, "msg": "ok"}


async def _vz_drama_render_worker(render_id: str, payload: Dict[str, Any]):
    task = VZ_TASKS.get(render_id)
    if not task:
        return
    task["status"] = "running"
    urls = [str(s.get("videoUrl") or "") for s in (payload.get("shots") or []) if str(s.get("videoUrl") or "")]
    if not urls:
        task["status"] = "error"
        task["error"] = "没有可渲染的视频片段"
        return
    if not shutil.which("ffmpeg"):
        task["status"] = "error"
        task["error"] = "服务器未安装 FFmpeg，暂不支持渲染合成"
        return
    out_name = f"vz_render_{uuid.uuid4().hex[:12]}.mp4"
    out_path = output_path_for(out_name, "output")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    list_path = out_path + ".list"
    try:
        lines = []
        for u in urls:
            clean = u
            if clean.startswith("http"):
                pass
            elif clean.startswith("/"):
                clean = clean.lstrip("/")
            local = clean
            if local.startswith(("http://", "https://")):
                # 下载到本地再拼接
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.get(local)
                    resp.raise_for_status()
                tmp_name = f"vz_render_src_{uuid.uuid4().hex[:8]}.mp4"
                tmp_path = output_path_for(tmp_name, "output")
                with open(tmp_path, "wb") as fh:
                    fh.write(resp.content)
                local = tmp_path
            lines.append(f"file '{local}'")
        with open(list_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path]
        proc = await asyncio.to_thread(subprocess.run, cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
        if proc.returncode != 0:
            # 回退：统一转码后再拼接
            proc2 = await asyncio.to_thread(subprocess.run,
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2", "-r", "24", "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
            if proc2.returncode != 0:
                raise RuntimeError((proc2.stderr or b"")[:300].decode("utf-8", "ignore"))
        url = output_url_for(out_name, "output")
        remote = await mirror_local_url_to_cos(url)
        task["status"] = "success"
        task["result"] = {"url": remote or url}
    except Exception as exc:
        task["status"] = "error"
        task["error"] = str(exc)[:300]
    finally:
        try:
            if os.path.exists(list_path):
                os.remove(list_path)
        except Exception:
            pass


@app.get("/api/drama/render/{render_id}")
async def vz_drama_render_get(render_id: str, request: Request):
    email = authenticated_account_email(request, required=False)
    task = VZ_TASKS.get(render_id)
    if not task:
        raise HTTPException(status_code=404, detail="渲染任务不存在")
    return {"data": task, "msg": "ok"}


@app.patch("/api/drama/render/{render_id}")
async def vz_drama_render_patch(render_id: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    task = VZ_TASKS.get(render_id)
    if not task:
        raise HTTPException(status_code=404, detail="渲染任务不存在")
    if payload.get("status") == "cancelled":
        task["status"] = "cancelled"
    return {"data": task, "msg": "ok"}


@app.post("/api/drama/projects/{pid}/export-jianying")
async def vz_drama_export_jianying(pid: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("说明.txt", "短剧剪映草稿导出接口已就绪。\n请在服务器端生成完整剪映草稿包。")
    filename = "短剧剪映草稿.zip"
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": disposition},
    )


# ---------------------------------------------------------------- Image / Video / Audio tasks

def _ref_image_to_ai(ref: Dict[str, Any], role: str = "reference") -> Optional[AIReference]:
    if not isinstance(ref, dict):
        return None
    url = _stable_url(ref) or str(ref.get("dataUrl") or "").strip()
    if not url or url.startswith("blob:"):
        return None
    kind = str(ref.get("type") or "image").lower()
    return AIReference(url=url, kind=kind if kind in ("image", "video", "audio") else "image", role=role)


async def _vz_run_image_task(tid: str, payload: Dict[str, Any], request: Request, email: str):
    VZ_TASKS[tid] = {"id": tid, "status": "running", "result": {}, "error": "", "canRetry": True}
    try:
        prompt = str(payload.get("prompt") or "")
        config = payload.get("config") or {}
        if not isinstance(config, dict):
            config = {}
        model = str(config.get("model") or "") or AGENT_IMAGE_DEFAULT_MODEL
        size = str(config.get("size") or "1:1")
        ratio = size if size not in ("Auto", "") else "1:1"
        refs = []
        for ref in (payload.get("references") or []):
            ai_ref = _ref_image_to_ai(ref)
            if ai_ref:
                refs.append(ai_ref)
        mask = payload.get("mask")
        if isinstance(mask, dict):
            ai_mask = _ref_image_to_ai(mask, "mask")
            if ai_mask:
                refs.append(ai_mask)
        image_payload = OnlineImageRequest(
            prompt=prompt,
            provider_id="",
            model=model,
            size=_agent_ratio_to_size(ratio),
            resolution=str(config.get("resolution") or "Auto"),
            quality=str(config.get("quality") or "high"),
            n=1,
            reference_images=refs,
            canvas_id="",
            node_id="",
        )
        task = await create_canvas_image_task(image_payload, request)
        task_id = str(task.get("task_id") or "")
        url = await _agent_poll_image_task(task_id, request, email)
        if not url:
            raise RuntimeError("生图未返回结果")
        entry = {"dataUrl": url, "remoteUrl": url, "serverUrl": url, "width": 0, "height": 0, "bytes": 0, "mimeType": "image/png"}
        VZ_TASKS[tid] = {"id": tid, "status": "success", "result": {**entry, "results": [entry]}, "error": "", "canRetry": False}
    except HTTPException as exc:
        VZ_TASKS[tid] = {"id": tid, "status": "error", "result": {}, "error": str(exc.detail)[:300], "canRetry": True}
    except Exception as exc:
        VZ_TASKS[tid] = {"id": tid, "status": "error", "result": {}, "error": str(exc)[:300], "canRetry": True}


@app.post("/api/image-tasks")
async def vz_image_task_create(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    tid = _vz_uuid("img")
    VZ_TASKS[tid] = {"id": tid, "status": "pending", "result": {}, "error": "", "canRetry": True}
    asyncio.create_task(_vz_run_image_task(tid, payload, request, email))
    return {"task": {"id": tid, "kind": "generation", "model": (payload.get("config") or {}).get("model", ""), "status": "pending"}}


@app.get("/api/image-tasks/{tid}")
async def vz_image_task_get(tid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    task = VZ_TASKS.get(tid)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task": task}


@app.patch("/api/image-tasks/{tid}")
async def vz_image_task_patch(tid: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    task = VZ_TASKS.get(tid)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if payload.get("status") == "cancelled":
        task["status"] = "cancelled"
        task["canRetry"] = False
    return {"task": task}


async def _vz_run_video_task(tid: str, payload: Dict[str, Any], request: Request):
    VZ_TASKS[tid] = {"id": tid, "status": "running", "result": {}, "error": "", "canRetry": True}
    try:
        prompt = str(payload.get("prompt") or "")
        config = payload.get("config") or {}
        if not isinstance(config, dict):
            config = {}
        model = str(config.get("model") or "") or AGENT_VIDEO_DEFAULT_MODEL
        provider_id = _vz_resolve_video_provider(model)
        video_model = _vz_model_name(model)
        ratio = str(config.get("size") or "16:9")
        if ratio in ("Auto", "") or "x" in ratio:
            ratio = "16:9"
        duration = 5
        try:
            duration = max(5, min(10, int(float(str(config.get("videoSeconds") or "5")))))
        except Exception:
            pass
        refs = []
        for ref in (payload.get("references") or []):
            if not isinstance(ref, dict):
                continue
            url = str(ref.get("url") or "").strip()
            if not url or url.startswith("blob:"):
                continue
            role = str(ref.get("role") or "first_frame")
            refs.append(AIReference(url=url, kind="image", role=role))
        video_payload = CanvasVideoRequest(
            prompt=prompt,
            provider_id=provider_id,
            model=video_model,
            duration=duration,
            aspect_ratio=ratio,
            resolution=str(config.get("resolution") or "Auto"),
            images=refs,
            canvas_id="",
            node_id="",
        )
        result = await canvas_video(video_payload, request)
        url = _agent_asset_url(result)
        if not url:
            raise RuntimeError("视频生成未返回可用的结果地址")
        VZ_TASKS[tid] = {"id": tid, "status": "success", "result": {"url": url, "remoteUrl": url, "mimeType": "video/mp4", "durationMs": duration * 1000}, "error": "", "canRetry": False}
    except HTTPException as exc:
        VZ_TASKS[tid] = {"id": tid, "status": "error", "result": {}, "error": str(exc.detail)[:300], "canRetry": True}
    except Exception as exc:
        VZ_TASKS[tid] = {"id": tid, "status": "error", "result": {}, "error": str(exc)[:300], "canRetry": True}


@app.post("/api/video-generation-tasks")
async def vz_video_task_create(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    tid = _vz_uuid("vid")
    VZ_TASKS[tid] = {"id": tid, "status": "pending", "result": {}, "error": "", "canRetry": True}
    asyncio.create_task(_vz_run_video_task(tid, payload, request))
    model = (payload.get("config") or {}).get("model", "")
    return {"task": {"id": tid, "model": model, "durationSeconds": 0}}


@app.get("/api/video-tasks/{tid}")
async def vz_video_task_get(tid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    task = VZ_TASKS.get(tid)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task": task}


@app.patch("/api/video-tasks/{tid}")
async def vz_video_task_patch(tid: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    task = VZ_TASKS.get(tid)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if payload.get("action") == "cancel" or payload.get("status") == "cancelled":
        task["status"] = "cancelled"
        task["canRetry"] = False
    return {"task": {"id": tid, "status": task.get("status")}}


@app.post("/api/audio-tasks")
async def vz_audio_task_create(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    tid = _vz_uuid("aud")
    VZ_TASKS[tid] = {"id": tid, "status": "error", "result": {}, "error": "语音合成暂不可用，请稍后再试或使用其他方式生成音频。", "canRetry": False, "model": (payload.get("config") or {}).get("model", "")}
    return {"task": {"id": tid, "status": "error", "model": (payload.get("config") or {}).get("model", ""), "result": {}, "error": VZ_TASKS[tid]["error"]}}


@app.get("/api/audio-tasks/{tid}")
async def vz_audio_task_get(tid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    task = VZ_TASKS.get(tid)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task": task}


@app.patch("/api/audio-tasks/{tid}")
async def vz_audio_task_patch(tid: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    task = VZ_TASKS.get(tid)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if payload.get("status") == "cancelled":
        task["status"] = "cancelled"
    return {"task": task}


# ---------------------------------------------------------------- Reference assets / misc

@app.post("/api/reference-assets")
async def vz_reference_assets(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    data_url = str(payload.get("dataUrl") or "").strip()
    original_name = str(payload.get("originalName") or "").strip() or f"ref_{uuid.uuid4().hex[:8]}"
    persistent = bool(payload.get("persistent"))
    if not data_url:
        raise HTTPException(status_code=400, detail="缺少 dataUrl")
    raw = data_url
    mime = "application/octet-stream"
    if raw.startswith("data:"):
        header, _, raw = raw.partition(",")
        mime = header[5:].split(";", 1)[0].strip().lower()
    try:
        content = base64.b64decode(raw, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="dataUrl 无法解码")
    if not content:
        raise HTTPException(status_code=400, detail="内容为空")
    ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif", "video/mp4": ".mp4", "audio/mpeg": ".mp3", "text/plain": ".txt"}
    ext = ext_map.get(mime, ".bin")
    prefix = "permanent" if persistent else "temporary"
    storage_name = f"{prefix}/vz_ref_{uuid.uuid4().hex[:16]}{ext}"
    path = output_path_for(storage_name, "input")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)
    local_url = output_url_for(storage_name, "input")
    remote = await mirror_local_url_to_cos(local_url)
    url = remote or local_url
    return {"upstreamUrl": url, "url": url, "token": storage_name, "key": storage_name, "bytes": len(content), "mimeType": mime}


def _vz_canvas_overview(email: str, recent_limit: int = 8):
    """返回 (latest_project, recent_canvas_assets)。只扫描当前账号可访问的画布。"""
    try:
        records = list_canvases(email=email)
    except Exception:
        records = []
    latest = None
    if records:
        record = records[0]
        cid = str(record.get("id") or "")
        if cid:
            previews: List[Dict[str, Any]] = []
            pseen = set()
            raw = None
            try:
                raw = load_canvas_any(cid)
            except Exception:
                pass
            if raw:
                for item in extract_canvas_assets(raw):
                    kind = str(item.get("kind") or "")
                    url = str(item.get("url") or "")
                    if kind in ("image", "video") and url and url not in pseen:
                        pseen.add(url)
                        previews.append({"kind": kind, "url": url})
                        if len(previews) >= 6:
                            break
            latest = {
                "id": cid,
                "title": str(record.get("title") or "未命名项目"),
                "updatedAt": str(int(record.get("updated_at") or record.get("created_at") or 0)),
                "nodeCount": int(record.get("node_count") or 0),
                "connectionCount": len((raw or {}).get("connections") or []),
                "previews": previews,
            }
    out: List[Dict[str, Any]] = []
    seen = set()
    for record in records:
        cid = str(record.get("id") or "")
        if not cid:
            continue
        try:
            raw = load_canvas_any(cid)
        except Exception:
            continue
        for item in extract_canvas_assets(raw):
            kind = str(item.get("kind") or "")
            url = str(item.get("url") or "")
            if kind not in ("image", "video") or not url or url in seen:
                continue
            seen.add(url)
            out.append({
                "id": str(item.get("id") or f"ast-{len(out)}"),
                "kind": kind,
                "url": url,
                "title": str(item.get("node_title") or item.get("canvas_title") or ""),
                "createdAt": str(int(item.get("created_at") or record.get("updated_at") or 0)),
            })
    out.sort(key=lambda a: float(a.get("createdAt") or 0), reverse=True)
    return latest, out[:recent_limit]


@app.get("/api/create/overview")
async def vz_create_overview(request: Request):
    email = authenticated_account_email(request, required=False)
    data = _vz_creative()
    assets = []
    for cid, lst in data["assets"].items():
        assets.extend(lst)
    assets.sort(key=lambda a: float(a.get("createdAt") or 0), reverse=True)
    recent = []
    for a in assets[:6]:
        recent.append({"id": a.get("id"), "kind": "image" if a.get("type") in ("image", "video") else "image", "url": _stable_url(a), "title": a.get("title") or "", "createdAt": str(a.get("createdAt") or "")})
    latest_project = None
    if email:
        latest_project, canvas_assets = await asyncio.to_thread(_vz_canvas_overview, email, 8)
        seen_urls = {r.get("url") for r in recent if r.get("url")}
        merged = recent + [c for c in canvas_assets if c.get("url") not in seen_urls]
        merged.sort(key=lambda a: float(a.get("createdAt") or 0), reverse=True)
        recent = merged[:8]
    running = []
    async with VZ_RUNS_LOCK:
        for run in VZ_RUNS.values():
            if run.get("email") != email:
                continue
            if run.get("status") in ("planning", "running", "paused"):
                running.append({"id": run["id"], "kind": "agent", "source": run.get("surface") or "chat", "title": run.get("prompt") or "", "createdAt": str(run.get("created_at") or ""), "conversationId": run.get("conversation_id") or "", "status": run.get("status")})
    return {"data": {"overview": {"latestProject": latest_project, "runningTasks": running[:6], "recentAssets": recent}}, "msg": "ok"}


@app.get("/api/canvas/projects")
async def vz_canvas_projects(request: Request, page: int = 1, pageSize: int = 12):
    email = authenticated_account_email(request, required=False)
    records = await asyncio.to_thread(list_canvases, email) if email else []
    total = len(records)
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(pageSize or 12)))
    start = (page - 1) * page_size
    projects = []
    for r in records[start:start + page_size]:
        cid = str(r.get("id") or "")
        conns = 0
        try:
            raw = load_canvas_any(cid)
            conns = len(raw.get("connections") or [])
        except Exception:
            pass
        projects.append({
            "id": cid,
            "title": str(r.get("title") or "未命名项目"),
            "updatedAt": str(int(r.get("updated_at") or r.get("created_at") or 0)),
            "nodeCount": int(r.get("node_count") or 0),
            "connectionCount": conns,
            "previews": [],
        })
    return {"data": {"projects": projects, "total": total, "page": page, "pageSize": page_size}, "msg": "ok"}


@app.get("/api/points")
async def vz_points(request: Request, page: int = 1, pageSize: int = 10, direction: str = ""):
    email = authenticated_account_email(request, required=False)
    try:
        with __import__("main").BILLING_LOCK:
            data = load_billing_users()
            ledger = data.get("ledger") or []
    except Exception:
        ledger = []
    records = []
    for row in ledger:
        if not isinstance(row, dict):
            continue
        row_email = clean_billing_email(str(row.get("email") or ""))
        if row_email != clean_billing_email(email):
            continue
        amount = float(row.get("amount") or row.get("delta") or 0)
        if direction == "credit" and amount < 0:
            continue
        if direction == "debit" and amount > 0:
            continue
        records.append({
            "id": str(row.get("id") or row.get("request_id") or _vz_uuid("pt")),
            "type": "credit" if amount > 0 else "debit",
            "amount": abs(int(round(amount))),
            "balanceAfter": int(round(float(row.get("balance_after") or row.get("balance") or 0))),
            "description": str(row.get("note") or row.get("description") or ""),
            "createdAt": str(row.get("created_at") or ""),
        })
    records.sort(key=lambda r: r["createdAt"], reverse=True)
    total = len(records)
    start = (max(1, int(page)) - 1) * max(1, int(pageSize))
    return {"records": records[start:start + max(1, int(pageSize))], "total": total, "page": int(page), "pageSize": int(pageSize)}


# ---------------------------------------------------------------- Public works / gallery / community

def _vz_work_assets(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen = set()
    cover = canvas_case_cover(data)
    if cover and cover not in seen:
        seen.add(cover)
        items.append({"id": "cover", "mediaType": "image", "mimeType": "image/png", "role": "cover", "sortOrder": 0, "metadata": {}, "url": cover})
    for it in extract_canvas_assets(data):
        kind = str(it.get("kind") or "")
        url = str(it.get("url") or "")
        if kind not in ("image", "video", "audio") or not url or url in seen:
            continue
        seen.add(url)
        mime = "video/mp4" if kind == "video" else "audio/mpeg" if kind == "audio" else "image/png"
        items.append({"id": str(it.get("id") or f"asset-{len(items)}"), "mediaType": kind, "mimeType": mime, "role": "content", "sortOrder": len(items), "metadata": {}, "url": url})
    return items


def _vz_author_profile(email: str) -> Dict[str, str]:
    email = clean_billing_email(str(email or ""))
    if not email:
        return {"ownerUserId": "", "ownerUsername": "", "ownerDisplayName": "匿名作者", "authorName": "匿名作者", "authorUsername": "", "authorAvatarUrl": ""}
    try:
        user = _public_user(email)
    except Exception:
        user = {}
    username = str(user.get("username") or email.split("@")[0])
    display = str(user.get("displayName") or username)
    return {
        "ownerUserId": email,
        "ownerUsername": username,
        "ownerDisplayName": display,
        "authorName": display,
        "authorUsername": username,
        "authorAvatarUrl": str(user.get("avatarUrl") or ""),
    }


def _vz_public_case_list() -> List[tuple]:
    cases = []
    for filename in os.listdir(CANVAS_DIR):
        if not filename.endswith(".json"):
            continue
        cid = filename[:-5]
        try:
            data = load_canvas_any(cid)
        except Exception:
            continue
        if data.get("deleted_at") or not case_is_live(data):
            continue
        cases.append((canvas_record(data), data))
    return cases


def _vz_public_case_by_slug(slug: str):
    slug = str(slug or "")
    if not slug or len(slug) > 64:
        return None
    try:
        data = load_canvas_any(slug)
    except Exception:
        return None
    if data.get("deleted_at") or not case_is_live(data):
        return None
    return canvas_record(data), data


def _vz_gallery_item(record: Dict[str, Any], data: Dict[str, Any], viewer: str = "") -> Dict[str, Any]:
    au = _vz_author_profile(str(record.get("owner_email") or record.get("case_published_by") or ""))
    liked_by = record.get("case_liked_by") or []
    assets = _vz_work_assets(data)
    preview = None
    for a in assets:
        if a.get("mediaType") in ("image", "video"):
            preview = {"id": a["id"], "mediaType": a["mediaType"], "mimeType": a["mimeType"], "url": a["url"]}
            break
    return {
        "slug": str(record.get("id") or ""),
        "sourceType": "canvas",
        "viewCount": int(record.get("case_views") or 0),
        "likeCount": int(record.get("case_likes") or len(liked_by)),
        "isFeatured": bool(record.get("case_featured") or False),
        "publishedAt": str(int(record.get("case_published_at") or record.get("case_submitted_at") or record.get("updated_at") or 0)),
        "title": str(record.get("case_title") or record.get("title") or "未命名作品"),
        "description": str(record.get("case_description") or ""),
        "publicPrompt": str(record.get("case_public_prompt") or ""),
        "category": str(record.get("case_category") or ""),
        "tags": list(record.get("case_tags") or []),
        "authorName": au["authorName"],
        "authorUsername": au["authorUsername"],
        "authorAvatarUrl": au["authorAvatarUrl"],
        "preview": preview,
    }


def _vz_work_gallery_item(work: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    versions = work.get("versions") or []
    published = None
    for v in versions:
        if v.get("id") == work.get("publishedVersionId"):
            published = v
            break
    if published is None:
        return None
    if str(published.get("moderationStatus") or "") != "approved":
        return None
    if str(published.get("visibility") or "public") != "public":
        return None
    au = _vz_author_profile(str(work.get("ownerEmail") or ""))
    preview = None
    for a in (published.get("assets") or []):
        mt = str(a.get("mediaType") or "")
        url = str(a.get("url") or "")
        if not url:
            continue
        if a.get("role") == "cover" or mt in ("image", "video"):
            preview = {"id": str(a.get("storageKey") or a.get("id") or ""), "mediaType": mt, "mimeType": str(a.get("mimeType") or ("video/mp4" if mt == "video" else "image/png")), "url": url}
            break
    return {
        "slug": str(work.get("slug") or work.get("id") or ""),
        "sourceType": str(work.get("sourceType") or "canvas"),
        "viewCount": int(work.get("viewCount") or 0),
        "likeCount": int(work.get("likeCount") or 0),
        "isFeatured": bool(work.get("isFeatured") or False),
        "publishedAt": str(int(_vz_iso_to_ms(published.get("submittedAt") or work.get("updatedAt") or "") or 0)),
        "title": str(published.get("title") or ""),
        "description": str(published.get("description") or ""),
        "publicPrompt": str(published.get("publicPrompt") or ""),
        "category": str(published.get("category") or ""),
        "tags": list(published.get("tags") or []),
        "authorName": "" if str(published.get("authorDisplay") or "profile") == "hidden" else (published.get("authorName") or au.get("authorName") or ""),
        "authorUsername": au.get("authorUsername") or "",
        "authorAvatarUrl": au.get("authorAvatarUrl") or "",
        "preview": preview,
    }


def _vz_iso_to_ms(value: str) -> int:
    value = str(value or "")
    if not value:
        return 0
    if value.isdigit():
        return int(value)
    try:
        return int(float(value) * 1000)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(time.mktime(time.strptime(value, fmt)) * 1000)
        except Exception:
            continue
    return 0


@app.get("/api/public/gallery")
async def vz_public_gallery(request: Request, category: str = "", limit: int = 20, sort: str = "latest"):
    email = authenticated_account_email(request, required=False)
    cases = await asyncio.to_thread(_vz_public_case_list)
    works_data = await asyncio.to_thread(_vz_works)
    work_overrides = {}
    extra_works = []
    for work in (works_data.get("works") or {}).values():
        item = _vz_work_gallery_item(work)
        if item is None:
            continue
        source_type = str(work.get("sourceType") or "")
        source_id = str(work.get("sourceId") or "")
        if source_type == "canvas" and source_id:
            work_overrides[source_id] = item
        else:
            extra_works.append(item)
    items = []
    for r, d in cases:
        cid = str(r.get("id") or "")
        override = work_overrides.get(cid)
        items.append(override if override is not None else _vz_gallery_item(r, d, email))
    items.extend(extra_works)
    cat = normalize_case_category(category)
    if cat:
        items = [it for it in items if str(it.get("category") or "") == cat]

    def sort_key(item):
        published = int(item.get("publishedAt") or 0)
        if sort == "popular":
            return (-int(item.get("likeCount") or 0), -published)
        if sort == "featured":
            return (0 if item.get("isFeatured") else 1, -published)
        return (-published,)

    if sort == "random":
        seed = int(time.time()) // 60
        items = sorted(items, key=lambda item: hashlib.sha1(f"{seed}:{item.get('slug')}".encode("utf-8")).hexdigest())
    else:
        items.sort(key=sort_key)
    limit = min(60, max(1, int(limit or 20)))
    page = items[:limit]
    next_cursor = str(limit) if len(items) > limit else None
    return {"code": 0, "data": {"items": page, "nextCursor": next_cursor}, "msg": "ok"}


@app.get("/api/public/works/{slug}")
async def vz_public_work_get(slug: str, request: Request):
    email = authenticated_account_email(request, required=False)
    record = _vz_public_work_record(slug)
    if record is not None:
        public = _vz_work_public(record)
        if public is None:
            raise HTTPException(status_code=404, detail="作品不存在或已停止公开")
        return {"code": 0, "data": {"work": public}, "msg": "ok"}
    item = _vz_public_case_by_slug(slug)
    if item is None:
        raise HTTPException(status_code=404, detail="作品不存在或已停止公开")
    record, data = item
    au = _vz_author_profile(str(record.get("owner_email") or record.get("case_published_by") or ""))
    liked_by = record.get("case_liked_by") or []
    return {"code": 0, "data": {"work": {
        "id": str(record.get("id") or ""),
        "slug": str(record.get("id") or ""),
        "sourceType": "canvas",
        "viewCount": int(record.get("case_views") or 0),
        "likeCount": int(record.get("case_likes") or len(liked_by)),
        "publishedAt": str(int(record.get("case_published_at") or record.get("case_submitted_at") or record.get("updated_at") or 0)),
        "title": str(record.get("case_title") or record.get("title") or "未命名作品"),
        "description": str(record.get("case_description") or ""),
        "publicPrompt": str(record.get("case_public_prompt") or ""),
        "category": str(record.get("case_category") or ""),
        "tags": list(record.get("case_tags") or []),
        "visibility": "public",
        "authorName": au["authorName"],
        "authorUsername": au["authorUsername"],
        "authorAvatarUrl": au["authorAvatarUrl"],
        "assets": _vz_work_assets(data),
    }}, "msg": "ok"}


@app.post("/api/public/works/{slug}/view")
async def vz_public_work_view(slug: str, request: Request):
    item = _vz_public_work_record(slug)
    if item is not None:
        public = _vz_work_public(item)
        if public is None:
            raise HTTPException(status_code=404, detail="作品不存在或已停止公开")
        views = int(item.get("viewCount") or 0) + 1
        item["viewCount"] = views
        item["lastViewedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        data = _vz_works()
        data["works"][item["id"]] = item
        _vz_save_works(data)
        return {"code": 0, "data": {"viewCount": views}, "msg": "ok"}
    item = _vz_public_case_by_slug(slug)
    if item is None:
        raise HTTPException(status_code=404, detail="作品不存在或已停止公开")
    _, data = item
    views = int(data.get("case_views") or 0) + 1
    data["case_views"] = views
    try:
        save_canvas_light(data)
    except Exception:
        pass
    return {"code": 0, "data": {"viewCount": views}, "msg": "ok"}


@app.get("/api/public/works/{slug}/community")
async def vz_public_work_community(slug: str, request: Request):
    email = authenticated_account_email(request, required=False)
    item = _vz_public_work_record(slug)
    if item is not None:
        public = _vz_work_public(item)
        if public is None:
            raise HTTPException(status_code=404, detail="作品不存在或已停止公开")
        owner_email = clean_billing_email(item.get("ownerEmail") or "")
        me = clean_billing_email(email or "")
        liked_by = set(item.get("likedBy") or [])
        return {"code": 0, "data": {
            "workId": str(item.get("id") or ""),
            "versionId": str(item.get("publishedVersionId") or ""),
            "slug": str(item.get("slug") or item.get("id") or ""),
            "ownerUserId": owner_email,
            "authorDisplay": "profile",
            "likeCount": int(item.get("likeCount") or len(liked_by)),
            "followerCount": author_follower_count(owner_email),
            "liked": bool(me) and me in liked_by,
            "followingAuthor": bool(me) and bool(owner_email) and me in followed_emails(owner_email),
            "canFollow": bool(me) and bool(owner_email) and me != owner_email,
        }, "msg": "ok"}
    item = _vz_public_case_by_slug(slug)
    if item is None:
        raise HTTPException(status_code=404, detail="作品不存在或已停止公开")
    record, data = item
    owner_email = str(record.get("owner_email") or record.get("case_published_by") or "")
    me = clean_billing_email(email or "")
    liked_by = set(data.get("case_liked_by") or [])
    return {"code": 0, "data": {
        "workId": str(record.get("id") or ""),
        "versionId": "v1",
        "slug": str(record.get("id") or ""),
        "ownerUserId": owner_email,
        "authorDisplay": "profile",
        "likeCount": int(record.get("case_likes") or len(liked_by)),
        "followerCount": author_follower_count(owner_email),
        "liked": bool(me) and me in liked_by,
        "followingAuthor": bool(me) and bool(owner_email) and me in followed_emails(owner_email),
        "canFollow": bool(me) and bool(owner_email) and me != owner_email,
    }, "msg": "ok"}


@app.post("/api/public/works/{slug}/community/like")
async def vz_public_work_like(slug: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    item = _vz_public_work_record(slug)
    if item is not None:
        public = _vz_work_public(item)
        if public is None:
            raise HTTPException(status_code=404, detail="作品不存在或已停止公开")
        me = clean_billing_email(email)
        liked_by = set(item.get("likedBy") or [])
        active = bool(payload.get("active"))
        changed = False
        if active and me not in liked_by:
            liked_by.add(me)
            changed = True
        elif not active and me in liked_by:
            liked_by.discard(me)
            changed = True
        if changed:
            item["likedBy"] = sorted(liked_by)
            item["likeCount"] = len(liked_by)
            data = _vz_works()
            data["works"][item["id"]] = item
            _vz_save_works(data)
        return {"code": 0, "data": {
            "workId": str(item.get("id") or ""),
            "versionId": str(item.get("publishedVersionId") or ""),
            "ownerUserId": str(item.get("ownerEmail") or ""),
            "changed": changed,
            "active": me in liked_by,
            "likeCount": len(liked_by),
        }, "msg": "ok"}
    item = _vz_public_case_by_slug(slug)
    if item is None:
        raise HTTPException(status_code=404, detail="作品不存在或已停止公开")
    record, data = item
    me = clean_billing_email(email)
    liked_by = set(data.get("case_liked_by") or [])
    active = bool(payload.get("active"))
    changed = False
    if active and me not in liked_by:
        liked_by.add(me)
        changed = True
    elif not active and me in liked_by:
        liked_by.discard(me)
        changed = True
    if changed:
        data["case_liked_by"] = sorted(liked_by)
        data["case_likes"] = len(liked_by)
        try:
            save_canvas_light(data)
        except Exception:
            pass
    return {"code": 0, "data": {
        "workId": str(record.get("id") or ""),
        "versionId": "v1",
        "ownerUserId": str(record.get("owner_email") or ""),
        "changed": changed,
        "active": me in liked_by,
        "likeCount": len(liked_by),
    }, "msg": "ok"}


@app.post("/api/public/works/{slug}/community/follow")
async def vz_public_work_follow(slug: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    item = _vz_public_work_record(slug)
    if item is not None:
        public = _vz_work_public(item)
        if public is None:
            raise HTTPException(status_code=404, detail="作品不存在或已停止公开")
        owner_email = clean_billing_email(item.get("ownerEmail") or "")
        if not owner_email:
            raise HTTPException(status_code=400, detail="该作品作者不可关注")
        active = bool(payload.get("active"))
        set_follow(email, owner_email, active)
        return {"code": 0, "data": {"changed": True, "active": active, "followerCount": author_follower_count(owner_email)}, "msg": "ok"}
    item = _vz_public_case_by_slug(slug)
    if item is None:
        raise HTTPException(status_code=404, detail="作品不存在或已停止公开")
    record, _ = item
    owner_email = str(record.get("owner_email") or record.get("case_published_by") or "")
    if not owner_email:
        raise HTTPException(status_code=400, detail="该作品作者不可关注")
    active = bool(payload.get("active"))
    set_follow(email, owner_email, active)
    return {"code": 0, "data": {"changed": True, "active": active, "followerCount": author_follower_count(owner_email)}, "msg": "ok"}


def _vz_username_to_email(username: str) -> str:
    username = str(username or "").strip()
    if not username:
        return ""
    try:
        for u in load_auth_users():
            if str(u.get("username") or u.get("name") or "") == username:
                e = clean_billing_email(u.get("email") or "")
                if e:
                    return e
    except Exception:
        pass
    for record, _ in _vz_public_case_list():
        e = clean_billing_email(str(record.get("owner_email") or record.get("case_published_by") or ""))
        if e and e.split("@")[0] == username:
            return e
    return ""


@app.get("/api/public/users/{username}")
async def vz_public_creator_get(username: str, request: Request, limit: int = 18, cursor: str = ""):
    email = authenticated_account_email(request, required=False)
    owner_email = _vz_username_to_email(username)
    if not owner_email:
        raise HTTPException(status_code=404, detail="创作者不存在")
    me = clean_billing_email(email or "")
    au = _vz_author_profile(owner_email)
    cases = await asyncio.to_thread(_vz_public_case_list)
    mine = [(r, d) for r, d in cases if str(r.get("owner_email") or r.get("case_published_by") or "") == owner_email]
    mine.sort(key=lambda x: -int(x[0].get("case_published_at") or x[0].get("case_submitted_at") or x[0].get("updated_at") or 0))
    limit = min(60, max(1, int(limit or 18)))
    offset = max(0, int(cursor or 0))
    page = mine[offset:offset + limit]
    items = [_vz_gallery_item(r, d, email) for r, d in page]
    received = sum(int(r.get("case_likes") or 0) for r, _ in mine)
    following = bool(me) and me in followed_emails(owner_email)
    profile = {
        "username": au["authorUsername"],
        "displayName": au["ownerDisplayName"],
        "bio": "",
        "avatarUrl": au["authorAvatarUrl"],
        "publishedWorkCount": len(mine),
        "receivedLikeCount": received,
        "followerCount": author_follower_count(owner_email),
        "followingCount": author_following_count(owner_email),
        "following": following,
        "canFollow": bool(me) and me != owner_email,
    }
    return {"code": 0, "data": {"profile": profile, "items": items, "nextCursor": str(offset + limit) if offset + limit < len(mine) else None}, "msg": "ok"}


@app.post("/api/public/users/{username}/follow")
async def vz_public_creator_follow(username: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    owner_email = _vz_username_to_email(username)
    if not owner_email:
        raise HTTPException(status_code=404, detail="创作者不存在")
    active = bool(payload.get("active"))
    set_follow(email, owner_email, active)
    return {"code": 0, "data": {"changed": True, "active": active, "followerCount": author_follower_count(owner_email)}, "msg": "ok"}


@app.post("/api/public/users/{username}/block")
async def vz_public_creator_block(username: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    return {"code": 0, "data": {"changed": False, "active": bool(payload.get("active")), "removedFollowCount": 0}, "msg": "ok"}


@app.get("/api/community/activity")
async def vz_community_activity(request: Request, view: str = "summary", page: int = 1, pageSize: int = 20):
    email = authenticated_account_email(request, required=False)
    me = clean_billing_email(email or "")
    if view == "summary":
        username = ""
        if email:
            try:
                username = str(_public_user(email).get("username") or email.split("@")[0])
            except Exception:
                username = email.split("@")[0]
        return {"code": 0, "data": {
            "view": "summary", "username": username,
            "publishedWorkCount": 0, "followingCount": author_following_count(me) if me else 0,
            "followerCount": author_follower_count(me) if me else 0, "likedWorkCount": 0,
            "publicProfileAvailable": bool(email),
        }, "msg": "ok"}
    return {"code": 0, "data": {"view": view, "items": [], "total": 0, "page": int(page), "pageSize": int(pageSize), "nextCursor": None}, "msg": "ok"}


@app.get("/api/notifications/interactions")
async def vz_interactions(request: Request, limit: int = 20, cursor: str = ""):
    email = authenticated_account_email(request, required=False)
    return {"code": 0, "data": {"items": [], "unreadCount": 0, "nextCursor": None}, "msg": "ok"}


@app.post("/api/notifications/interactions/read-all")
async def vz_interactions_read_all(request: Request):
    email = authenticated_account_email(request, required=False)
    return {"code": 0, "data": {"updated": 0}, "msg": "ok"}


@app.post("/api/notifications/interactions/{nid}/read")
async def vz_interactions_read(nid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    raise HTTPException(status_code=404, detail="通知不存在")


@app.post("/api/public/works/{slug}/report")
async def vz_public_report(slug: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    item = {
        "id": _vz_uuid("case"), "workId": slug, "versionId": "", "submitterUserId": email,
        "caseType": "report", "category": str(payload.get("category") or ""),
        "description": str(payload.get("description") or ""), "status": "open",
        "createdAt": str(_now_ms()), "updatedAt": str(_now_ms()),
    }
    return {"data": {"item": item}, "msg": "ok"}


@app.post("/api/works/{work_id}/appeal")
async def vz_work_appeal(work_id: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    item = {
        "id": _vz_uuid("case"), "workId": work_id, "versionId": str(payload.get("versionId") or ""),
        "submitterUserId": email, "caseType": "appeal", "category": "appeal",
        "description": str(payload.get("description") or ""), "status": "open",
        "createdAt": str(_now_ms()), "updatedAt": str(_now_ms()),
    }
    return {"data": {"item": item}, "msg": "ok"}


@app.get("/api/works/{work_id}/appeal")
async def vz_work_appeal_list(work_id: str, request: Request, page: int = 1, pageSize: int = 10):
    email = authenticated_account_email(request, required=False)
    return {"items": [], "total": 0, "page": int(page), "pageSize": int(pageSize)}


@app.get("/api/admin/work-cases")
async def vz_admin_work_cases(request: Request, page: int = 1, pageSize: int = 10, caseType: str = "", status: str = "", keyword: str = ""):
    email = authenticated_account_email(request, required=False)
    return {"items": [], "total": 0, "page": int(page), "pageSize": int(pageSize)}


@app.post("/api/admin/work-cases/{case_id}/resolve")
async def vz_admin_work_case_resolve(case_id: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    item = {"id": case_id, "status": str(payload.get("decision") or "approved"), "resolution": str(payload.get("resolution") or "")}
    return {"data": {"item": item}, "msg": "ok"}


@app.get("/api/drama/projects/{pid}/revision-guide")
async def vz_drama_revision_guide(pid: str, request: Request):
    email = authenticated_account_email(request, required=False)
    return {"data": {"guide": ""}, "msg": "ok"}


# ---------------------------------------------------------------------------
# 作品发布系统（Works Publication）— 与上游 VOZEB-PRO 行为一致
# 存储：data/vz/works.json（用户作品 + 版本 + 资产 + 审核状态）
# 提交审核自动通过（自动发布），管理端仍保留 review / take-down / feature。
# ---------------------------------------------------------------------------
VZ_WORKS_FILE = os.path.join(VZ_DATA_DIR, "works.json")
VZ_LOCKS["works"] = __import__("threading").Lock()

_WORK_VISIBILITIES = ("public", "unlisted", "private")
_WORK_AUTHOR_DISPLAYS = ("profile", "custom", "hidden")
_WORK_SOURCE_TYPES = ("media", "canvas", "drama")
_WORK_MODERATION = ("draft", "pending", "approved", "rejected", "taken_down")


def _vz_works() -> Dict[str, Any]:
    os.makedirs(VZ_DATA_DIR, exist_ok=True)
    data = read_json_store(VZ_WORKS_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("works", {})
    return data


def _vz_save_works(data: Dict[str, Any]):
    with VZ_LOCKS["works"]:
        write_json_store(VZ_WORKS_FILE, data)


def _vz_works_endpoint(func):
    @functools.wraps(func)
    async def _wrapped(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"code": 1, "data": None, "msg": str(exc.detail)})
        except Exception:
            import traceback
            traceback.print_exc()
            return JSONResponse(status_code=500, content={"code": 1, "data": None, "msg": "服务器内部错误"})

    return _wrapped


@app.post("/api/admin/works/{work_id}/feature")
@_vz_works_endpoint
async def vz_admin_work_feature(work_id: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request)
    if not email or not _vz_is_admin(email):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    work = _vz_works_find(work_id)
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    featured = bool(payload.get("featured"))
    work["isFeatured"] = featured
    if featured:
        work["featuredAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        work["featuredByUserId"] = clean_billing_email(email)
    work["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    data = _vz_works()
    data["works"][work_id] = work
    _vz_save_works(data)
    return {"code": 0, "data": {"work": _vz_work_full(work)}, "msg": "ok"}


def _vz_is_admin(email: str) -> bool:
    email = clean_billing_email(email or "")
    if not email:
        return False
    try:
        for u in load_auth_users():
            if clean_billing_email(u.get("email") or "") == email and (u.get("is_admin") or u.get("role") == "admin"):
                return True
    except Exception:
        pass
    try:
        if _public_user(email).get("role") == "admin":
            return True
    except Exception:
        pass
    return False


def _vz_media_candidate(storage_key: str, media_type: str, mime: str, url: str, name: str = "", size: int = 0):
    return {
        "storageKey": str(storage_key),
        "mediaType": media_type,
        "mimeType": mime,
        "originalName": str(name) or str(storage_key).split("/")[-1] or "媒体",
        "bytes": int(size or 0),
        "previewUrl": str(url),
    }


def _vz_drama_candidates(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen = set()

    def add(kind: str, url: Any, key: Any = None):
        url = str(url or "")
        if not url or url in seen:
            return
        seen.add(url)
        mime = "video/mp4" if kind == "video" else "audio/mpeg" if kind == "audio" else "image/png"
        candidates.append(_vz_media_candidate(key or f"{project.get('id')}-{kind}-{len(candidates)}", kind, mime, url))

    for ep in (project.get("episodes") or []):
        for s in (ep.get("shots") or []):
            if s.get("storyboardStatus") == "success" and s.get("storyboardImageUrl"):
                add("image", s.get("storyboardImageUrl"), s.get("storyboardTaskId") or f"shot-{s.get('id')}-frame")
            if s.get("storyboardEndStatus") == "success" and s.get("storyboardEndImageUrl"):
                add("image", s.get("storyboardEndImageUrl"), s.get("storyboardEndTaskId") or f"shot-{s.get('id')}-end")
            if s.get("generationStatus") == "success" and s.get("videoUrl"):
                add("video", s.get("videoUrl"), s.get("generationTaskId") or f"shot-{s.get('id')}-video")
            if s.get("audioStatus") == "success" and s.get("audioUrl"):
                add("audio", s.get("audioUrl"), s.get("audioTaskId") or f"shot-{s.get('id')}-audio")
    for src in (project.get("sourceAssets") or []):
        kind = str(src.get("type") or "")
        if kind not in ("image", "video", "audio"):
            continue
        url = str(src.get("serverUrl") or src.get("remoteUrl") or "")
        if not url:
            continue
        add(kind, url, src.get("storageKey") or src.get("id"))
    return candidates


def _vz_canvas_candidates(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen = set()
    cover = canvas_case_cover(data)
    if cover and cover not in seen:
        seen.add(cover)
        candidates.append(_vz_media_candidate("cover", "image", "image/png", cover, "封面"))
    for it in extract_canvas_assets(data):
        kind = str(it.get("kind") or "")
        url = str(it.get("url") or "")
        if kind not in ("image", "video", "audio") or not url or url in seen:
            continue
        seen.add(url)
        mime = "video/mp4" if kind == "video" else "audio/mpeg" if kind == "audio" else "image/png"
        candidates.append(_vz_media_candidate(str(it.get("id") or f"asset-{len(candidates)}"), kind, mime, url, str(it.get("name") or "")))
    return candidates


def _vz_media_candidates(email: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        main_mod = __import__("main")
        with main_mod.WORKBENCH_LIBRARY_LOCK:
            lib = main_mod.load_workbench_library()
        items = list((lib.get("users") or {}).get(email) or [])
    except Exception:
        pass
    candidates: List[Dict[str, Any]] = []
    for it in items:
        kind = "video" if str(it.get("type") or "") == "video" else "image"
        url = str(it.get("url") or "")
        if not url:
            continue
        mime = "video/mp4" if kind == "video" else "image/png"
        candidates.append(_vz_media_candidate(str(it.get("id") or f"lib-{len(candidates)}"), kind, mime, url, str(it.get("name") or "")))
    return candidates


def _vz_works_source(email: str, source_type: str, source_id: str) -> Dict[str, Any]:
    source_type = str(source_type or "")
    source_id = str(source_id or "")
    if source_type == "drama":
        data = _vz_drama()
        project = (data.get("projects") or {}).get(source_id)
        if not project:
            raise HTTPException(status_code=404, detail="短剧项目不存在")
        candidates = _vz_drama_candidates(project)
        if not candidates:
            raise HTTPException(status_code=409, detail="该短剧项目没有可发布的媒体")
        suggested = str(project.get("summary") or "")
        if not suggested:
            for ep in (project.get("episodes") or []):
                for s in (ep.get("shots") or []):
                    if s.get("imagePrompt"):
                        suggested = str(s.get("imagePrompt") or "")
                        break
                if suggested:
                    break
        return {
            "sourceType": source_type,
            "sourceId": source_id,
            "title": str(project.get("title") or "未命名短剧"),
            "suggestedPrompt": suggested,
            "candidates": candidates,
        }
    if source_type == "canvas":
        try:
            data = load_canvas_any(source_id)
        except Exception:
            raise HTTPException(status_code=404, detail="画布不存在")
        if data.get("deleted_at") or not case_is_live(data):
            raise HTTPException(status_code=404, detail="画布不存在")
        candidates = _vz_canvas_candidates(data)
        if not candidates:
            raise HTTPException(status_code=409, detail="该画布没有可发布的媒体")
        return {
            "sourceType": source_type,
            "sourceId": source_id,
            "title": case_display_title(data),
            "suggestedPrompt": str(data.get("public_prompt") or data.get("case_public_prompt") or ""),
            "candidates": candidates,
        }
    if source_type == "media":
        candidates = _vz_media_candidates(email)
        if source_id:
            candidates = [c for c in candidates if c["storageKey"] == source_id]
            if not candidates:
                raise HTTPException(status_code=404, detail="素材不存在")
        if not candidates:
            raise HTTPException(status_code=409, detail="素材库没有可发布的素材")
        return {
            "sourceType": source_type,
            "sourceId": source_id or str(candidates[0]["storageKey"]),
            "title": str(candidates[0]["originalName"]) if len(candidates) == 1 else "素材库",
            "suggestedPrompt": "",
            "candidates": candidates,
        }
    raise HTTPException(status_code=400, detail="不支持的来源类型")


def _vz_works_source_list(email: str, source_type: str, keyword: str = "", page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    source_type = str(source_type or "")
    keyword = str(keyword or "").strip().lower()
    items: List[Dict[str, Any]] = []

    def match(title: str) -> bool:
        return not keyword or keyword in str(title or "").lower()

    if source_type in ("", "drama"):
        data = _vz_drama()
        for p in (data.get("projects") or {}).values():
            if clean_billing_email(p.get("ownerEmail") or "") != clean_billing_email(email):
                continue
            if not match(p.get("title") or ""):
                continue
            shots = [s for ep in (p.get("episodes") or []) for s in (ep.get("shots") or [])]
            has_media = any(s.get("storyboardStatus") == "success" or s.get("generationStatus") == "success" for s in shots)
            items.append({"id": str(p.get("id")), "title": str(p.get("title") or "未命名短剧"), "kind": "video" if has_media else None, "updatedAt": str(p.get("updatedAt") or "")})
    if source_type in ("", "canvas"):
        for r, d in _vz_public_case_list():
            title = case_display_title(d)
            if not match(title):
                continue
            items.append({"id": str(r.get("id")), "title": title, "kind": None, "updatedAt": str(r.get("case_published_at") or r.get("updated_at") or "")})
    if source_type in ("", "media"):
        for c in _vz_media_candidates(email):
            if not match(c["originalName"]):
                continue
            items.append({"id": c["storageKey"], "title": c["originalName"], "kind": c["mediaType"], "updatedAt": ""})
    items.sort(key=lambda x: str(x.get("updatedAt") or ""), reverse=True)
    total = len(items)
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    start = (page - 1) * page_size
    return {"items": items[start:start + page_size], "total": total, "page": page, "pageSize": page_size}


def _vz_works_find(work_id: str) -> Optional[Dict[str, Any]]:
    work_id = str(work_id or "")
    if not work_id or len(work_id) > 80:
        return None
    data = _vz_works()
    return (data.get("works") or {}).get(work_id)


def _vz_works_slug_exists(slug: str) -> bool:
    slug = str(slug or "")
    if not slug:
        return False
    data = _vz_works()
    return any(str(w.get("slug") or w.get("id")) == slug for w in (data.get("works") or {}).values())


def _vz_work_version_without_assets(version: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in version.items() if k not in ("assets",)}


def _vz_work_full(work: Dict[str, Any]) -> Dict[str, Any]:
    versions = work.get("versions") or []
    current = None
    for v in versions:
        if v.get("id") == work.get("currentVersionId"):
            current = v
            break
    if current is None and versions:
        current = versions[-1]
    published = None
    if work.get("publishedVersionId"):
        for v in versions:
            if v.get("id") == work.get("publishedVersionId"):
                published = v
                break
    au = _vz_author_profile(str(work.get("ownerEmail") or ""))
    return {
        "id": work.get("id"),
        "ownerUserId": au.get("ownerUserId") or work.get("ownerEmail"),
        "ownerUsername": au.get("ownerUsername"),
        "ownerDisplayName": au.get("ownerDisplayName"),
        "ownerAccountId": work.get("ownerEmail"),
        "slug": work.get("slug") or work.get("id"),
        "sourceType": work.get("sourceType"),
        "sourceId": work.get("sourceId"),
        "lifecycleStatus": work.get("lifecycleStatus") or "active",
        "currentVersionId": current.get("id") if current else None,
        "publishedVersionId": work.get("publishedVersionId"),
        "isFeatured": bool(work.get("isFeatured")),
        "featuredAt": work.get("featuredAt"),
        "featuredByUserId": work.get("featuredByUserId"),
        "currentVersion": _vz_work_version_without_assets(current) if current else None,
        "publishedVersion": _vz_work_version_without_assets(published) if published else None,
        "currentPreview": _vz_work_preview(current) if current else None,
        "currentAssets": (current.get("assets") or []) if current else [],
        "publishedAssets": (published.get("assets") or []) if published else [],
        "viewCount": int(work.get("viewCount") or 0),
        "likeCount": int(work.get("likeCount") or 0),
        "lastViewedAt": work.get("lastViewedAt"),
        "revokedAt": work.get("revokedAt"),
        "createdAt": work.get("createdAt"),
        "updatedAt": work.get("updatedAt"),
    }


def _vz_work_preview(version: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for a in (version.get("assets") or []):
        if a.get("role") == "cover" or a.get("mediaType") in ("image", "video"):
            return {"id": a.get("storageKey"), "mediaType": a.get("mediaType"), "mimeType": a.get("mimeType"), "url": a.get("url") or ""}
    return None


def _vz_work_public(work: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    versions = work.get("versions") or []
    published = None
    for v in versions:
        if v.get("id") == work.get("publishedVersionId"):
            published = v
            break
    if published is None:
        return None
    if str(published.get("visibility") or "public") == "private":
        return None
    au = _vz_author_profile(str(work.get("ownerEmail") or ""))
    assets = []
    for a in (published.get("assets") or []):
        assets.append({
            "id": a.get("storageKey"),
            "mediaType": a.get("mediaType"),
            "mimeType": a.get("mimeType"),
            "role": a.get("role"),
            "sortOrder": a.get("sortOrder"),
            "metadata": a.get("metadata") or {},
            "url": a.get("url") or "",
        })
    return {
        "id": work.get("id"),
        "slug": work.get("slug") or work.get("id"),
        "sourceType": work.get("sourceType"),
        "viewCount": int(work.get("viewCount") or 0),
        "likeCount": int(work.get("likeCount") or 0),
        "publishedAt": str(published.get("submittedAt") or work.get("updatedAt") or ""),
        "title": published.get("title") or "",
        "description": published.get("description") or "",
        "publicPrompt": published.get("publicPrompt") or "",
        "category": published.get("category") or "",
        "tags": list(published.get("tags") or []),
        "visibility": published.get("visibility") or "public",
        "authorName": "" if str(published.get("authorDisplay") or "profile") == "hidden" else (published.get("authorName") or au.get("authorName") or ""),
        "authorUsername": au.get("authorUsername") or "",
        "authorAvatarUrl": au.get("authorAvatarUrl") or "",
        "assets": assets,
    }


def _vz_works_normalize(email: str, source: Dict[str, Any], input: Dict[str, Any], current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    candidates = {c["storageKey"]: c for c in (source.get("candidates") or [])}
    asset_keys = input.get("assetStorageKeys")
    if not isinstance(asset_keys, list) or not asset_keys:
        if current and (current.get("assets") or []):
            asset_keys = [a.get("storageKey") for a in current["assets"] if a.get("role") == "content"]
        else:
            asset_keys = [c["storageKey"] for c in (source.get("candidates") or [])]
    selected = [str(k) for k in asset_keys if str(k)]
    if not selected:
        raise HTTPException(status_code=409, detail="请至少选择一个作品媒体")
    for key in selected:
        if key not in candidates:
            raise HTTPException(status_code=400, detail="选择的媒体不属于当前来源")

    existing_cover = ""
    if current and (current.get("assets") or []):
        for a in current["assets"]:
            if a.get("role") == "cover":
                existing_cover = str(a.get("storageKey") or "")
    requested_cover = input.get("coverStorageKey")
    if requested_cover is None:
        cover_key = existing_cover
    else:
        cover_key = str(requested_cover or "")
    if not cover_key:
        cover_key = next((k for k in selected if candidates.get(k, {}).get("mediaType") == "image"), "")
    if cover_key and candidates.get(cover_key, {}).get("mediaType") != "image":
        raise HTTPException(status_code=400, detail="作品封面必须选择来源中的图片")

    title = str(input.get("title") if input.get("title") is not None else ((current or {}).get("title") if current else None) or source.get("title") or "")
    title = title.strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="请填写作品标题")
    public_prompt = str(input.get("publicPrompt") if input.get("publicPrompt") is not None else (((current or {}).get("publicPrompt") if current else None) or source.get("suggestedPrompt") or ""))
    public_prompt = public_prompt.strip()[:8000]
    if not public_prompt:
        raise HTTPException(status_code=400, detail="请填写公开提示词")
    description = str(input.get("description") or "")
    category = str(input.get("category") or "")[:40] or "其他"
    tags = input.get("tags") if isinstance(input.get("tags"), list) else []
    tags = [str(t).strip()[:40] for t in tags if str(t).strip()]
    tags = list(dict.fromkeys(tags))[:10]
    visibility = str(input.get("visibility") or "public")
    if visibility not in _WORK_VISIBILITIES:
        visibility = "public"
    author_display = str(input.get("authorDisplay") or "profile")
    if author_display not in _WORK_AUTHOR_DISPLAYS:
        author_display = "profile"
    user = None
    try:
        user = _public_user(email)
    except Exception:
        pass
    default_author = str((user or {}).get("displayName") or (user or {}).get("username") or "")
    if author_display == "hidden":
        author_name = ""
    elif author_display == "custom":
        author_name = str(input.get("authorName") or "").strip()[:80]
        if not author_name:
            raise HTTPException(status_code=400, detail="请填写展示作者名")
    else:
        author_name = default_author
    return {
        "selectedKeys": selected,
        "coverKey": cover_key,
        "versionFields": {
            "title": title,
            "description": description.strip()[:2000],
            "publicPrompt": public_prompt,
            "category": category,
            "tags": tags,
            "visibility": visibility,
            "authorDisplay": author_display,
            "authorName": author_name,
        },
    }


def _vz_works_build_version(work: Dict[str, Any], version_no: int, source: Dict[str, Any], draft: Dict[str, Any]) -> Dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    version_id = _vz_uuid("ver")
    version = {
        "id": version_id,
        "workId": work.get("id"),
        "versionNumber": version_no,
        "title": draft["versionFields"]["title"],
        "description": draft["versionFields"]["description"],
        "publicPrompt": draft["versionFields"]["publicPrompt"],
        "category": draft["versionFields"]["category"],
        "tags": draft["versionFields"]["tags"],
        "visibility": draft["versionFields"]["visibility"],
        "authorDisplay": draft["versionFields"]["authorDisplay"],
        "authorName": draft["versionFields"]["authorName"],
        "moderationStatus": "draft",
        "rejectionReason": None,
        "submittedAt": None,
        "reviewedAt": None,
        "reviewedByUserId": None,
        "moderationProvider": None,
        "moderationSignal": None,
        "createdAt": now,
        "updatedAt": now,
        "assets": [],
    }
    candidates = {c["storageKey"]: c for c in (source.get("candidates") or [])}
    sort_order = 0
    for key in draft["selectedKeys"]:
        cand = candidates.get(key)
        if not cand:
            continue
        role = "cover" if key == draft["coverKey"] else "content"
        version["assets"].append({
            "id": f"{version_id}-{sort_order}",
            "versionId": version_id,
            "storageKey": cand["storageKey"],
            "mediaType": cand["mediaType"],
            "mimeType": cand["mimeType"],
            "role": role,
            "sortOrder": sort_order,
            "metadata": {},
            "url": cand["previewUrl"],
            "createdAt": now,
        })
        sort_order += 1
    return version


def _vz_works_visible_slug() -> str:
    for _ in range(20):
        slug = _vz_uuid("w")
        if not _vz_works_slug_exists(slug):
            return slug
    return _vz_uuid("w")


@app.get("/api/works/sources")
@_vz_works_endpoint
async def vz_works_sources(request: Request, sourceType: str = "", sourceId: str = "", page: int = 1, pageSize: int = 20, keyword: str = ""):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    if sourceId:
        source = _vz_works_source(email, sourceType, sourceId)
        return {"code": 0, "data": {"source": source}, "msg": "ok"}
    return {"code": 0, "data": _vz_works_source_list(email, sourceType, keyword, page, pageSize), "msg": "ok"}


@app.get("/api/works")
@_vz_works_endpoint
async def vz_works_list(request: Request, page: int = 1, pageSize: int = 10, status: str = "", keyword: str = ""):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    email = clean_billing_email(email)
    status = str(status or "")
    keyword = str(keyword or "").strip().lower()
    data = _vz_works()
    works = []
    for work in (data.get("works") or {}).values():
        if clean_billing_email(work.get("ownerEmail") or "") != email:
            continue
        current = None
        for v in (work.get("versions") or []):
            if v.get("id") == work.get("currentVersionId"):
                current = v
                break
        if status and str((current or {}).get("moderationStatus") or "") != status:
            continue
        if keyword:
            title = str((current or {}).get("title") or "")
            slug = str(work.get("slug") or "")
            if keyword not in title.lower() and keyword not in slug.lower():
                continue
        works.append(work)
    works.sort(key=lambda w: str(w.get("updatedAt") or ""), reverse=True)
    total = len(works)
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(pageSize or 10)))
    start = (page - 1) * page_size
    items = [_vz_work_full(w) for w in works[start:start + page_size]]
    return {"code": 0, "data": {"items": items, "total": total, "page": page, "pageSize": page_size}, "msg": "ok"}


@app.post("/api/works")
@_vz_works_endpoint
async def vz_works_create(payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    source_type = str(payload.get("sourceType") or "")
    source_id = str(payload.get("sourceId") or "")
    if source_type not in _WORK_SOURCE_TYPES or not source_id:
        raise HTTPException(status_code=400, detail="请选择发布来源")
    source = _vz_works_source(email, source_type, source_id)
    draft = _vz_works_normalize(email, source, payload)
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    work_id = _vz_uuid("work")
    work = {
        "id": work_id,
        "slug": _vz_works_visible_slug(),
        "ownerEmail": clean_billing_email(email),
        "sourceType": source_type,
        "sourceId": source_id,
        "lifecycleStatus": "active",
        "isFeatured": False,
        "featuredAt": None,
        "featuredByUserId": None,
        "viewCount": 0,
        "likeCount": 0,
        "likedBy": [],
        "lastViewedAt": None,
        "revokedAt": None,
        "currentVersionId": None,
        "publishedVersionId": None,
        "versions": [],
        "createdAt": now,
        "updatedAt": now,
    }
    version = _vz_works_build_version(work, 1, source, draft)
    work["versions"] = [version]
    work["currentVersionId"] = version["id"]
    data = _vz_works()
    data["works"][work_id] = work
    _vz_save_works(data)
    return {"code": 0, "data": {"work": _vz_work_full(work)}, "msg": "ok"}


@app.get("/api/works/{work_id}")
@_vz_works_endpoint
async def vz_works_get(work_id: str, request: Request):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    work = _vz_works_find(work_id)
    if not work or clean_billing_email(work.get("ownerEmail") or "") != clean_billing_email(email):
        raise HTTPException(status_code=404, detail="作品不存在")
    return {"code": 0, "data": {"work": _vz_work_full(work)}, "msg": "ok"}


@app.patch("/api/works/{work_id}")
@_vz_works_endpoint
async def vz_works_patch(work_id: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    work = _vz_works_find(work_id)
    if not work or clean_billing_email(work.get("ownerEmail") or "") != clean_billing_email(email):
        raise HTTPException(status_code=404, detail="作品不存在")
    if work.get("lifecycleStatus") != "active":
        raise HTTPException(status_code=409, detail="作品已下架，不能继续编辑")
    current = None
    for v in (work.get("versions") or []):
        if v.get("id") == work.get("currentVersionId"):
            current = v
            break
    if current is None:
        raise HTTPException(status_code=409, detail="作品当前版本不存在")
    if current.get("moderationStatus") == "pending":
        raise HTTPException(status_code=409, detail="作品正在审核，不能编辑")
    source = _vz_works_source(email, str(work.get("sourceType") or ""), str(work.get("sourceId") or ""))
    draft = _vz_works_normalize(email, source, payload, current)
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    if current.get("moderationStatus") in ("draft", "rejected"):
        current.update(draft["versionFields"])
        current["updatedAt"] = now
        current["assets"] = []
        candidates = {c["storageKey"]: c for c in (source.get("candidates") or [])}
        sort_order = 0
        for key in draft["selectedKeys"]:
            cand = candidates.get(key)
            if not cand:
                continue
            current["assets"].append({
                "id": f"{current['id']}-{sort_order}",
                "versionId": current["id"],
                "storageKey": cand["storageKey"],
                "mediaType": cand["mediaType"],
                "mimeType": cand["mimeType"],
                "role": "cover" if key == draft["coverKey"] else "content",
                "sortOrder": sort_order,
                "metadata": {},
                "url": cand["previewUrl"],
                "createdAt": current.get("createdAt") or now,
            })
            sort_order += 1
        version = current
    else:
        version = _vz_works_build_version(work, int(work.get("versions")[-1].get("versionNumber") or 0) + 1, source, draft)
        work["versions"].append(version)
        work["currentVersionId"] = version["id"]
    work["updatedAt"] = now
    data = _vz_works()
    data["works"][work_id] = work
    _vz_save_works(data)
    return {"code": 0, "data": {"work": _vz_work_full(work)}, "msg": "ok"}


@app.delete("/api/works/{work_id}")
@_vz_works_endpoint
async def vz_works_delete(work_id: str, request: Request):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    email = clean_billing_email(email)
    work = _vz_works_find(work_id)
    if not work or (clean_billing_email(work.get("ownerEmail") or "") != email and not _vz_is_admin(email)):
        raise HTTPException(status_code=404, detail="作品不存在")
    data = _vz_works()
    del data["works"][work_id]
    _vz_save_works(data)
    return {"code": 0, "data": {"deletedId": work_id}, "msg": "ok"}


@app.post("/api/works/{work_id}/submit")
@_vz_works_endpoint
async def vz_works_submit(work_id: str, request: Request):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    work = _vz_works_find(work_id)
    if not work or clean_billing_email(work.get("ownerEmail") or "") != clean_billing_email(email):
        raise HTTPException(status_code=404, detail="作品不存在")
    if work.get("lifecycleStatus") != "active":
        raise HTTPException(status_code=409, detail="作品已下架")
    current = None
    for v in (work.get("versions") or []):
        if v.get("id") == work.get("currentVersionId"):
            current = v
            break
    if current is None:
        raise HTTPException(status_code=409, detail="作品当前版本不存在")
    status_now = current.get("moderationStatus")
    if status_now in ("pending", "approved"):
        return {"code": 0, "data": {"work": _vz_work_full(work)}, "msg": "ok"}
    if status_now == "taken_down":
        raise HTTPException(status_code=409, detail="下架版本需要先编辑再提交")
    if not current.get("publicPrompt"):
        raise HTTPException(status_code=409, detail="请填写公开提示词")
    if not any(a.get("role") == "content" for a in (current.get("assets") or [])):
        raise HTTPException(status_code=409, detail="作品没有可发布媒体")
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    current["moderationStatus"] = "approved"
    current["submittedAt"] = now
    current["reviewedAt"] = now
    current["reviewedByUserId"] = None
    current["updatedAt"] = now
    work["publishedVersionId"] = current["id"]
    work["updatedAt"] = now
    data = _vz_works()
    data["works"][work_id] = work
    _vz_save_works(data)
    return {"code": 0, "data": {"work": _vz_work_full(work)}, "msg": "ok"}


@app.post("/api/works/{work_id}/revoke")
@_vz_works_endpoint
async def vz_works_revoke(work_id: str, request: Request):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    work = _vz_works_find(work_id)
    if not work or clean_billing_email(work.get("ownerEmail") or "") != clean_billing_email(email):
        raise HTTPException(status_code=404, detail="作品不存在")
    work["lifecycleStatus"] = "revoked"
    work["revokedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    work["updatedAt"] = work["revokedAt"]
    data = _vz_works()
    data["works"][work_id] = work
    _vz_save_works(data)
    return {"code": 0, "data": {"work": _vz_work_full(work)}, "msg": "ok"}


@app.post("/api/works/{work_id}/relist")
@_vz_works_endpoint
async def vz_works_relist(work_id: str, request: Request):
    email = authenticated_account_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="请先登录")
    work = _vz_works_find(work_id)
    if not work or clean_billing_email(work.get("ownerEmail") or "") != clean_billing_email(email):
        raise HTTPException(status_code=404, detail="作品不存在")
    if work.get("lifecycleStatus") != "revoked":
        return {"code": 0, "data": {"work": _vz_work_full(work)}, "msg": "ok"}
    work["lifecycleStatus"] = "active"
    work["revokedAt"] = None
    work["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    data = _vz_works()
    data["works"][work_id] = work
    _vz_save_works(data)
    return {"code": 0, "data": {"work": _vz_work_full(work)}, "msg": "ok"}


@app.post("/api/works/{work_id}/appeal")
@_vz_works_endpoint
async def vz_works_appeal(work_id: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request, required=False)
    work = _vz_works_find(work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    item = {
        "id": _vz_uuid("case"), "workId": work_id, "versionId": str(payload.get("versionId") or ""),
        "submitterUserId": email, "caseType": "appeal", "category": "appeal",
        "description": str(payload.get("description") or ""), "status": "open",
        "createdAt": str(_now_ms()), "updatedAt": str(_now_ms()),
    }
    return {"code": 0, "data": {"item": item}, "msg": "ok"}


@app.get("/api/admin/works")
@_vz_works_endpoint
async def vz_admin_works_list(request: Request, page: int = 1, pageSize: int = 10, status: str = "", lifecycleStatus: str = "", keyword: str = ""):
    email = authenticated_account_email(request)
    if not email or not _vz_is_admin(email):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    status = str(status or "")
    keyword = str(keyword or "").strip().lower()
    data = _vz_works()
    works = []
    for work in (data.get("works") or {}).values():
        current = None
        for v in (work.get("versions") or []):
            if v.get("id") == work.get("currentVersionId"):
                current = v
                break
        if status and str((current or {}).get("moderationStatus") or "") != status:
            continue
        if lifecycleStatus and str(work.get("lifecycleStatus") or "") != lifecycleStatus:
            continue
        if keyword:
            title = str((current or {}).get("title") or "")
            slug = str(work.get("slug") or "")
            owner = str(work.get("ownerEmail") or "")
            if keyword not in title.lower() and keyword not in slug.lower() and keyword not in owner.lower():
                continue
        works.append(work)
    works.sort(key=lambda w: str(w.get("updatedAt") or ""), reverse=True)
    total = len(works)
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(pageSize or 10)))
    start = (page - 1) * page_size
    items = [_vz_work_full(w) for w in works[start:start + page_size]]
    return {"code": 0, "data": {"items": items, "total": total, "page": page, "pageSize": page_size}, "msg": "ok"}


@app.post("/api/admin/works/{work_id}/review")
@_vz_works_endpoint
async def vz_admin_work_review(work_id: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request)
    if not email or not _vz_is_admin(email):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    work = _vz_works_find(work_id)
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    version_id = str(payload.get("versionId") or "")
    decision = str(payload.get("decision") or "")
    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="无效的审核决定")
    target = None
    for v in (work.get("versions") or []):
        if v.get("id") == version_id:
            target = v
            break
    if target is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    target["moderationStatus"] = decision
    target["reviewedAt"] = now
    target["reviewedByUserId"] = clean_billing_email(email)
    target["rejectionReason"] = str(payload.get("reason") or "") if decision == "rejected" else None
    if decision == "approved":
        work["publishedVersionId"] = target["id"]
    work["updatedAt"] = now
    data = _vz_works()
    data["works"][work_id] = work
    _vz_save_works(data)
    return {"code": 0, "data": {"work": _vz_work_full(work)}, "msg": "ok"}


@app.post("/api/admin/works/{work_id}/take-down")
@_vz_works_endpoint
async def vz_admin_work_take_down(work_id: str, payload: Dict[str, Any], request: Request):
    email = authenticated_account_email(request)
    if not email or not _vz_is_admin(email):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    work = _vz_works_find(work_id)
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    current = None
    for v in (work.get("versions") or []):
        if v.get("id") == work.get("currentVersionId"):
            current = v
            break
    if current is not None:
        current["moderationStatus"] = "taken_down"
        current["reviewedAt"] = now
        current["reviewedByUserId"] = clean_billing_email(email)
        current["rejectionReason"] = str(payload.get("reason") or "")
        current["updatedAt"] = now
    work["updatedAt"] = now
    data = _vz_works()
    data["works"][work_id] = work
    _vz_save_works(data)
    return {"code": 0, "data": {"work": _vz_work_full(work)}, "msg": "ok"}


def _vz_public_work_record(slug: str) -> Optional[Dict[str, Any]]:
    slug = str(slug or "")
    if not slug or len(slug) > 80:
        return None
    data = _vz_works()
    for work in (data.get("works") or {}).values():
        if str(work.get("slug") or "") == slug or str(work.get("id") or "") == slug:
            return work
    return None
