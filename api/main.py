"""
FastAPI主应用 - GitLab代码审查服务的REST API接口
重构版本：只保留 /review 接口，全部通过 ESB 集成
"""
import uuid
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from core.reviewer import GitLabReviewer
from core.task_manager import init_task_manager, cleanup_task_manager, get_task_manager
from core.redis_client import get_redis_manager, close_redis_connection
from config.settings import settings, REVIEW_TYPES
from api.esb_middleware import EsbMiddleware

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="GitLab Code Reviewer",
    description="基于AI的GitLab代码审查服务 - ESB集成版",
    version=settings.service_version,
    docs_url="/docs",
    redoc_url="/redoc"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_hosts,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加 ESB 中间件 - 所有 /review 开头的路径都通过 ESB
app.add_middleware(
    EsbMiddleware,
    esb_enabled_paths=["/review"]
)

# Pydantic模型定义
class ReviewRequest(BaseModel):
    """审查请求模型 - 支持MR和分支比较模式"""
    gitlab_url: str = Field(..., description="GitLab实例URL")
    project_id: str = Field(..., description="项目ID")
    access_token: str = Field(..., description="GitLab访问令牌")

    # 模式选择
    mode: str = Field(default="mr", description="审查模式: 'mr' 或 'branch_compare'")

    # MR模式所需参数
    mr_id: Optional[int] = Field(default=None, gt=0, description="Merge Request ID (mode='mr'时必需)")

    # 分支比较模式所需参数
    target_branch: Optional[str] = Field(default=None, description="目标分支 (mode='branch_compare'时必需)")
    source_branch: Optional[str] = Field(default=None, description="源分支 (mode='branch_compare'时必需)")

    # 历史问题追踪
    devops_task_id: Optional[str] = Field(default=None, description="DevOps任务/工作项编号（用于历史问题追踪和复检）")

    review_type: str = Field(default="full", description="审查类型")
    ai_model: Optional[str] = Field(default=None, description="AI模型名称")
    options: Optional[Dict[str, Any]] = Field(default_factory=dict, description="额外选项")

    @field_validator('review_type')
    @classmethod
    def validate_review_type(cls, v):
        if v not in REVIEW_TYPES:
            raise ValueError(f'review_type must be one of: {list(REVIEW_TYPES.keys())}')
        return v

    @field_validator('gitlab_url')
    @classmethod
    def validate_gitlab_url(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError('gitlab_url must start with http:// or https://')
        return v.rstrip('/')


class ReviewResponse(BaseModel):
    """审查响应模型"""
    review_id: str
    status: str
    score: float = Field(ge=0, le=10)
    summary: str
    findings: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    mr_info: Dict[str, Any] = Field(default_factory=dict)
    statistics: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str
    timestamp: str


# 全局变量
app_start_time = datetime.now()


# 依赖函数
async def get_reviewer(request: ReviewRequest) -> GitLabReviewer:
    """创建审查器实例"""
    try:
        reviewer = GitLabReviewer(
            gitlab_url=request.gitlab_url,
            access_token=request.access_token,
            ai_model=request.ai_model
        )
        return reviewer
    except Exception as e:
        logger.error(f"Failed to create reviewer: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to initialize reviewer: {str(e)}"
        )


async def execute_review_task(task_id: str, request: ReviewRequest):
    """
    后台执行审查任务

    Args:
        task_id: 任务ID
        request: 审查请求
    """
    try:
        task_mgr = get_task_manager()

        # 进度回调函数
        async def update_progress(progress: int, message: str):
            await task_mgr.update_progress(task_id, progress, message)

        # 更新进度：开始
        await update_progress(10, "初始化审查器...")

        # 创建审查器
        reviewer = GitLabReviewer(
            gitlab_url=request.gitlab_url,
            access_token=request.access_token,
            ai_model=request.ai_model
        )

        await update_progress(20, "开始执行审查...")

        # 执行审查（根据模式）
        if request.mode == "mr":
            if not request.mr_id:
                raise ValueError("mr_id is required for 'mr' mode")

            await update_progress(30, f"审查 MR !{request.mr_id}...")
            result = await reviewer.review_merge_request(
                project_id=request.project_id,
                mr_id=request.mr_id,
                review_type=request.review_type,
                options=request.options
            )

        elif request.mode == "branch_compare":
            if not request.target_branch or not request.source_branch:
                raise ValueError("target_branch and source_branch are required for 'branch_compare' mode")

            await update_progress(30, f"比较分支 {request.source_branch} vs {request.target_branch}...")
            result = await reviewer.review_branch_comparison(
                project_id=request.project_id,
                target_branch=request.target_branch,
                source_branch=request.source_branch,
                review_type=request.review_type,
                task_id=request.devops_task_id
            )
        else:
            raise ValueError(f"Invalid mode: {request.mode}")

        await update_progress(90, "审查完成，保存结果...")

        # 完成任务（会自动设置状态为completed，进度为100）
        await task_mgr.complete_task(task_id, result)

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        task_mgr = get_task_manager()
        await task_mgr.fail_task(task_id, str(e))


# ============================================================================
# API 路由定义 - 所有路由都通过 ESB 中间件
# ============================================================================

@app.get("/", response_model=Dict[str, str])
async def root():
    """根路径 - API信息"""
    return {
        "message": "GitLab Code Reviewer API - ESB Integration",
        "version": settings.service_version,
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    return HealthResponse(
        status="healthy",
        version=settings.service_version,
        timestamp=datetime.now().isoformat()
    )


@app.post("/review", response_model=ReviewResponse)
async def review_merge_request(
    request: ReviewRequest,
    reviewer: GitLabReviewer = Depends(get_reviewer)
):
    """
    执行同步代码审查（通过 ESB）

    支持两种模式：
    - mr: 审查指定的 Merge Request
    - branch_compare: 比较两个分支

    此接口会立即返回审查结果（可能耗时较长）
    对于长时间任务，建议使用 /review/async 接口
    """
    try:
        logger.info(f"[ESB] Starting sync review for project {request.project_id}")

        if request.mode == "mr":
            if not request.mr_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="mr_id is required for 'mr' mode"
                )

            logger.info(f"[ESB] Mode: MR review for !{request.mr_id}")
            result = await reviewer.review_merge_request(
                project_id=request.project_id,
                mr_id=request.mr_id,
                review_type=request.review_type,
                options=request.options
            )

        elif request.mode == "branch_compare":
            if not request.target_branch or not request.source_branch:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="target_branch and source_branch are required for 'branch_compare' mode"
                )

            logger.info(f"[ESB] Mode: Branch comparison between '{request.source_branch}' and '{request.target_branch}'")
            result = await reviewer.review_branch_comparison(
                project_id=request.project_id,
                target_branch=request.target_branch,
                source_branch=request.source_branch,
                review_type=request.review_type,
                task_id=request.devops_task_id
            )

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid mode: '{request.mode}'. Must be 'mr' or 'branch_compare'."
            )

        logger.info(f"[ESB] Review completed with score {result['score']}")
        return ReviewResponse(**result)

    except ValueError as e:
        logger.error(f"[ESB] Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"[ESB] Review failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Review failed: {str(e)}"
        )


