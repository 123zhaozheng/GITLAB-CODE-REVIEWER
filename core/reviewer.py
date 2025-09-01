"""
核心审查引擎模块
整合GitLab客户端和AI处理器，提供统一的代码审查接口
"""
import asyncio
import logging
from typing import Dict, List, Optional, AsyncGenerator, Any
from datetime import datetime
import uuid

from core.gitlab_client import GitLabClient, FilePatchInfo
from core.simple_ai_processor import SimpleAIProcessor
from config.settings import settings, REVIEW_TYPES

logger = logging.getLogger(__name__)

class ReviewResult:
    """审查结果类"""
    def __init__(self, review_id: str, status: str = "pending"):
        self.review_id = review_id
        self.status = status
        self.findings = []
        self.summary = ""
        self.score = 0.0
        self.review_type = ""
        self.created_at = datetime.now()
        self.completed_at = None
        self.files_analyzed = 0
        self.cost_estimate = 0.0

class GitLabReviewer:
    """GitLab代码审查器 - 主要入口类"""
    
    def __init__(self, gitlab_url: str, access_token: str, 
                 ai_model: Optional[str] = None):
        self.gitlab_url = gitlab_url
        self.access_token = access_token
        self.ai_model = ai_model or settings.default_ai_model
        
        # 初始化客户端
        self.gitlab_client = GitLabClient(gitlab_url, access_token)
        self.ai_processor = SimpleAIProcessor(self.ai_model)
        
        # 审查状态追踪
        self.active_reviews = {}
    
    async def review_file_patches(self, 
                                  diff_files: List[FilePatchInfo],
                                  review_type: str = "full",
                                  mr_info: Optional[Dict] = None) -> Dict[str, Any]:
        """
        审查文件补丁列表 - 这是新的核心审查方法
        
        Args:
            diff_files: 文件补丁信息列表
            review_type: 审查类型
            mr_info: (可选) 关联的MR信息，用于丰富报告
            
        Returns:
            审查结果字典
        """
        review_id = str(uuid.uuid4())
        logger.info(f"Starting generic review {review_id} for {len(diff_files)} files.")
        
        if not diff_files:
            return self._create_empty_review_result(review_id, "No changes to review")
        
        # AI分析
        ai_analysis = await self.ai_processor.analyze_merge_request(
            diff_files, review_type, mr_info or {}
        )
        
        # 构建最终结果
        result = self._build_review_result(
            review_id, review_type, ai_analysis, mr_info or {}, diff_files
        )
        
        logger.info(f"Review {review_id} completed with score {result['score']}")
        return result

    async def review_merge_request(self, project_id: str, mr_id: int,
                                 review_type: str = "full",
                                 options: Optional[Dict] = None) -> Dict[str, Any]:
        """
        审查GitLab Merge Request - 现在是 review_file_patches 的封装
        """
        review_id = str(uuid.uuid4())
        review_result = ReviewResult(review_id, "processing")
        self.active_reviews[review_id] = review_result
        
        try:
            logger.info(f"Starting review {review_id} for MR {project_id}!{mr_id}")
            
            if review_type not in REVIEW_TYPES:
                raise ValueError(f"Invalid review type: {review_type}")
            
            async with self.gitlab_client:
                mr_info = await self.gitlab_client.get_mr_basic_info(project_id, mr_id)
                diff_files = await self.gitlab_client.get_diff_files(project_id, mr_id)
                
                # 调用核心审查方法
                result = await self.review_file_patches(diff_files, review_type, mr_info)
                
                # 更新状态
                review_result.status = "completed"
                review_result.completed_at = datetime.now()
                # ... (其他状态更新可以保持)
                
                return result
                
        except Exception as e:
            logger.error(f"Review {review_id} for MR {mr_id} failed: {e}")
            review_result.status = "failed"
            raise
        finally:
            if review_id in self.active_reviews:
                del self.active_reviews[review_id]

    async def review_branch_comparison(self, project_id: str, 
                                       target_branch: str, source_branch: str,
                                       review_type: str = "full") -> Dict[str, Any]:
        """
        审查两个分支的比较
        """
        logger.info(f"Starting branch comparison review for {project_id}: {target_branch}...{source_branch}")
        async with self.gitlab_client:
            diff_files = await self.gitlab_client.compare_branches(
                project_id, target_branch, source_branch
            )
            
            # 为报告创建一个模拟的 mr_info 对象
            comparison_info = {
                "title": f"Comparison: {source_branch} vs {target_branch}",
                "web_url": f"{self.gitlab_url}/{project_id}/-/compare/{target_branch}...{source_branch}",
                "author": {"name": "Branch Comparison"},
                "source_branch": source_branch,
                "target_branch": target_branch
            }
            
            # 调用核心审查方法
            result = await self.review_file_patches(diff_files, review_type, comparison_info)
            return result
    
    async def stream_review(self, project_id: str, mr_id: int,
                          review_type: str = "full") -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式审查 - 实时返回审查进度
        """
        review_id = str(uuid.uuid4())
        
        try:
            yield {"type": "start", "review_id": review_id, "status": "initializing"}
            
            async with self.gitlab_client:
                # 获取MR信息
                yield {"type": "progress", "message": "获取MR信息...", "progress": 10}
                mr_info = await self.gitlab_client.get_mr_basic_info(project_id, mr_id)
                
                # 获取文件差异
                yield {"type": "progress", "message": "分析文件变更...", "progress": 20}
                diff_files = await self.gitlab_client.get_diff_files(project_id, mr_id)
                
                if not diff_files:
                    yield {"type": "completed", "message": "未发现文件变更", "score": 10.0}
                    return
                
                # 逐文件分析
                for i, file_patch in enumerate(diff_files):
                    progress = 30 + (i / len(diff_files)) * 60
                    yield {
                        "type": "file_progress",
                        "filename": file_patch.filename,
                        "progress": progress,
                        "message": f"分析文件 {i+1}/{len(diff_files)}"
                    }
                    
                    # 可以在这里添加单文件分析逻辑
                    await asyncio.sleep(0.1)  # 模拟处理时间
                
                # 最终AI分析
                yield {"type": "progress", "message": "AI综合分析...", "progress": 90}
                ai_analysis = await self.ai_processor.analyze_merge_request(
                    diff_files, review_type, mr_info
                )
                
                # 返回最终结果
                result = self._build_review_result(
                    review_id, review_type, ai_analysis, mr_info, diff_files
                )
                
                yield {"type": "completed", "result": result, "progress": 100}
                
        except Exception as e:
            yield {"type": "error", "message": str(e), "review_id": review_id}
    
    async def get_review_status(self, review_id: str) -> Optional[Dict[str, Any]]:
        """获取审查状态"""
        if review_id not in self.active_reviews:
            return None
        
        review = self.active_reviews[review_id]
        return {
            "review_id": review_id,
            "status": review.status,
            "created_at": review.created_at.isoformat(),
            "files_analyzed": review.files_analyzed,
            "score": review.score
        }
    
    
    async def update_mr_with_review(self, project_id: str, mr_id: int,
                                  review_result: Dict[str, Any]) -> bool:
        """用审查结果更新MR描述"""
        try:
            # 获取当前描述
            async with self.gitlab_client:
                mr_info = await self.gitlab_client.get_mr_basic_info(project_id, mr_id)
                current_description = mr_info.get("description", "")
                
                # 添加审查总结
                review_summary = self._generate_review_summary(review_result)
                updated_description = f"{current_description}\n\n{review_summary}"
                
                success = await self.gitlab_client.update_mr_description(
                    project_id, mr_id, description=updated_description
                )
                
                return success
                
        except Exception as e:
            logger.error(f"Failed to update MR description: {e}")
            return False
    
    def _build_review_result(self, review_id: str, review_type: str,
                           ai_analysis: Dict[str, Any], mr_info: Dict[str, Any],
                           diff_files: List[FilePatchInfo]) -> Dict[str, Any]:
        """构建审查结果"""
        
        return {
            "review_id": review_id,
            "status": "completed",
            "review_type": review_type,
            "score": ai_analysis.get("score", 7.0),
            "summary": ai_analysis.get("summary", "代码审查完成"),
            "findings": ai_analysis.get("findings", []),
            "suggestions": ai_analysis.get("suggestions", []),
            "issues": ai_analysis.get("issues", []),
            "recommendations": ai_analysis.get("recommendations", []),
            "mr_info": {
                "title": mr_info.get("title"),
                "url": mr_info.get("web_url"),
                "author": mr_info.get("author", {}).get("name"),
                "source_branch": mr_info.get("source_branch"),
                "target_branch": mr_info.get("target_branch")
            },
            "statistics": {
                "files_analyzed": len(diff_files),
                "total_additions": sum(f.num_plus_lines for f in diff_files),
                "total_deletions": sum(f.num_minus_lines for f in diff_files),
                "review_type_info": REVIEW_TYPES.get(review_type, {})
            },
            "metadata": {
                "reviewer_version": settings.service_version,
                "ai_model": self.ai_model,
                "review_timestamp": datetime.now().isoformat(),
                "cost_estimate": ai_analysis.get("cost_estimate", 0.0)
            }
        }
    
    def _create_empty_review_result(self, review_id: str, message: str) -> Dict[str, Any]:
        """创建空的审查结果"""
        return {
            "review_id": review_id,
            "status": "completed",
            "score": 10.0,
            "summary": message,
            "findings": [],
            "suggestions": [],
            "recommendations": ["No changes to review"],
            "statistics": {"files_analyzed": 0},
            "metadata": {"review_timestamp": datetime.now().isoformat()}
        }
    
    
    
    
    def _generate_review_summary(self, review_result: Dict[str, Any]) -> str:
        """生成审查总结"""
        score = review_result.get("score", 0)
        review_type = review_result.get("review_type", "full")
        files_count = review_result.get("statistics", {}).get("files_analyzed", 0)
        
        summary = f"""
## 🤖 AI代码审查总结

- **审查类型**: {REVIEW_TYPES.get(review_type, {}).get('name', review_type)}
- **总体评分**: {score:.1f}/10.0
- **分析文件数**: {files_count}
- **审查完成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{review_result.get('summary', '审查完成')}
"""
        return summary