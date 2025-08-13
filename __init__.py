"""
GitLab Code Reviewer
基于PR Agent核心技术的独立GitLab代码审查系统

这是一个专为GitLab优化的AI代码审查服务，提供：
- 🚀 高性能的异步处理
- 🎯 多种审查模式（全面/安全/性能/快速）
- 🔌 简单的REST API接口
- 💰 智能的成本控制
- 📊 详细的审查报告

主要模块：
- core.reviewer: 核心审查引擎
- core.gitlab_client: GitLab API客户端
- core.ai_processor: AI分析处理器
- api.main: FastAPI服务接口
- config.settings: 配置管理

使用示例：
    from core.reviewer import GitLabReviewer
    
    reviewer = GitLabReviewer(
        gitlab_url="https://gitlab.example.com",
        access_token="glpat-xxxx"
    )
    
    result = await reviewer.review_merge_request(
        project_id="123",
        mr_id=456,
        review_type="full"
    )
"""

__version__ = "1.0.0"
__author__ = "GitLab Code Reviewer Team"
__email__ = "support@example.com"
__description__ = "基于AI的GitLab代码审查系统"

# 导入主要类
from core.reviewer import GitLabReviewer
from core.gitlab_client import GitLabClient
from core.ai_processor import AIProcessor
from config.settings import settings

__all__ = [
    "GitLabReviewer",
    "GitLabClient", 
    "AIProcessor",
    "settings"
]

# 版本检查
import sys
if sys.version_info < (3, 11):
    raise RuntimeError("GitLab Code Reviewer requires Python 3.11 or higher")

# 日志配置
import logging
logging.getLogger(__name__).addHandler(logging.NullHandler())