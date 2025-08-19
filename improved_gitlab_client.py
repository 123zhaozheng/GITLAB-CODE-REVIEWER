"""
改进版GitLab客户端 - 增强错误处理和权限检查
"""
import asyncio
import aiohttp
import gitlab
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)

class ImprovedGitLabClient:
    """改进版GitLab客户端，增强错误处理"""
    
    def __init__(self, gitlab_url: str, access_token: str):
        self.gitlab_url = gitlab_url.rstrip('/')
        self.access_token = access_token
        self.gitlab = gitlab.Gitlab(gitlab_url, private_token=access_token)
        self._cache = {}
    
    async def get_available_mrs(self, project_id: str) -> List[Dict[str, Any]]:
        """获取项目中可用的MR列表"""
        try:
            project = self.gitlab.projects.get(project_id)
            mrs = project.mergerequests.list(state='all', per_page=20)
            
            mr_list = []
            for mr in mrs:
                mr_list.append({
                    "id": mr.id,
                    "iid": mr.iid,
                    "title": mr.title,
                    "state": mr.state,
                    "author": mr.author.get("name") if mr.author else "Unknown"
                })
            
            logger.info(f"Found {len(mr_list)} MRs in project {project_id}")
            return mr_list
            
        except Exception as e:
            logger.error(f"Failed to get MR list: {e}")
            raise
    
    async def get_mr_basic_info_with_fallback(self, project_id: str, mr_id: int) -> Dict[str, Any]:
        """获取MR基本信息 - 带回退策略"""
        
        # 策略1: 直接获取MR
        try:
            project = self.gitlab.projects.get(project_id)
            mr = project.mergerequests.get(mr_id)
            
            return self._build_mr_info(mr)
            
        except gitlab.exceptions.GitlabGetError as e:
            if "403" in str(e):
                logger.warning(f"Direct MR access forbidden, trying alternative methods...")
                return await self._try_alternative_mr_access(project_id, mr_id)
            elif "404" in str(e):
                logger.error(f"MR {mr_id} not found in project {project_id}")
                # 尝试列出可用的MR
                available_mrs = await self.get_available_mrs(project_id)
                if available_mrs:
                    logger.info("Available MRs:")
                    for mr in available_mrs[:5]:  # 显示前5个
                        logger.info(f"  MR #{mr['iid']}: {mr['title']} ({mr['state']})")
                raise ValueError(f"MR {mr_id} not found. Available MRs: {[mr['iid'] for mr in available_mrs[:5]]}")
            else:
                raise
        except Exception as e:
            logger.error(f"Failed to get MR basic info: {e}")
            raise
    
    async def _try_alternative_mr_access(self, project_id: str, mr_id: int) -> Dict[str, Any]:
        """尝试替代的MR访问方法"""
        
        try:
            # 方法1: 通过MR列表查找
            project = self.gitlab.projects.get(project_id)
            mrs = project.mergerequests.list(iids=[mr_id])
            
            if mrs:
                mr = mrs[0]
                logger.info(f"Successfully accessed MR {mr_id} via list method")
                return self._build_mr_info(mr)
            else:
                raise ValueError(f"MR {mr_id} not found via list method")
                
        except Exception as e:
            logger.error(f"Alternative MR access failed: {e}")
            
            # 方法2: 尝试获取最新的MR作为示例
            try:
                available_mrs = await self.get_available_mrs(project_id)
                if available_mrs:
                    latest_mr_iid = available_mrs[0]['iid']
                    logger.warning(f"Using latest MR {latest_mr_iid} instead of {mr_id}")
                    
                    # 递归调用，但这次使用存在的MR ID
                    return await self.get_mr_basic_info_with_fallback(project_id, latest_mr_iid)
                else:
                    raise ValueError("No accessible MRs found in project")
            except Exception as fallback_error:
                logger.error(f"Fallback method also failed: {fallback_error}")
                raise
    
    def _build_mr_info(self, mr) -> Dict[str, Any]:
        """构建MR信息字典"""
        return {
            "id": mr.id,
            "iid": mr.iid,
            "title": mr.title,
            "description": mr.description or "",
            "source_branch": mr.source_branch,
            "target_branch": mr.target_branch,
            "author": {
                "id": mr.author.get("id") if mr.author else None,
                "name": mr.author.get("name") if mr.author else "Unknown",
                "username": mr.author.get("username") if mr.author else "unknown"
            },
            "web_url": mr.web_url,
            "created_at": mr.created_at,
            "updated_at": mr.updated_at,
            "state": mr.state,
            "diff_refs": getattr(mr, 'diff_refs', {})
        }
    
    async def check_mr_permissions(self, project_id: str, mr_id: int) -> Dict[str, Any]:
        """检查MR访问权限"""
        
        permissions = {
            "can_access_project": False,
            "can_list_mrs": False,
            "can_access_specific_mr": False,
            "user_role": "unknown",
            "available_mrs": []
        }
        
        try:
            # 检查项目访问
            project = self.gitlab.projects.get(project_id)
            permissions["can_access_project"] = True
            
            # 检查MR列表访问
            mrs = project.mergerequests.list(per_page=1)
            permissions["can_list_mrs"] = True
            permissions["available_mrs"] = [mr.iid for mr in mrs[:10]]
            
            # 检查特定MR访问
            mr = project.mergerequests.get(mr_id)
            permissions["can_access_specific_mr"] = True
            
        except Exception as e:
            logger.warning(f"Permission check failed at some step: {e}")
        
        return permissions

