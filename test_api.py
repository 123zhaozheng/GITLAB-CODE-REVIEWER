"""
内测API - 使用Mock数据进行快速测试
"""
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
import asyncio
import json
from datetime import datetime

# 导入Mock客户端
from tests.mock_gitlab_client import MockGitLabClient
from core.ai_processor import AIProcessor
from core.reviewer import GitLabReviewer
from config.settings import settings

# 创建内测FastAPI应用
test_app = FastAPI(
    title="GitLab Code Reviewer - 内测版",
    description="使用Mock数据的内测环境，无需真实GitLab",
    version="1.0.0-test"
)

class TestReviewRequest(BaseModel):
    """内测审查请求"""
    project_id: str = "123"
    mr_id: int = 456
    review_type: str = "full"
    mock_scenario: str = "default"  # 模拟场景

class MockGitLabReviewer(GitLabReviewer):
    """使用Mock数据的审查器"""
    
    def __init__(self, mock_scenario: str = "default"):
        # 初始化Mock客户端
        self.gitlab_url = "https://mock-gitlab.com"
        self.access_token = "mock-token"
        self.ai_model = settings.default_ai_model
        
        self.gitlab_client = MockGitLabClient(self.gitlab_url, self.access_token)
        self.ai_processor = AIProcessor(self.ai_model)
        self.active_reviews = {}
        self.mock_scenario = mock_scenario

@test_app.get("/")
async def test_root():
    """内测首页"""
    return {
        "message": "GitLab Code Reviewer 内测环境",
        "version": "1.0.0-test",
        "description": "使用Mock数据，无需真实GitLab实例",
        "endpoints": {
            "health": "/health",
            "test_review": "/test/review",
            "mock_scenarios": "/test/scenarios",
            "demo_data": "/test/demo-data"
        }
    }

@test_app.get("/health")
async def test_health():
    """内测健康检查"""
    return {
        "status": "healthy",
        "mode": "test",
        "mock_data": True,
        "timestamp": datetime.now().isoformat()
    }

@test_app.get("/test/scenarios")
async def get_mock_scenarios():
    """获取可用的模拟场景"""
    scenarios = {
        "default": {
            "description": "默认场景 - 包含Python认证功能的MR",
            "files": ["src/auth/login.py", "tests/test_auth.py", "src/middleware.py", "docs/api.md"],
            "issues": "中等质量代码，包含一些安全和性能问题"
        },
        "high_quality": {
            "description": "高质量代码 - 完美的代码示例",
            "files": ["src/utils.py", "tests/test_utils.py"],
            "issues": "高质量代码，几乎没有问题"
        },
        "security_issues": {
            "description": "安全问题场景 - 包含多个安全漏洞",
            "files": ["src/sql_query.py", "src/user_input.py"],
            "issues": "包含SQL注入、XSS等安全漏洞"
        },
        "performance_issues": {
            "description": "性能问题场景 - 包含性能瓶颈",
            "files": ["src/data_processing.py", "src/api_handler.py"],
            "issues": "包含N+1查询、内存泄漏等性能问题"
        },
        "large_mr": {
            "description": "大型MR - 包含多个文件和复杂变更",
            "files": ["src/feature1.py", "src/feature2.py", "tests/", "docs/"],
            "issues": "大型重构，需要仔细审查"
        }
    }
    return {"scenarios": scenarios}

@test_app.post("/test/review")
async def test_review(request: TestReviewRequest):
    """内测审查接口 - 使用Mock数据"""
    try:
        # 创建Mock审查器
        reviewer = MockGitLabReviewer(request.mock_scenario)
        
        # 执行审查（使用Mock数据）
        result = await reviewer.review_merge_request(
            project_id=request.project_id,
            mr_id=request.mr_id,
            review_type=request.review_type
        )
        
        # 添加内测标识
        result["test_mode"] = True
        result["mock_scenario"] = request.mock_scenario
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"内测审查失败: {str(e)}")

@test_app.get("/test/demo-data")
async def get_demo_data():
    """获取演示数据"""
    return {
        "sample_mr": {
            "project_id": "123",
            "mr_id": 456,
            "title": "feat: 添加用户认证功能",
            "description": "添加JWT认证和用户登录功能",
            "files_changed": 4,
            "additions": 156,
            "deletions": 23
        },
        "sample_review_types": [
            "full", "security", "performance", "quick"
        ],
        "sample_api_call": {
            "method": "POST",
            "url": "/test/review",
            "body": {
                "project_id": "123",
                "mr_id": 456,
                "review_type": "full",
                "mock_scenario": "default"
            }
        }
    }

@test_app.get("/test/ai-models")
async def test_ai_models():
    """测试AI模型连接"""
    try:
        # 简单测试AI连接
        ai_processor = AIProcessor()
        
        # 模拟一个小的测试请求
        test_prompt = "请简单评价这段代码: print('hello world')"
        
        # 这里可以选择是否真实调用AI
        mock_response = {
            "status": "available",
            "model": ai_processor.model,
            "test_prompt": test_prompt,
            "mock_response": "这是一个简单的Hello World程序，代码质量良好。",
            "note": "这是模拟响应，实际使用时会调用真实AI模型"
        }
        
        return mock_response
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "suggestion": "请检查AI API配置"
        }

# 批量测试接口
@test_app.post("/test/batch-review")
async def test_batch_review():
    """批量测试多个场景"""
    scenarios = ["default", "security_issues", "performance_issues", "high_quality"]
    results = []
    
    for scenario in scenarios:
        try:
            reviewer = MockGitLabReviewer(scenario)
            result = await reviewer.review_merge_request(
                project_id="123",
                mr_id=456 + len(results),  # 不同的MR ID
                review_type="full"
            )
            
            results.append({
                "scenario": scenario,
                "score": result["score"],
                "findings_count": len(result.get("findings", [])),
                "status": "success"
            })
            
        except Exception as e:
            results.append({
                "scenario": scenario,
                "error": str(e),
                "status": "failed"
            })
    
    return {
        "batch_test_results": results,
        "summary": {
            "total": len(scenarios),
            "success": len([r for r in results if r.get("status") == "success"]),
            "failed": len([r for r in results if r.get("status") == "failed"])
        }
    }

# 性能测试接口
@test_app.post("/test/performance")
async def test_performance():
    """性能测试"""
    import time
    
    start_time = time.time()
    
    # 并发测试
    tasks = []
    for i in range(5):  # 5个并发请求
        reviewer = MockGitLabReviewer("default")
        task = reviewer.review_merge_request(
            project_id="123",
            mr_id=456 + i,
            review_type="quick"  # 使用快速模式
        )
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    end_time = time.time()
    
    success_count = len([r for r in results if not isinstance(r, Exception)])
    
    return {
        "performance_test": {
            "concurrent_requests": 5,
            "total_time": round(end_time - start_time, 2),
            "average_time_per_request": round((end_time - start_time) / 5, 2),
            "success_rate": f"{success_count}/5",
            "errors": [str(r) for r in results if isinstance(r, Exception)]
        }
    }

if __name__ == "__main__":
    import uvicorn
    print("🚀 启动GitLab Code Reviewer内测服务...")
    print("📖 API文档: http://localhost:8001/docs")
    print("🧪 内测页面: http://localhost:8001")
    
    uvicorn.run(
        "test_api:test_app",
        host="0.0.0.0", 
        port=8001,
        reload=True
    )