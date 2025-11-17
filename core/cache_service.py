"""
Redis缓存服务模块
用于缓存审查结果和历史问题，提升重复审查的性能
"""
import json
import hashlib
import logging
from typing import Dict, List, Optional, Any
from datetime import timedelta
from core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

class CacheService:
    """Redis缓存服务 - 使用共享的 Redis 连接池"""

    def __init__(self):
        """
        初始化缓存服务

        注意：现在使用全局共享的 Redis 连接管理器
        """
        # 缓存过期时间（7天）
        self.review_cache_ttl = timedelta(days=7)
        self.history_cache_ttl = timedelta(days=30)  # 历史问题保存更长时间

        logger.info("CacheService initialized (using shared Redis connection)")

    async def _get_redis(self):
        """获取 Redis 客户端"""
        return await get_redis_client()

    async def connect(self):
        """
        连接到Redis（保留兼容性，实际由 RedisConnectionManager 管理）
        """
        client = await self._get_redis()
        if client:
            logger.debug("Using shared Redis connection")
        else:
            logger.warning("Redis connection not available")

    async def close(self):
        """
        关闭Redis连接（保留兼容性，实际由 RedisConnectionManager 管理）

        注意：不再真正关闭连接，因为连接是共享的
        """
        logger.debug("CacheService.close() called (connection is shared, not closing)")

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()

    def _generate_review_cache_key(self, project_id: str, source_commit: str,
                                   target_branch: str, review_type: str = "full",
                                   task_id: Optional[str] = None) -> str:
        """
        生成审查结果缓存key

        用途：缓存完全相同代码的审查结果，避免重复审查
        注意：使用 source_commit (hash) 而不是 source_branch，因为分支内容会变化

        Args:
            project_id: 项目ID
            source_commit: 源分支的commit hash（确保唯一性）
            target_branch: 目标分支名
            review_type: 审查类型
            task_id: 任务/工作项/开发项目号（可选），用于区分同一分支的不同开发任务

        Returns:
            缓存key字符串

        示例：
            review:cache:abc123  (基于 project_id:commit_hash:target_branch:type:task_id)
        """
        # 组合所有参数，使用commit hash确保准确匹配相同的代码
        if task_id:
            key_components = f"{project_id}:{source_commit}:{target_branch}:{review_type}:{task_id}"
        else:
            key_components = f"{project_id}:{source_commit}:{target_branch}:{review_type}"
        # 生成hash
        key_hash = hashlib.sha256(key_components.encode()).hexdigest()[:16]
        # 返回带前缀的key
        return f"review:cache:{key_hash}"

    def _generate_history_key(self, project_id: str, target_branch: str,
                             task_id: Optional[str] = None) -> str:
        """
        生成历史问题存储key

        用途：存储同一开发任务在目标分支上的历史问题，用于问题追踪和复检
        注意：不包含source_branch！因为同一任务会多次提交，源分支commit会变化

        Args:
            project_id: 项目ID
            target_branch: 目标分支名
            task_id: 任务/工作项/开发项目号（可选）

        Returns:
            历史问题key字符串

        设计说明：
            - 同一个 task_id + target_branch 可以找到历史问题
            - 开发人员多次提交代码，都能找到之前的问题进行复检
            - 不同源分支的commit都对比同一份历史问题

        示例：
            如果 task_id="JIRA-123", target_branch="develop"
            则所有针对这个任务的提交（无论源分支commit如何变化）都共享同一份历史问题
        """
        if task_id:
            # 有task_id：按任务+目标分支存储
            key_components = f"{project_id}:{target_branch}:{task_id}"
        else:
            # 无task_id：只按项目+目标分支存储（全局历史）
            key_components = f"{project_id}:{target_branch}"
        key_hash = hashlib.sha256(key_components.encode()).hexdigest()[:16]
        return f"review:history:{key_hash}"

    async def get_cached_review(self, project_id: str, source_commit: str,
                               target_branch: str, review_type: str = "full",
                               task_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        获取缓存的审查结果

        Args:
            project_id: 项目ID
            source_commit: 源分支的commit hash
            target_branch: 目标分支名
            review_type: 审查类型
            task_id: 任务/工作项/开发项目号（可选）

        Returns:
            缓存的审查结果，如果不存在返回None
        """
        redis_client = await self._get_redis()
        if not redis_client:
            return None

        try:
            cache_key = self._generate_review_cache_key(
                project_id, source_commit, target_branch, review_type, task_id
            )

            cached_data = await redis_client.get(cache_key)

            if cached_data:
                task_info = f" [task:{task_id}]" if task_id else ""
                logger.info(f"Cache HIT for review: {project_id} commit:{source_commit[:8]}→{target_branch}{task_info}")
                result = json.loads(cached_data)
                # 添加缓存标记
                result["from_cache"] = True
                return result
            else:
                task_info = f" [task:{task_id}]" if task_id else ""
                logger.info(f"Cache MISS for review: {project_id} commit:{source_commit[:8]}→{target_branch}{task_info}")
                return None

        except Exception as e:
            logger.error(f"Error getting cached review: {e}")
            return None

    async def cache_review_result(self, project_id: str, source_commit: str,
                                 target_branch: str, review_type: str,
                                 review_result: Dict[str, Any],
                                 task_id: Optional[str] = None) -> bool:
        """
        缓存审查结果

        Args:
            project_id: 项目ID
            source_commit: 源分支的commit hash
            target_branch: 目标分支名
            review_type: 审查类型
            review_result: 审查结果
            task_id: 任务/工作项/开发项目号（可选）

        Returns:
            是否成功缓存
        """
        redis_client = await self._get_redis()
        if not redis_client:
            return False

        try:
            cache_key = self._generate_review_cache_key(
                project_id, source_commit, target_branch, review_type, task_id
            )

            # 序列化结果
            cached_data = json.dumps(review_result, ensure_ascii=False)

            # 存储到Redis，设置过期时间
            await redis_client.setex(
                cache_key,
                int(self.review_cache_ttl.total_seconds()),
                cached_data
            )

            task_info = f" [task:{task_id}]" if task_id else ""
            logger.info(f"Cached review result: commit:{source_commit[:8]}→{target_branch}{task_info} (TTL: {self.review_cache_ttl.days} days)")
            return True

        except Exception as e:
            logger.error(f"Error caching review result: {e}")
            return False

    async def get_historical_issues(self, project_id: str, target_branch: str,
                                   task_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取历史审查问题（按文件组织）

        注意：不需要source_branch参数，因为历史问题是按task_id+target_branch存储的

        Args:
            project_id: 项目ID
            target_branch: 目标分支名
            task_id: 任务/工作项/开发项目号（可选）

        Returns:
            历史问题字典，key为文件名，value为该文件的问题列表

        设计说明：
            同一个任务的多次提交（源分支commit不同）都会获取相同的历史问题
        """
        redis_client = await self._get_redis()
        if not redis_client:
            return {}

        try:
            history_key = self._generate_history_key(
                project_id, target_branch, task_id
            )

            cached_data = await redis_client.get(history_key)

            if cached_data:
                task_info = f" [task:{task_id}]" if task_id else ""
                logger.info(f"Found historical issues for: {project_id}→{target_branch}{task_info}")
                return json.loads(cached_data)
            else:
                task_info = f" [task:{task_id}]" if task_id else ""
                logger.info(f"No historical issues found for: {project_id}→{target_branch}{task_info}")
                return {}

        except Exception as e:
            logger.error(f"Error getting historical issues: {e}")
            return {}

    async def save_historical_issues(self, project_id: str, target_branch: str,
                                    findings: List[Dict[str, Any]],
                                    task_id: Optional[str] = None) -> bool:
        """
        保存历史审查问题（按文件组织）

        注意：不需要source_branch参数，历史问题按task_id+target_branch存储

        Args:
            project_id: 项目ID
            target_branch: 目标分支名
            findings: 审查发现的问题列表
            task_id: 任务/工作项/开发项目号（可选）

        Returns:
            是否成功保存

        设计说明：
            无论源分支如何变化，同一个任务的历史问题都累积在同一个key下
        """
        redis_client = await self._get_redis()
        if not redis_client:
            return False

        try:
            history_key = self._generate_history_key(
                project_id, target_branch, task_id
            )

            # 按文件组织问题
            issues_by_file = {}
            for finding in findings:
                filename = finding.get("filename", "unknown")
                if filename not in issues_by_file:
                    issues_by_file[filename] = []

                # 只保存必要的信息
                issue_summary = {
                    "type": finding.get("type", "unknown"),
                    "line_number": finding.get("line_number", 0),
                    "severity": finding.get("severity", "low"),
                    "description": finding.get("description", ""),
                    "suggestion": finding.get("suggestion", "")
                }
                issues_by_file[filename].append(issue_summary)

            # 序列化并存储
            cached_data = json.dumps(issues_by_file, ensure_ascii=False)

            await redis_client.setex(
                history_key,
                int(self.history_cache_ttl.total_seconds()),
                cached_data
            )

            task_info = f" [task:{task_id}]" if task_id else ""
            logger.info(f"Saved historical issues for {len(issues_by_file)} files: {project_id}→{target_branch}{task_info}")
            return True

        except Exception as e:
            logger.error(f"Error saving historical issues: {e}")
            return False

    # ---------------------------------------------------------------------
    # 重复审查（按分支+任务）去重：当 project_id + source_branch + target_branch + task_id 相同，
    # 直接返回上一次的审查结果（包含相同的 review_id）
    # ---------------------------------------------------------------------
    def _generate_duplicate_key(self, project_id: str, source_branch: str,
                                target_branch: str, task_id: Optional[str] = None) -> str:
        """
        生成重复审查检测用的key（不使用commit，按分支+任务维度）

        说明：
            - 与 get_cached_review（commit 级别缓存）互补
            - 仅用于用户期望的“相同参数直接复用上一次结果”的场景
        """
        task_part = task_id or ""
        key_components = f"{project_id}:{source_branch}:{target_branch}:{task_part}"
        key_hash = hashlib.sha256(key_components.encode()).hexdigest()[:16]
        return f"review:dedup:{key_hash}"

    async def get_duplicate_review(self, project_id: str, source_branch: str,
                                   target_branch: str, task_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        获取按分支+任务维度的最近一次审查结果

        命中时直接返回完整结果，并附加 from_cache=True
        """
        redis_client = await self._get_redis()
        if not redis_client:
            return None

        try:
            dup_key = self._generate_duplicate_key(project_id, source_branch, target_branch, task_id)
            cached_data = await redis_client.get(dup_key)
            task_info = f" [task:{task_id}]" if task_id else ""

            if cached_data:
                logger.info(f"Duplicate HIT for review: {project_id} {source_branch}→{target_branch}{task_info}")
                result = json.loads(cached_data)
                result["from_cache"] = True
                return result
            else:
                logger.info(f"Duplicate MISS for review: {project_id} {source_branch}→{target_branch}{task_info}")
                return None
        except Exception as e:
            logger.error(f"Error getting duplicate review: {e}")
            return None

    async def cache_duplicate_review(self, project_id: str, source_branch: str,
                                     target_branch: str, review_result: Dict[str, Any],
                                     task_id: Optional[str] = None) -> bool:
        """
        缓存最近一次按分支+任务维度的审查结果（用于重复审查直接返回）
        """
        redis_client = await self._get_redis()
        if not redis_client:
            return False

        try:
            dup_key = self._generate_duplicate_key(project_id, source_branch, target_branch, task_id)
            cached_data = json.dumps(review_result, ensure_ascii=False)
            await redis_client.setex(
                dup_key,
                int(self.review_cache_ttl.total_seconds()),
                cached_data
            )
            task_info = f" [task:{task_id}]" if task_id else ""
            logger.info(f"Cached duplicate mapping for: {project_id} {source_branch}→{target_branch}{task_info}")
            return True
        except Exception as e:
            logger.error(f"Error caching duplicate review: {e}")
            return False

    async def clear_review_cache(self, project_id: str, source_commit: str,
                                target_branch: str, review_type: Optional[str] = None,
                                task_id: Optional[str] = None) -> bool:
        """
        清除指定的审查缓存

        Args:
            project_id: 项目ID
            source_commit: 源分支的commit hash
            target_branch: 目标分支名
            review_type: 审查类型，如果为None则清除所有类型
            task_id: 任务ID（可选）

        Returns:
            是否成功清除
        """
        redis_client = await self._get_redis()
        if not redis_client:
            return False

        try:
            if review_type:
                # 清除指定类型的缓存
                cache_key = self._generate_review_cache_key(
                    project_id, source_commit, target_branch, review_type, task_id
                )
                await redis_client.delete(cache_key)
                logger.info(f"Cleared cache: commit:{source_commit[:8]}→{target_branch} type:{review_type}")
            else:
                # 清除所有类型的缓存
                from config.settings import REVIEW_TYPES
                for rt in REVIEW_TYPES.keys():
                    cache_key = self._generate_review_cache_key(
                        project_id, source_commit, target_branch, rt, task_id
                    )
                    await redis_client.delete(cache_key)
                logger.info(f"Cleared all review type caches for commit:{source_commit[:8]}→{target_branch}")

            return True

        except Exception as e:
            logger.error(f"Error clearing review cache: {e}")
            return False

    async def health_check(self) -> bool:
        """
        健康检查

        Returns:
            Redis是否可用
        """
        redis_client = await self._get_redis()
        if not redis_client:
            return False

        try:
            await redis_client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
