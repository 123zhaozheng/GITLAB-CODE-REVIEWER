"""
GitLab客户端模块
基于PR Agent的GitLab Provider优化而来，专注于异步性能
"""
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple, Any
import gitlab
from urllib.parse import urlparse
import logging
import fnmatch


from config.settings import settings

logger = logging.getLogger(__name__)

class FilePatchInfo:
    """文件补丁信息 - 简化版本"""
    def __init__(self, filename: str, old_content: str, new_content: str, 
                 patch: str, edit_type: str, old_filename: Optional[str] = None):
        self.filename = filename
        self.old_content = old_content
        self.new_content = new_content
        self.patch = patch
        self.edit_type = edit_type
        self.old_filename = old_filename
        
        # 计算统计信息
        patch_lines = patch.splitlines() if patch else []
        self.num_plus_lines = len([line for line in patch_lines if line.startswith('+')])
        self.num_minus_lines = len([line for line in patch_lines if line.startswith('-')])

class GitLabClient:
    """优化的GitLab API客户端"""
    
    def __init__(self, gitlab_url: str, access_token: str):
        self.gitlab_url = gitlab_url.rstrip('/')
        self.access_token = access_token
        self.gitlab = gitlab.Gitlab(gitlab_url, private_token=access_token)
        self._cache = {}
        self._session = None
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self._session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self._session:
            await self._session.close()
    
    async def get_mr_basic_info(self, project_id: str, mr_id: int) -> Dict[str, Any]:
        """获取MR基本信息 - 带缓存"""
        cache_key = f"mr_basic_{project_id}_{mr_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]
            
        try:
            project = self.gitlab.projects.get(project_id)
            mr = project.mergerequests.get(mr_id)
            
            mr_info = {
                "id": mr.id,
                "iid": mr.iid,
                "title": mr.title,
                "description": mr.description or "",
                "source_branch": mr.source_branch,
                "target_branch": mr.target_branch,
                "author": {
                    "id": mr.author.get("id"),
                    "name": mr.author.get("name"),
                    "username": mr.author.get("username")
                },
                "web_url": mr.web_url,
                "created_at": mr.created_at,
                "updated_at": mr.updated_at,
                "state": mr.state,
                "diff_refs": mr.diff_refs
            }
            
            self._cache[cache_key] = mr_info
            return mr_info
            
        except Exception as e:
            logger.error(f"Failed to get MR basic info: {e}")
            raise
    
    async def get_mr_changes(self, project_id: str, mr_id: int) -> Dict[str, Any]:
        """获取MR变更信息"""
        cache_key = f"mr_changes_{project_id}_{mr_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]
            
        try:
            project = self.gitlab.projects.get(project_id)
            mr = project.mergerequests.get(mr_id)
            changes = mr.changes()
            
            self._cache[cache_key] = changes
            return changes
            
        except Exception as e:
            logger.error(f"Failed to get MR changes: {e}")
            raise
    
    async def get_file_content(self, project_id: str, file_path: str, ref: str) -> str:
        """异步获取文件内容"""
        try:
            project = self.gitlab.projects.get(project_id)
            file_obj = project.files.get(file_path, ref)
            content = file_obj.decode()
            return content.decode('utf-8') if isinstance(content, bytes) else content
        except gitlab.GitlabGetError:
            # 文件不存在（可能是新建文件）
            return ""
        except Exception as e:
            logger.warning(f"Error retrieving file {file_path} from ref {ref}: {e}")
            return ""
    
    async def get_diff_files(self, project_id: str, mr_id: int) -> List[FilePatchInfo]:
        """获取MR的差异文件列表 - 核心功能"""
        try:
            # 获取MR基本信息和变更
            mr_info = await self.get_mr_basic_info(project_id, mr_id)
            changes_data = await self.get_mr_changes(project_id, mr_id)
            changes = changes_data.get('changes', [])
            
            if not changes:
                logger.warning(f"No changes found for MR {mr_id}")
                return []
            
            # 应用智能过滤
            filtered_changes = self._filter_relevant_files(changes)
            
            # 并行获取文件内容
            tasks = []
            for change in filtered_changes:
                task = self._create_file_patch_info(
                    project_id, change, mr_info['diff_refs']
                )
                tasks.append(task)
            
            # 限制并发数量
            semaphore = asyncio.Semaphore(10)
            async def limited_task(task):
                async with semaphore:
                    return await task
            
            results = await asyncio.gather(
                *[limited_task(task) for task in tasks],
                return_exceptions=True
            )
            
            # 过滤掉异常结果
            diff_files = []
            for result in results:
                if isinstance(result, FilePatchInfo):
                    diff_files.append(result)
                elif isinstance(result, Exception):
                    logger.error(f"Error processing file: {result}")
            
            logger.info(f"Successfully processed {len(diff_files)} files for MR {mr_id}")
            return diff_files
            
        except Exception as e:
            logger.error(f"Failed to get diff files for MR {mr_id}: {e}")
            raise
    
    async def compare_branches(self, project_id: str, target_branch: str, source_branch: str) -> List[FilePatchInfo]:
        """比较两个分支并获取差异文件列表"""
        logger.info(f"Comparing branches: '{source_branch}' vs '{target_branch}'")
        try:
            project = self.gitlab.projects.get(project_id)
            # straight=True 表示我们想要两个分支端点之间的直接比较（相当于 git diff target...source）
            comparison = project.repository_compare(from_=target_branch, to=source_branch, straight=True)
            diffs = comparison.get('diffs', [])

            if not diffs:
                logger.warning(f"No differences found between '{source_branch}' and '{target_branch}'")
                return []

            filtered_diffs = self._filter_relevant_files(diffs)

            # 我们可以复用 _create_file_patch_info，只需提供正确的 "refs"
            # 在这种情况下，"base" 是目标分支，"head" 是源分支
            diff_refs = {'base_sha': target_branch, 'head_sha': source_branch}

            tasks = [self._create_file_patch_info(project_id, diff, diff_refs) for diff in filtered_diffs]

            # 使用与 get_diff_files 中相同的并发限制逻辑
            semaphore = asyncio.Semaphore(10)
            async def limited_task(task):
                async with semaphore:
                    return await task

            results = await asyncio.gather(
                *[limited_task(task) for task in tasks],
                return_exceptions=True
            )

            file_patches = []
            for result in results:
                if isinstance(result, FilePatchInfo):
                    file_patches.append(result)
                elif isinstance(result, Exception):
                    logger.error(f"Error processing file during branch compare: {result}")

            logger.info(f"Successfully processed {len(file_patches)} files from branch comparison.")
            return file_patches

        except Exception as e:
            logger.error(f"Failed to compare branches '{source_branch}' and '{target_branch}': {e}")
            raise

    async def _create_file_patch_info(self, project_id: str, change: Dict, diff_refs: Dict) -> FilePatchInfo:
        """创建单个文件的补丁信息"""
        try:
            old_path = change.get('old_path', '')
            new_path = change.get('new_path', '')
            patch = change.get('diff', '')
            
            # 并行获取文件内容
            old_content_task = self.get_file_content(project_id, old_path, diff_refs['base_sha'])
            new_content_task = self.get_file_content(project_id, new_path, diff_refs['head_sha'])
            
            old_content, new_content = await asyncio.gather(
                old_content_task, new_content_task, return_exceptions=True
            )
            
            # 处理异常情况
            if isinstance(old_content, Exception):
                old_content = ""
            if isinstance(new_content, Exception):
                new_content = ""
            
            # 确定编辑类型
            edit_type = self._determine_edit_type(change)
            
            return FilePatchInfo(
                filename=new_path,
                old_content=old_content,
                new_content=new_content,
                patch=patch,
                edit_type=edit_type,
                old_filename=old_path if old_path != new_path else None
            )
            
        except Exception as e:
            logger.error(f"Failed to create patch info for {change.get('new_path', 'unknown')}: {e}")
            raise
    
    def _determine_edit_type(self, change: Dict) -> str:
        """确定文件编辑类型"""
        if change.get('new_file', False):
            return "ADDED"
        elif change.get('deleted_file', False):
            return "DELETED"
        elif change.get('renamed_file', False):
            return "RENAMED"
        else:
            return "MODIFIED"
    
    def _filter_relevant_files(self, changes: List[Dict]) -> List[Dict]:
        """
        智能过滤相关文件：
        1) 基于路径/模式忽略无需审查的目录或文件（如 node_modules、venv、target 等）
        2) 基于扩展名优先级（FILE_PRIORITY）排序与过滤（优先级为0视为忽略）
        3) 限制最大文件数量

        当 settings.smart_filtering = False 时，仅返回前 N 个（按出现顺序），不做排序
        """
        # 路径/模式过滤（始终应用，防止明显无意义的产物进入审查）
        ignored_patterns = settings.ignore_path_patterns or []

        def is_ignored_by_path(change: Dict) -> bool:
            file_path = change.get('new_path') or change.get('old_path') or ''
            # GitLab 路径为 posix 风格，确保统一
            norm = file_path.replace('\\', '/').lstrip('/')
            for pattern in ignored_patterns:
                if fnmatch.fnmatch(norm, pattern):
                    return True
            return False

        path_filtered = [c for c in changes if not is_ignored_by_path(c)]

        if not settings.smart_filtering:
            # 关闭智能筛选时，仅做数量限制
            return path_filtered[:settings.max_files_per_review]

        # 基于扩展名的优先级排序
        from config.settings import FILE_PRIORITY

        def get_file_priority(change: Dict) -> int:
            file_path = change.get('new_path', '')
            ext = '.' + file_path.split('.')[-1] if '.' in file_path else ''
            return FILE_PRIORITY.get(ext, 5)  # 默认中等优先级

        # 过滤掉优先级为0的文件（忽略文件类型）
        relevant_changes = [c for c in path_filtered if get_file_priority(c) > 0]

        # 按优先级排序（高 → 低）
        relevant_changes.sort(key=get_file_priority, reverse=True)

        # 限制文件数量
        return relevant_changes[:settings.max_files_per_review]
    
    
    async def update_mr_description(self, project_id: str, mr_id: int, 
                                   title: Optional[str] = None, 
                                   description: Optional[str] = None) -> bool:
        """更新MR标题和描述"""
        try:
            project = self.gitlab.projects.get(project_id)
            mr = project.mergerequests.get(mr_id)
            
            if title:
                mr.title = title
            if description:
                mr.description = description
                
            mr.save()
            return True
        except Exception as e:
            logger.error(f"Failed to update MR: {e}")
            return False
    
    def get_mr_url(self, project_id: str, mr_id: int) -> str:
        """获取MR的Web URL"""
        return f"{self.gitlab_url}/{project_id}/-/merge_requests/{mr_id}"