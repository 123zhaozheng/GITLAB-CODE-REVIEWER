"""
ESB 中间件 - 自动处理 ESB 请求和响应的包裹
"""
import logging
from typing import Callable, Dict, Any
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import json

from core.esb_utils import EsbWrapper, EsbRespStatus

logger = logging.getLogger(__name__)


class EsbMiddleware(BaseHTTPMiddleware):
    """
    ESB 中间件

    自动处理 ESB 格式的请求和响应：
    1. 解包 ESB 请求，提取业务数据
    2. 将业务数据传递给路由处理
    3. 将路由响应包裹为 ESB 格式
    """

    def __init__(self, app: ASGIApp, esb_enabled_paths: list = None):
        """
        初始化 ESB 中间件

        Args:
            app: ASGI 应用
            esb_enabled_paths: 需要启用 ESB 包裹的路径列表（支持前缀匹配）
                              如果为 None，则对所有路径启用
        """
        super().__init__(app)
        self.esb_enabled_paths = esb_enabled_paths or ["/esb/"]

    def _should_process_esb(self, path: str) -> bool:
        """
        判断是否需要处理 ESB 包裹

        Args:
            path: 请求路径

        Returns:
            bool: 是否需要处理
        """
        return any(path.startswith(prefix) for prefix in self.esb_enabled_paths)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        处理请求和响应

        Args:
            request: 请求对象
            call_next: 下一个中间件或路由处理器

        Returns:
            Response: 响应对象
        """
        # 检查是否需要处理 ESB 格式
        if not self._should_process_esb(request.url.path):
            return await call_next(request)

        # 只处理 POST 请求
        if request.method != "POST":
            return await call_next(request)

        try:
            # 读取原始请求体
            body = await request.body()

            # 解析 ESB 请求
            try:
                esb_request = json.loads(body)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in ESB request: {e}")
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": True,
                        "message": "Invalid JSON format"
                    }
                )

            # 验证 ESB 请求格式
            if "ReqInfo" not in esb_request or "Request" not in esb_request:
                logger.error("Invalid ESB request format: missing ReqInfo or Request")
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": True,
                        "message": "Invalid ESB request format: missing 'ReqInfo' or 'Request'"
                    }
                )

            # 解包业务数据
            business_data = EsbWrapper.unwrap_request(esb_request)
            logger.info(f"ESB request unwrapped for path: {request.url.path}")

            # 将业务数据重新封装为请求体
            # 注意：这里我们需要修改 request 对象，但 Request 对象是不可变的
            # 所以我们将 ESB 请求存储在 request.state 中供后续使用
            request.state.esb_request = esb_request
            request.state.business_data = business_data

            # 创建新的请求体
            new_body = json.dumps(business_data).encode()

            # 重建请求对象（需要特殊处理）
            async def receive():
                return {"type": "http.request", "body": new_body}

            # 修改 request._receive 以使用新的 body
            request._receive = receive

            # 调用下一个处理器
            response = await call_next(request)

            # 读取响应内容
            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk

            # 解析响应
            try:
                business_response = json.loads(response_body)
            except json.JSONDecodeError:
                # 如果响应不是 JSON，直接返回
                logger.warning("Response is not JSON, returning as-is")
                return Response(
                    content=response_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type
                )

            # 包裹响应
            if response.status_code == 200:
                esb_response = EsbWrapper.wrap_response(
                    esb_request=esb_request,
                    business_data=business_response,
                    resp_st=EsbRespStatus.SUCCESS,
                    resp_info_code="0000",
                    desc="成功"
                )
            else:
                # 处理错误响应
                error_message = business_response.get("message", "Unknown error")
                esb_response = EsbWrapper.wrap_error_response(
                    esb_request=esb_request,
                    error_message=error_message,
                    error_code=str(response.status_code)
                )

            logger.info(f"ESB response wrapped for path: {request.url.path}")

            # 返回包裹后的响应
            return JSONResponse(
                content=esb_response,
                status_code=200,  # ESB 格式总是返回 200，错误信息在 RspInfo 中
                headers={"Content-Type": "application/json"}
            )

        except Exception as e:
            logger.error(f"Error in ESB middleware: {e}", exc_info=True)

            # 尝试构造错误响应
            try:
                if hasattr(request.state, 'esb_request'):
                    esb_response = EsbWrapper.wrap_error_response(
                        esb_request=request.state.esb_request,
                        error_message=str(e),
                        error_code="9999"
                    )
                    return JSONResponse(content=esb_response, status_code=200)
            except:
                pass

            # 如果无法构造 ESB 响应，返回普通错误
            return JSONResponse(
                status_code=500,
                content={
                    "error": True,
                    "message": f"Internal server error: {str(e)}"
                }
            )
