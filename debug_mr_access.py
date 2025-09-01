#!/usr/bin/env python3
"""
详细的MR访问权限诊断脚本
"""
import requests
import json

def debug_mr_access():
    """详细诊断MR访问权限"""
    
    GITLAB_URL = "https://gitlab.com"
    PROJECT_ID = "73234025"  
    MR_ID = "1"  
    ACCESS_TOKEN = "glpat-qAWvw1UKzHxg8Z-R4PbA_G86MQp1OmhwNHZoCw.01.121uksyhz"
    
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    
    print("🔍 详细诊断MR访问权限问题...")
    print("=" * 60)
    
    # 1. 检查用户在项目中的权限
    print("\n1️⃣ 检查用户在项目中的权限...")
    try:
        response = requests.get(f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/members/all", headers=headers, timeout=10)
        if response.status_code == 200:
            members = response.json()
            current_user_id = None
            
            # 先获取当前用户ID
            user_response = requests.get(f"{GITLAB_URL}/api/v4/user", headers=headers, timeout=10)
            if user_response.status_code == 200:
                current_user_id = user_response.json().get('id')
                print(f"当前用户ID: {current_user_id}")
            
            # 查找当前用户的权限
            user_permission = None
            for member in members:
                if member.get('id') == current_user_id:
                    access_level = member.get('access_level', 0)
                    access_level_names = {
                        10: "Guest", 20: "Reporter", 30: "Developer", 
                        40: "Maintainer", 50: "Owner"
                    }
                    user_permission = access_level_names.get(access_level, f"Unknown({access_level})")
                    print(f"✅ 用户权限级别: {user_permission} ({access_level})")
                    break
            
            if not user_permission:
                print("⚠️  未找到用户在项目中的直接权限，可能通过组继承")
        else:
            print(f"⚠️  无法获取项目成员列表: {response.status_code}")
    except Exception as e:
        print(f"❌ 检查权限异常: {e}")
    
    # 2. 列出所有MR，看看是否存在
    print("\n2️⃣ 检查项目中的MR列表...")
    try:
        response = requests.get(f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/merge_requests", headers=headers, timeout=10)
        if response.status_code == 200:
            mrs = response.json()
            print(f"✅ 项目中共有 {len(mrs)} 个MR")
            
            if mrs:
                print("前5个MR:")
                for i, mr in enumerate(mrs[:5]):
                    print(f"   MR #{mr.get('iid')}: {mr.get('title')} - {mr.get('state')}")
                    
                # 检查我们要访问的MR是否在列表中
                target_mr = None
                for mr in mrs:
                    if str(mr.get('iid')) == str(MR_ID):
                        target_mr = mr
                        break
                
                if target_mr:
                    print(f"✅ 找到目标MR #{MR_ID}: {target_mr.get('title')}")
                    print(f"   状态: {target_mr.get('state')}")
                    print(f"   作者: {target_mr.get('author', {}).get('name')}")
                else:
                    print(f"❌ 未找到MR #{MR_ID}")
                    print("💡 建议: 检查MR ID是否正确，或者MR是否已被删除")
            else:
                print("⚠️  项目中没有MR")
        else:
            print(f"❌ 无法获取MR列表: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ 获取MR列表异常: {e}")
    
    # 3. 尝试不同的MR访问方式
    print("\n3️⃣ 尝试不同的MR访问方式...")
    
    # 方式1: 直接访问 (之前失败的方式)
    print("方式1: 直接访问MR")
    try:
        response = requests.get(f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/merge_requests/{MR_ID}", headers=headers, timeout=10)
        if response.status_code == 200:
            print("✅ 直接访问成功")
        else:
            print(f"❌ 直接访问失败: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ 直接访问异常: {e}")
    
    # 方式2: 通过查询参数访问
    print("\n方式2: 通过查询参数访问")
    try:
        response = requests.get(f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/merge_requests?iids[]={MR_ID}", headers=headers, timeout=10)
        if response.status_code == 200:
            mrs = response.json()
            if mrs:
                print("✅ 查询参数访问成功")
                mr = mrs[0]
                print(f"   MR信息: {mr.get('title')}")
            else:
                print("❌ 查询参数访问返回空结果")
        else:
            print(f"❌ 查询参数访问失败: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ 查询参数访问异常: {e}")
    
    # 4. 检查项目设置
    print("\n4️⃣ 检查项目相关设置...")
    try:
        response = requests.get(f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}", headers=headers, timeout=10)
        if response.status_code == 200:
            project = response.json()
            
            # 检查合并请求相关设置
            mr_enabled = project.get('merge_requests_enabled', True)
            visibility = project.get('visibility', 'unknown')
            
            print(f"✅ 项目设置检查:")
            print(f"   合并请求功能: {'启用' if mr_enabled else '禁用'}")
            print(f"   项目可见性: {visibility}")
            
            # 检查项目权限设置
            permissions = project.get('permissions', {})
            if permissions:
                project_access = permissions.get('project_access')
                group_access = permissions.get('group_access')
                
                if project_access:
                    print(f"   项目访问级别: {project_access.get('access_level', 'unknown')}")
                if group_access:
                    print(f"   组访问级别: {group_access.get('access_level', 'unknown')}")
        else:
            print(f"❌ 无法获取项目详细信息: {response.status_code}")
    except Exception as e:
        print(f"❌ 检查项目设置异常: {e}")
    
    print("\n" + "=" * 60)
    print("🔍 诊断完成")
    print("\n💡 可能的解决方案:")
    print("1. 如果MR不存在，请检查MR ID是否正确")
    print("2. 如果是权限问题，请联系项目管理员提升机器人账户权限")
    print("3. 机器人账户可能需要至少Reporter权限才能访问MR详情")
    print("4. 某些私有项目可能对机器人账户有特殊限制")

if __name__ == "__main__":
    debug_mr_access()