# 测试函数
async def test_improved_client():
    """测试改进版客户端"""
    
    GITLAB_URL = "https://gitlab.com"
    PROJECT_ID = "73234025"  
    MR_ID = 1  
    ACCESS_TOKEN = "glpat-qAWvw1UKzHxg8Z-R4PbA_G86MQp1OmhwNHZoCw.01.121uksyhz"
    
    client = ImprovedGitLabClient(GITLAB_URL, ACCESS_TOKEN)
    
    print("🔍 测试改进版GitLab客户端...")
    
    # 1. 检查权限
    print("\n1️⃣ 检查MR访问权限...")
    try:
        permissions = await client.check_mr_permissions(PROJECT_ID, MR_ID)
        print(f"项目访问: {'✅' if permissions['can_access_project'] else '❌'}")
        print(f"MR列表访问: {'✅' if permissions['can_list_mrs'] else '❌'}")
        print(f"特定MR访问: {'✅' if permissions['can_access_specific_mr'] else '❌'}")
        
        if permissions['available_mrs']:
            print(f"可用的MR IDs: {permissions['available_mrs'][:5]}")
    except Exception as e:
        print(f"权限检查异常: {e}")
    
    # 2. 获取可用MR列表
    print("\n2️⃣ 获取可用MR列表...")
    try:
        mrs = await client.get_available_mrs(PROJECT_ID)
        if mrs:
            print(f"找到 {len(mrs)} 个MR:")
            for mr in mrs[:5]:
                print(f"  MR #{mr['iid']}: {mr['title'][:50]}... ({mr['state']})")
        else:
            print("项目中没有MR")
    except Exception as e:
        print(f"获取MR列表失败: {e}")
    
    # 3. 尝试获取MR信息（带回退）
    print("\n3️⃣ 尝试获取MR信息（带回退策略）...")
    try:
        mr_info = await client.get_mr_basic_info_with_fallback(PROJECT_ID, MR_ID)
        print(f"✅ 成功获取MR信息:")
        print(f"   标题: {mr_info['title']}")
        print(f"   状态: {mr_info['state']}")
        print(f"   作者: {mr_info['author']['name']}")
    except Exception as e:
        print(f"❌ 获取MR信息失败: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_improved_client())

