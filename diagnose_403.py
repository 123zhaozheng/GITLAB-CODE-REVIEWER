#!/usr/bin/env python3
"""
GitLab 403错误诊断脚本
帮助诊断和解决GitLab API 403 Forbidden错误
"""
import os
import sys
import asyncio
import requests
import gitlab
from urllib.parse import urlparse
import json

def print_header(title):
    print(f"\n{'='*60}")
    print(f"🔍 {title}")
    print('='*60)

def print_success(message):
    print(f"✅ {message}")

def print_error(message):
    print(f"❌ {message}")

def print_warning(message):
    print(f"⚠️  {message}")

def print_info(message):
    print(f"ℹ️  {message}")

async def diagnose_gitlab_connection(gitlab_url, project_id, mr_id, access_token):
    """诊断GitLab连接问题"""
    
    print_header("GitLab 403错误诊断")
    
    # 1. 检查基本配置
    print_info("1. 检查基本配置...")
    
    if not gitlab_url:
        print_error("GitLab URL 未设置")
        return False
    
    if not access_token:
        print_error("Access Token 未设置")
        return False
        
    if not project_id:
        print_error("Project ID 未设置")
        return False
        
    if not mr_id:
        print_error("MR ID 未设置")
        return False
    
    print_success(f"GitLab URL: {gitlab_url}")
    print_success(f"Project ID: {project_id}")
    print_success(f"MR ID: {mr_id}")
    print_success(f"Token: {access_token[:10]}...{access_token[-4:] if len(access_token) > 14 else access_token}")
    
    # 2. 验证URL格式
    print_info("\n2. 验证URL格式...")
    try:
        parsed = urlparse(gitlab_url)
        if not parsed.scheme or not parsed.netloc:
            print_error("GitLab URL格式不正确")
            return False
        print_success("URL格式正确")
    except Exception as e:
        print_error(f"URL解析错误: {e}")
        return False
    
    # 3. 测试网络连接
    print_info("\n3. 测试网络连接...")
    try:
        response = requests.get(f"{gitlab_url.rstrip('/')}/api/v4/version", timeout=10)
        if response.status_code == 200:
            version_info = response.json()
            print_success(f"GitLab连接成功，版本: {version_info.get('version', 'unknown')}")
        else:
            print_warning(f"GitLab响应状态码: {response.status_code}")
    except Exception as e:
        print_error(f"网络连接失败: {e}")
        return False
    
    # 4. 测试Token有效性
    print_info("\n4. 测试Access Token...")
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(f"{gitlab_url.rstrip('/')}/api/v4/user", headers=headers, timeout=10)
        
        if response.status_code == 200:
            user_info = response.json()
            print_success(f"Token有效，用户: {user_info.get('name', 'unknown')} (@{user_info.get('username', 'unknown')})")
        elif response.status_code == 401:
            print_error("Token无效或已过期")
            return False
        else:
            print_error(f"Token验证失败，状态码: {response.status_code}")
            print_error(f"响应: {response.text}")
            return False
    except Exception as e:
        print_error(f"Token验证异常: {e}")
        return False
    
    # 5. 测试项目访问权限
    print_info("\n5. 测试项目访问权限...")
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(f"{gitlab_url.rstrip('/')}/api/v4/projects/{project_id}", headers=headers, timeout=10)
        
        if response.status_code == 200:
            project_info = response.json()
            print_success(f"项目访问成功: {project_info.get('name', 'unknown')}")
            print_info(f"项目可见性: {project_info.get('visibility', 'unknown')}")
            
            # 检查用户权限级别
            permissions = project_info.get('permissions', {})
            if permissions:
                project_access = permissions.get('project_access', {})
                group_access = permissions.get('group_access', {})
                if project_access:
                    print_info(f"项目权限级别: {project_access.get('access_level', 'unknown')}")
                if group_access:
                    print_info(f"组权限级别: {group_access.get('access_level', 'unknown')}")
            
        elif response.status_code == 404:
            print_error("项目不存在或无访问权限")
            return False
        elif response.status_code == 403:
            print_error("没有项目访问权限")
            return False
        else:
            print_error(f"项目访问失败，状态码: {response.status_code}")
            print_error(f"响应: {response.text}")
            return False
    except Exception as e:
        print_error(f"项目访问异常: {e}")
        return False
    
    # 6. 测试MR访问权限
    print_info("\n6. 测试MR访问权限...")
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(f"{gitlab_url.rstrip('/')}/api/v4/projects/{project_id}/merge_requests/{mr_id}", headers=headers, timeout=10)
        
        if response.status_code == 200:
            mr_info = response.json()
            print_success(f"MR访问成功: {mr_info.get('title', 'unknown')}")
            print_info(f"MR状态: {mr_info.get('state', 'unknown')}")
            print_info(f"作者: {mr_info.get('author', {}).get('name', 'unknown')}")
        elif response.status_code == 404:
            print_error("MR不存在")
            return False
        elif response.status_code == 403:
            print_error("没有MR访问权限")
            return False
        else:
            print_error(f"MR访问失败，状态码: {response.status_code}")
            print_error(f"响应: {response.text}")
            return False
    except Exception as e:
        print_error(f"MR访问异常: {e}")
        return False
    
    # 7. 测试python-gitlab库连接
    print_info("\n7. 测试python-gitlab库连接...")
    try:
        gl = gitlab.Gitlab(gitlab_url, private_token=access_token)
        gl.auth()
        
        project = gl.projects.get(project_id)
        print_success(f"python-gitlab连接成功: {project.name}")
        
        mr = project.mergerequests.get(mr_id)
        print_success(f"MR获取成功: {mr.title}")
        
    except gitlab.exceptions.GitlabAuthenticationError:
        print_error("GitLab认证失败")
        return False
    except gitlab.exceptions.GitlabGetError as e:
        print_error(f"GitLab获取错误: {e}")
        return False
    except Exception as e:
        print_error(f"python-gitlab异常: {e}")
        return False
    
    print_header("诊断完成")
    print_success("所有检查都通过了！403错误可能是暂时的网络问题。")
    return True

