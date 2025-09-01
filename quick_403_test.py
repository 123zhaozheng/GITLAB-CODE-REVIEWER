#!/usr/bin/env python3
"""
快速403错误测试脚本
"""
import requests
import json

def test_gitlab_access():
    """快速测试GitLab访问"""
    
    # 这里填入你的实际参数
    GITLAB_URL = "https://gitlab.com"  # 替换为你的GitLab URL
    PROJECT_ID = "73234025"  # 替换为你的项目ID  
    MR_ID = "2"  # 替换为你的MR ID
    # 如果MR 1不存在，可以尝试其他ID，比如最新的MR
    ACCESS_TOKEN = "glpat-m9CrqoTgme6Lm4qtABk8XG86MQp1OmhwNXVuCw.01.120t008z4"  # 替换为你的access token
    
    print("🔍 快速测试GitLab 403错误...")
    print(f"GitLab URL: {GITLAB_URL}")
    print(f"Project ID: {PROJECT_ID}")
    print(f"MR ID: {MR_ID}")
    print(f"Token: {ACCESS_TOKEN[:10]}..." if len(ACCESS_TOKEN) > 10 else ACCESS_TOKEN)
    
    # 测试用户信息
    print("\n1️⃣ 测试Token有效性...")
    try:
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        response = requests.get(f"{GITLAB_URL}/api/v4/user", headers=headers, timeout=10)
        
        if response.status_code == 200:
            user_info = response.json()
            print(f"✅ Token有效，用户: {user_info.get('name')} (@{user_info.get('username')})")
        else:
            print(f"❌ Token验证失败: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Token验证异常: {e}")
        return False
    
    # 测试项目访问
    print("\n2️⃣ 测试项目访问...")
    try:
        response = requests.get(f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}", headers=headers, timeout=10)
        
        if response.status_code == 200:
            project_info = response.json()
            print(f"✅ 项目访问成功: {project_info.get('name')}")
            print(f"   可见性: {project_info.get('visibility')}")
        else:
            print(f"❌ 项目访问失败: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ 项目访问异常: {e}")
        return False
    
    # 测试MR访问
    print("\n3️⃣ 测试MR访问...")
    try:
        response = requests.get(f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/merge_requests/{MR_ID}", headers=headers, timeout=10)
        
        if response.status_code == 200:
            mr_info = response.json()
            print(f"✅ MR访问成功: {mr_info.get('title')}")
            print(f"   状态: {mr_info.get('state')}")
            print(f"   作者: {mr_info.get('author', {}).get('name')}")
        else:
            print(f"❌ MR访问失败: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ MR访问异常: {e}")
        return False
    
    print("\n🎉 所有测试通过！你的配置是正确的。")
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("GitLab 403错误快速测试")
    print("=" * 60)
    print("\n⚠️  请先修改脚本中的配置参数:")
    print("   - GITLAB_URL: 你的GitLab实例URL")
    print("   - PROJECT_ID: 项目ID") 
    print("   - MR_ID: Merge Request ID")
    print("   - ACCESS_TOKEN: 你的GitLab访问令牌")
    print("\n然后运行: python quick_403_test.py")
    print("=" * 60)
    
    # 如果你已经修改了配置，取消下面这行的注释
    test_gitlab_access()
