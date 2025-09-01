"""
FastAPI主应用 - GitLab代码审查服务的REST API接口
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
import os

from core.reviewer import GitLabReviewer
from config.settings import settings, REVIEW_TYPES

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="GitLab Code Reviewer",
    description="基于AI的GitLab代码审查服务",
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

class CommentRequest(BaseModel):
    """评论请求模型"""
    gitlab_url: str
    project_id: str
    mr_id: int = Field(gt=0)
    access_token: str
    review_result: Dict[str, Any]
    format_type: str = Field(default="markdown", pattern="^(markdown|plain)$")

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str
    timestamp: str
    uptime: str

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

# API路由定义

@app.get("/", response_model=Dict[str, str])
async def root():
    """根路径 - API信息"""
    return {
        "message": "GitLab Code Reviewer API",
        "version": settings.service_version,
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    uptime = datetime.now() - app_start_time
    return HealthResponse(
        status="healthy",
        version=settings.service_version,
        timestamp=datetime.now().isoformat(),
        uptime=str(uptime)
    )

@app.get("/review-types")
async def get_review_types():
    """获取支持的审查类型"""
    return {
        "review_types": REVIEW_TYPES,
        "description": "支持的代码审查类型及其说明"
    }

@app.post("/review", response_model=ReviewResponse)
async def review_merge_request(
    request: ReviewRequest,
    background_tasks: BackgroundTasks,
    reviewer: GitLabReviewer = Depends(get_reviewer)
):
    """
    执行完整的MR代码审查
    
    这是主要的审查接口，支持同步返回完整的审查结果。
    """
    try:
        logger.info(f"Starting review for project {request.project_id}")
        
        if request.mode == "mr":
            if not request.mr_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="mr_id is required for 'mr' mode")
            
            logger.info(f"Mode: MR review for !{request.mr_id}")
            result = await reviewer.review_merge_request(
                project_id=request.project_id,
                mr_id=request.mr_id,
                review_type=request.review_type,
                options=request.options
            )
        
        elif request.mode == "branch_compare":
            if not request.target_branch or not request.source_branch:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_branch and source_branch are required for 'branch_compare' mode")
            
            logger.info(f"Mode: Branch comparison between '{request.source_branch}' and '{request.target_branch}'")
            result = await reviewer.review_branch_comparison(
                project_id=request.project_id,
                target_branch=request.target_branch,
                source_branch=request.source_branch,
                review_type=request.review_type
            )
            
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid mode: '{request.mode}'. Must be 'mr' or 'branch_compare'.")

        logger.info(f"Review completed with score {result['score']}")
        return ReviewResponse(**result)
        
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Review failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Review failed: {str(e)}"
        )

@app.post("/review/stream")
async def stream_review(request: ReviewRequest):
    """
    流式代码审查 - 实时返回进度和结果
    
    适合长时间的审查任务，可以实时显示进度。
    """
    try:
        async def generate_stream():
            try:
                reviewer = GitLabReviewer(
                    gitlab_url=request.gitlab_url,
                    access_token=request.access_token,
                    ai_model=request.ai_model
                )
                
                async for chunk in reviewer.stream_review(
                    project_id=request.project_id,
                    mr_id=request.mr_id,
                    review_type=request.review_type
                ):
                    yield f"data: {chunk}\n\n"
                    
            except Exception as e:
                error_data = {
                    "type": "error",
                    "message": str(e),
                    "timestamp": datetime.now().isoformat()
                }
                yield f"data: {error_data}\n\n"
        
        return StreamingResponse(
            generate_stream(),
            media_type="text/plain",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )
        
    except Exception as e:
        logger.error(f"Stream review failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stream review failed: {str(e)}"
        )

@app.post("/review/comment")
async def post_review_comment(request: CommentRequest):
    """
    将审查结果发布为MR评论
    
    用于将审查结果自动发布到GitLab MR中。
    """
    try:
        reviewer = GitLabReviewer(
            gitlab_url=request.gitlab_url,
            access_token=request.access_token
        )
        
        comment_info = await reviewer.post_review_comment(
            project_id=request.project_id,
            mr_id=request.mr_id,
            review_result=request.review_result,
            format_type=request.format_type
        )
        
        return {
            "status": "success",
            "comment_info": comment_info,
            "message": "Review comment posted successfully"
        }
        
    except Exception as e:
        logger.error(f"Failed to post comment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to post comment: {str(e)}"
        )

@app.post("/review/update-mr")
async def update_mr_with_review(
    gitlab_url: str,
    project_id: str,
    mr_id: int,
    access_token: str,
    review_result: Dict[str, Any]
):
    """
    用审查结果更新MR描述
    
    将审查总结添加到MR描述中。
    """
    try:
        reviewer = GitLabReviewer(gitlab_url, access_token)
        
        success = await reviewer.update_mr_with_review(
            project_id=project_id,
            mr_id=mr_id,
            review_result=review_result
        )
        
        if success:
            return {"status": "success", "message": "MR updated successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update MR"
            )
            
    except Exception as e:
        logger.error(f"Failed to update MR: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update MR: {str(e)}"
        )

@app.get("/review/{review_id}/status")
async def get_review_status(review_id: str):
    """
    获取审查状态
    
    用于查询正在进行中的审查状态。
    """
    # 这里需要实现状态查询逻辑
    # 可以使用Redis或数据库存储审查状态
    return {
        "message": "Status tracking not implemented yet",
        "review_id": review_id
    }

@app.post("/batch-review")
async def batch_review(
    requests: List[ReviewRequest],
    background_tasks: BackgroundTasks
):
    """
    批量审查多个MR
    
    适合CI/CD系统中批量处理多个MR。
    """
    if len(requests) > 10:  # 限制批量大小
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch size cannot exceed 10"
        )
    
    try:
        # 启动后台任务处理批量审查
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        async def process_batch():
            results = []
            for req in requests:
                try:
                    reviewer = GitLabReviewer(
                        gitlab_url=req.gitlab_url,
                        access_token=req.access_token,
                        ai_model=req.ai_model
                    )
                    
                    result = await reviewer.review_merge_request(
                        project_id=req.project_id,
                        mr_id=req.mr_id,
                        review_type=req.review_type,
                        options=req.options
                    )
                    results.append({"status": "success", "result": result})
                    
                except Exception as e:
                    results.append({"status": "error", "error": str(e)})
            
            # 这里可以将结果存储到数据库或发送通知
            logger.info(f"Batch {batch_id} completed with {len(results)} results")
        
        background_tasks.add_task(process_batch)
        
        return {
            "batch_id": batch_id,
            "status": "processing",
            "message": f"Batch review started for {len(requests)} MRs"
        }
        
    except Exception as e:
        logger.error(f"Batch review failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch review failed: {str(e)}"
        )

# 错误处理
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

# 启动事件
@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info(f"GitLab Code Reviewer API v{settings.service_version} starting up")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Default AI model: {settings.default_ai_model}")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info("GitLab Code Reviewer API shutting down")

# 开发模式启动
if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )