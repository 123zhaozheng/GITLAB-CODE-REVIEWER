"""
ESB 依赖与按路由注入的包装器

目的
- 替代全局中间件的做法，只在标记的接口上进行 ESB 解包与回包。
- 保持“可感知”的能力：如果请求不是 ESB 包（例如直接调用接口），则按原样透传，不做转换。

实现要点
- EsbRoute: 自定义 APIRoute，在路由级别拦截请求/响应，完成 ESB 解包与回包。
- get_esb_ctx: FastAPI 依赖，允许在业务处理函数中读取原始 ESB 请求上下文（可选）。
"""
from __future__ import annotations

import json
import logging
from typing import Callable, Optional, Dict, Any

from fastapi import Request, Response, Depends
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from core.esb_utils import EsbWrapper, EsbRespStatus

logger = logging.getLogger(__name__)


class EsbRoute(APIRoute):
    """
    按路由启用的 ESB 包装器：
    - 如果请求体符合 ESB 结构（包含 ReqInfo/Request），则解包并把业务数据注入到下游；
    - 调用下游后，如果有 ESB 上下文，则把业务响应回包为 ESB 格式并固定返回 200；
    - 如果请求不是 ESB 结构，则不做任何处理（方便内部/调试直连）。
    """

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            esb_request: Optional[Dict[str, Any]] = None
            new_body_bytes: Optional[bytes] = None

            # 仅在 POST/PUT/PATCH 时尝试解包（GET/DELETE 无请求体）
            if request.method in ("POST", "PUT", "PATCH"):
                try:
                    raw = await request.body()
                    if raw:
                        # 试图解析为 JSON 并判断是否为 ESB 包
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict) and "ReqInfo" in parsed and "Request" in parsed:
                            esb_request = parsed
                            business_data = EsbWrapper.unwrap_request(parsed)
                            new_body_bytes = json.dumps(business_data).encode("utf-8")
                            logger.info(f"[ESB] Unwrapped request on {request.url.path}")
                except json.JSONDecodeError:
                    # 不是 JSON，按原样透传，交由原路由处理
                    logger.debug("[ESB] Non-JSON body, bypassing ESB unwrap")
                except Exception as e:
                    logger.error(f"[ESB] Failed to unwrap ESB request: {e}", exc_info=True)
                    # 这里直接返回 ESB 错误包（若无法解析出 ReqInfo 也按普通 400 返回）
                    if esb_request:
                        esb_error = EsbWrapper.wrap_error_response(
                            esb_request=esb_request,
                            error_message=str(e),
                            error_code="4001",
                        )
                        return JSONResponse(content=esb_error, status_code=200)
                    return JSONResponse(
                        status_code=400,
                        content={"error": True, "message": f"Invalid ESB request: {str(e)}"},
                    )

            # 如已解包，用新的 body 替换 request._receive，并把上下文挂到 request.state
            if esb_request and new_body_bytes is not None:
                async def receive() -> Dict[str, Any]:
                    # 返回一次包含新 body 的 http.request 事件，并声明没有更多分片
                    return {"type": "http.request", "body": new_body_bytes, "more_body": False}

                # 覆盖底层接收函数与缓存的 body，确保 FastAPI 后续读取到的是新内容
                request._receive = receive  # type: ignore[attr-defined]
                setattr(request, "_body", new_body_bytes)  # Starlette 会缓存 body；需要同步覆盖
                request.state.esb_request = esb_request

            # 执行业务处理
            response = await original_route_handler(request)

            # 如果没有 ESB 上下文，直接返回原始响应（兼容直连/非 ESB 调用）
            if not getattr(request.state, "esb_request", None):
                return response

            # 读取业务响应并回包
            try:
                # 读取响应内容为 bytes
                body_bytes: bytes = b""

                # Starlette 在 BaseHTTPMiddleware 流程下多为 StreamingResponse（有 body_iterator）
                # 但在路由级包装里，常见的是 JSONResponse/Response（没有 body_iterator）。
                if hasattr(response, "body_iterator"):
                    # 流式：把迭代器消费为 bytes
                    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                        body_bytes += chunk
                else:
                    # 非流式：直接读取已渲染的 body
                    raw = getattr(response, "body", b"")
                    if raw is None:
                        body_bytes = b""
                    elif isinstance(raw, (bytes, bytearray, memoryview)):
                        body_bytes = bytes(raw)
                    else:
                        # 兜底：尝试 bytes() 转换
                        body_bytes = bytes(raw)

                # 如果不是 JSON，按原样透传（少数场景下可能需要，但通常 ESB 期望 JSON）
                try:
                    business_resp = json.loads(body_bytes) if body_bytes else {}
                except json.JSONDecodeError:
                    logger.warning("[ESB] Response is not JSON, returning as-is")
                    return Response(
                        content=body_bytes,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        media_type=response.media_type,
                        background=getattr(response, "background", None),
                    )

                # 业务返回 2xx -> ESB 成功包；否则 -> ESB 失败包
                if 200 <= response.status_code < 300:
                    esb_resp = EsbWrapper.wrap_response(
                        esb_request=request.state.esb_request,
                        business_data=business_resp,
                        resp_st=EsbRespStatus.SUCCESS,
                        resp_info_code="0000",
                        desc="成功",
                    )
                else:
                    msg = business_resp.get("message") or business_resp.get("detail") or "Unknown error"
                    esb_resp = EsbWrapper.wrap_error_response(
                        esb_request=request.state.esb_request,
                        error_message=msg,
                        error_code=str(response.status_code),
                    )

                # ESB 规范：HTTP 固定 200，真实状态在 RspInfo 中体现
                # 透传除 content-length 外的头，并保留 background 任务
                passthrough_headers = {
                    k: v for k, v in dict(response.headers).items()
                    if k.lower() != "content-length"
                }
                return JSONResponse(
                    content=esb_resp,
                    status_code=200,
                    headers=passthrough_headers,
                    background=getattr(response, "background", None),
                )

            except Exception as e:
                logger.error(f"[ESB] Failed to wrap ESB response: {e}", exc_info=True)
                try:
                    esb_resp = EsbWrapper.wrap_error_response(
                        esb_request=request.state.esb_request,
                        error_message=str(e),
                        error_code="9999",
                    )
                    return JSONResponse(
                        content=esb_resp,
                        status_code=200,
                        background=getattr(response, "background", None),
                    )
                except Exception:
                    # 若连 ESB 回包都失败，则退回 500 普通响应
                    return JSONResponse(status_code=500, content={"error": True, "message": "Internal server error"})

        return custom_route_handler


def get_esb_ctx(request: Request) -> Optional[Dict[str, Any]]:
    """
    依赖：获取 ESB 上下文（原始 ESB 请求对象）。
    - 在使用 EsbRoute 的接口中可用；
    - 业务处理代码可选依赖它来获取原始 ReqInfo 等字段。
    """
    return getattr(request.state, "esb_request", None)