@app.post("/review/async")
async def async_review(request: ReviewRequest, background_tasks: BackgroundTasks):
    """
    提交异步审查任务（通过 ESB） - 立即返回任务ID

    适用于长时间运行的审查任务，客户端可以通过轮询获取进度和结果

    返回：
    - task_id: 任务ID
    - status: 任务状态
    - message: 提示信息
    - progress_url: 进度查询URL
    - result_url: 结果查询URL
    """
    try:
        task_id = str(uuid.uuid4())
        task_mgr = get_task_manager()

        # 创建任务
        await task_mgr.create_task(task_id)

        # 后台执行
        background_tasks.add_task(
            execute_review_task,
            task_id,
            request
        )

        logger.info(f"[ESB] Async task {task_id} created for project {request.project_id}")

        return {
            "task_id": task_id,
            "status": "pending",
            "message": "任务已提交，请使用task_id查询进度",
            "progress_url": f"/review/{task_id}/progress",
            "result_url": f"/review/{task_id}/result"
        }

    except Exception as e:
        logger.error(f"[ESB] Failed to create async review task: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {str(e)}"
        )


@app.get("/review/{task_id}/progress")
async def get_task_progress(task_id: str):
    """
    获取任务进度（通过 ESB）

    返回当前任务的执行状态和进度百分比

    返回：
    - task_id: 任务ID
    - status: 任务状态 (pending/running/completed/failed)
    - progress: 进度百分比 (0-100)
    - message: 当前状态消息
    - created_at: 任务创建时间
    - updated_at: 最后更新时间
    """
    try:
        task_mgr = get_task_manager()
        task = await task_mgr.get_task(task_id)

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )

        return {
            "task_id": task_id,
            "status": task.status,
            "progress": task.progress,
            "message": task.message,
            "created_at": task.created_at,
            "updated_at": task.updated_at
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ESB] Failed to get task progress: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get progress: {str(e)}"
        )


@app.get("/review/{task_id}/result")
async def get_task_result(task_id: str):
    """
    获取任务结果（通过 ESB）

    如果任务完成，返回完整的审查结果；否则返回当前状态

    返回：
    - 如果 completed: { task_id, status: "completed", result: {...} }
    - 如果 failed: { task_id, status: "failed", error: "..." }
    - 如果 pending/running: { task_id, status, progress, message }
    """
    try:
        task_mgr = get_task_manager()
        task = await task_mgr.get_task(task_id)

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )

        if task.status == "completed":
            return {
                "task_id": task_id,
                "status": "completed",
                "result": task.result
            }
        elif task.status == "failed":
            return {
                "task_id": task_id,
                "status": "failed",
                "error": task.error
            }
        else:
            return {
                "task_id": task_id,
                "status": task.status,
                "progress": task.progress,
                "message": task.message
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ESB] Failed to get task result: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get result: {str(e)}"
        )


# ============================================================================
# 错误处理
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """HTTP异常处理器"""
    logger.error(f"HTTP {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.now().isoformat()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """通用异常处理器"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "message": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now().isoformat()
        }
    )


# ============================================================================
# 启动/关闭事件
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info(f"GitLab Code Reviewer API v{settings.service_version} starting up")
    logger.info(f"ESB Integration: Enabled for /review paths")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Default AI model: {settings.default_ai_model}")

    # 初始化共享的 Redis 连接
    logger.info(f"Initializing shared Redis connection: {settings.redis_url}")
    redis_manager = get_redis_manager()
    redis_client = await redis_manager.connect()

    if redis_client:
        logger.info("✓ Redis connection successful")
    else:
        logger.warning("✗ Redis connection failed - cache and tasks may not work")

    # 初始化 TaskManager（现在使用共享的 Redis 连接）
    logger.info("Initializing TaskManager (using shared Redis connection)")
    init_task_manager(task_ttl=settings.redis_task_ttl)


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info("GitLab Code Reviewer API shutting down")

    # 清理 TaskManager
    await cleanup_task_manager()
    logger.info("TaskManager cleaned up")

    # 关闭共享的 Redis 连接
    await close_redis_connection()
    logger.info("Redis connection closed")


# 开发模式启动
if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