def print_solutions():
    """打印解决方案"""
    print_header("常见403错误解决方案")
    
    print("\n🔧 1. Access Token问题:")
    print("   - 确保Token有效且未过期")
    print("   - 检查Token权限，需要 'api' 权限")
    print("   - 如果是项目Token，确保有足够的角色权限")
    
    print("\n🔧 2. 项目权限问题:")
    print("   - 确保Token对应的用户有项目访问权限")
    print("   - 私有项目需要至少Reporter权限")
    print("   - 检查项目ID是否正确")
    
    print("\n🔧 3. MR权限问题:")
    print("   - 确保MR存在且未被删除")
    print("   - 检查MR ID是否正确")
    print("   - 某些受保护的MR可能需要更高权限")
    
    print("\n🔧 4. 网络和配置问题:")
    print("   - 检查GitLab URL是否正确")
    print("   - 确保网络连接正常")
    print("   - 检查防火墙设置")
    
    print("\n🔧 5. Token创建建议:")
    print("   - 使用Personal Access Token")
    print("   - 权限至少包含: api, read_api, read_repository")
    print("   - 设置合适的过期时间")

def main():
    """主函数"""
    print("🚀 GitLab 403错误诊断工具")
    print("此工具将帮助您诊断GitLab API 403 Forbidden错误")
    
    # 获取参数
    if len(sys.argv) >= 5:
        gitlab_url = sys.argv[1]
        project_id = sys.argv[2]
        mr_id = int(sys.argv[3])
        access_token = sys.argv[4]
    else:
        print("\n请提供以下信息:")
        gitlab_url = input("GitLab URL (例如: https://gitlab.com): ").strip()
        project_id = input("Project ID (例如: 123): ").strip()
        mr_id = int(input("MR ID (例如: 456): ").strip())
        access_token = input("Access Token (glpat-xxx): ").strip()
    
    # 运行诊断
    try:
        success = asyncio.run(diagnose_gitlab_connection(gitlab_url, project_id, mr_id, access_token))
        
        if not success:
            print_solutions()
    except KeyboardInterrupt:
        print("\n\n❌ 用户中断")
    except Exception as e:
        print_error(f"诊断过程出错: {e}")
        print_solutions()

if __name__ == "__main__":
    main()
