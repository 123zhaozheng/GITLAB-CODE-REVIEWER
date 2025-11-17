"""
任务管理器 - 使用 Redis 存储异步审查任务的状态
"""
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
from core.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    status: str
    progress: int
    message: str
    created_at: str
    updated_at: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """从字典创建任务对象"""
        return cls(**data)


class TaskManager:
    """
    任务管理器 - 使用 Redis 管理异步审查任务
    使用共享的 Redis 连接池
    """

    # Redis 键前缀
    TASK_PREFIX = "gitlab_reviewer:task:"
    TASK_INDEX_KEY = "gitlab_reviewer:tasks"

    def __init__(self, task_ttl: int = 86400):
        """
        初始化任务管理器

        Args:
            task_ttl: 任务过期时间（秒），默认 24 小时
        """
        self.task_ttl = task_ttl
        logger.info("TaskManager initialized (using shared Redis connection)")

    async def _get_redis(self):
        """获取共享的 Redis 客户端"""
        return await get_redis_client()

    async def close(self):
        """
        关闭 Redis 连接（保留兼容性，实际由 RedisConnectionManager 管理）

        注意：不再真正关闭连接，因为连接是共享的
        """
        logger.debug("TaskManager.close() called (connection is shared, not closing)")

    def _get_task_key(self, task_id: str) -> str:
        """获取任务的 Redis 键"""
        return f"{self.TASK_PREFIX}{task_id}"

    async def create_task(self, task_id: str) -> Task:
        """
        创建新任务

        Args:
            task_id: 任务ID

        Returns:
            Task: 创建的任务对象
        """
        redis_client = await self._get_redis()
        now = datetime.now().isoformat()

        task = Task(
            task_id=task_id,
            status=TaskStatus.PENDING.value,
            progress=0,
            message="任务已创建",
            created_at=now,
            updated_at=now
        )

        # 存储到 Redis
        task_key = self._get_task_key(task_id)
        task_data = json.dumps(task.to_dict())

        await redis_client.set(task_key, task_data, ex=self.task_ttl)

        # 添加到任务索引
        await redis_client.sadd(self.TASK_INDEX_KEY, task_id)

        logger.info(f"Task {task_id} created in Redis")
        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        """
        获取任务信息

        Args:
            task_id: 任务ID

        Returns:
            Optional[Task]: 任务对象，不存在则返回 None
        """
        redis_client = await self._get_redis()
        task_key = self._get_task_key(task_id)

        task_data = await redis_client.get(task_key)

        if not task_data:
            logger.warning(f"Task {task_id} not found in Redis")
            return None

        try:
            data = json.loads(task_data)
            return Task.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to parse task data for {task_id}: {e}")
            return None

    async def update_progress(self, task_id: str, progress: int, message: str):
        """
        更新任务进度

        Args:
            task_id: 任务ID
            progress: 进度百分比 (0-100)
            message: 进度消息
        """
        task = await self.get_task(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found when updating progress")
            return

        task.status = TaskStatus.RUNNING.value
        task.progress = min(100, max(0, progress))
        task.message = message
        task.updated_at = datetime.now().isoformat()

        # 保存到 Redis
        redis_client = await self._get_redis()
        task_key = self._get_task_key(task_id)
        task_data = json.dumps(task.to_dict())

        await redis_client.set(task_key, task_data, ex=self.task_ttl)

        logger.info(f"Task {task_id} progress: {progress}% - {message}")

    async def complete_task(self, task_id: str, result: Dict[str, Any]):
        """
        标记任务完成

        Args:
            task_id: 任务ID
            result: 任务结果
        """
        task = await self.get_task(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found when completing")
            return

        task.status = TaskStatus.COMPLETED.value
        task.progress = 100
        task.message = "任务完成"
        task.result = result
        task.updated_at = datetime.now().isoformat()

        # 保存到 Redis
        redis_client = await self._get_redis()
        task_key = self._get_task_key(task_id)
        task_data = json.dumps(task.to_dict())

        # 完成的任务可以设置更长的过期时间，方便查询
        await redis_client.set(task_key, task_data, ex=self.task_ttl)

        logger.info(f"Task {task_id} completed")

    async def fail_task(self, task_id: str, error: str):
        """
        标记任务失败

        Args:
            task_id: 任务ID
            error: 错误信息
        """
        task = await self.get_task(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found when failing")
            return

        task.status = TaskStatus.FAILED.value
        task.message = "任务失败"
        task.error = error
        task.updated_at = datetime.now().isoformat()

        # 保存到 Redis
        redis_client = await self._get_redis()
        task_key = self._get_task_key(task_id)
        task_data = json.dumps(task.to_dict())

        await redis_client.set(task_key, task_data, ex=self.task_ttl)

        logger.error(f"Task {task_id} failed: {error}")

    async def delete_task(self, task_id: str) -> bool:
        """
        删除任务

        Args:
            task_id: 任务ID

        Returns:
            bool: 是否删除成功
        """
        redis_client = await self._get_redis()
        task_key = self._get_task_key(task_id)

        result = await redis_client.delete(task_key)

        # 从索引中移除
        await redis_client.srem(self.TASK_INDEX_KEY, task_id)

        if result > 0:
            logger.info(f"Task {task_id} deleted from Redis")
            return True
        return False

    async def get_all_tasks(self) -> Dict[str, Task]:
        """
        获取所有任务

        Returns:
            Dict[str, Task]: 所有任务字典
        """
        redis_client = await self._get_redis()

        # 从索引获取所有任务 ID
        task_ids = await redis_client.smembers(self.TASK_INDEX_KEY)

        tasks = {}
        for task_id in task_ids:
            task = await self.get_task(task_id)
            if task:
                tasks[task_id] = task
            else:
                # 如果任务不存在，从索引中移除
                await redis_client.srem(self.TASK_INDEX_KEY, task_id)

        return tasks

    async def cleanup_old_tasks(self, max_age_hours: int = 24):
        """
        清理旧任务

        注意：由于使用了 Redis TTL，过期的任务会自动删除
        这个方法主要用于清理索引中的过期任务引用

        Args:
            max_age_hours: 最大保留时间（小时）
        """
        redis_client = await self._get_redis()
        now = datetime.now()

        # 获取所有任务 ID
        task_ids = await redis_client.smembers(self.TASK_INDEX_KEY)

        cleaned_count = 0
        for task_id in task_ids:
            task = await self.get_task(task_id)

            # 如果任务不存在（已过期），从索引中移除
            if not task:
                await redis_client.srem(self.TASK_INDEX_KEY, task_id)
                cleaned_count += 1
                continue

            # 检查任务年龄
            created = datetime.fromisoformat(task.created_at)
            age = (now - created).total_seconds() / 3600

            if age > max_age_hours:
                await self.delete_task(task_id)
                cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} old tasks")

    async def get_task_count(self) -> int:
        """
        获取任务总数

        Returns:
            int: 任务数量
        """
        redis_client = await self._get_redis()
        return await redis_client.scard(self.TASK_INDEX_KEY)

    async def get_tasks_by_status(self, status: TaskStatus) -> Dict[str, Task]:
        """
        根据状态获取任务

        Args:
            status: 任务状态

        Returns:
            Dict[str, Task]: 符合条件的任务字典
        """
        all_tasks = await self.get_all_tasks()
        return {
            task_id: task
            for task_id, task in all_tasks.items()
            if task.status == status.value
        }

    async def health_check(self) -> bool:
        """
        健康检查 - 测试 Redis 连接

        Returns:
            bool: Redis 是否可用
        """
        try:
            redis_client = await self._get_redis()
            if not redis_client:
                return False
            await redis_client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False


# 全局任务管理器实例（需要在应用启动时初始化）
task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """
    获取全局任务管理器实例

    Returns:
        TaskManager: 任务管理器实例

    Raises:
        RuntimeError: 如果任务管理器未初始化
    """
    if task_manager is None:
        raise RuntimeError("TaskManager not initialized. Call init_task_manager() first.")
    return task_manager


def init_task_manager(task_ttl: int = 86400):
    """
    初始化全局任务管理器

    Args:
        task_ttl: 任务过期时间（秒）

    注意：不再需要 redis_url 参数，使用共享的 Redis 连接
    """
    global task_manager
    task_manager = TaskManager(task_ttl=task_ttl)
    logger.info(f"TaskManager initialized (using shared Redis connection)")


async def cleanup_task_manager():
    """关闭任务管理器"""
    global task_manager
    if task_manager:
        await task_manager.close()
        logger.info("TaskManager closed")
