"""
Mock GitLab客户端 - 用于内测，不需要真实GitLab实例
"""
import asyncio
import json
import random
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

from core.gitlab_client import FilePatchInfo

class MockGitLabClient:
    """模拟GitLab客户端，用于内测"""
    
    def __init__(self, gitlab_url: str, access_token: str):
        self.gitlab_url = gitlab_url
        self.access_token = access_token
        self._mock_data = self._generate_mock_data()
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        pass
    
    def _generate_mock_data(self) -> Dict[str, Any]:
        """生成模拟数据"""
        return {
            "projects": {
                "123": {
                    "id": 123,
                    "name": "awesome-project",
                    "description": "一个很棒的测试项目",
                    "default_branch": "main"
                }
            },
            "merge_requests": {
                "456": {
                    "id": 456,
                    "iid": 456,
                    "title": "feat: 添加用户认证功能",
                    "description": """
## 功能说明
添加了用户认证功能，包括：
- JWT token认证
- 用户登录/注册
- 权限验证中间件

## 测试说明
- 添加了单元测试
- 通过了集成测试
                    """.strip(),
                    "source_branch": "feature/user-auth",
                    "target_branch": "main",
                    "author": {
                        "id": 1,
                        "name": "张三",
                        "username": "zhangsan"
                    },
                    "web_url": f"{self.gitlab_url}/awesome-project/-/merge_requests/456",
                    "created_at": (datetime.now() - timedelta(hours=2)).isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "state": "opened",
                    "diff_refs": {
                        "base_sha": "abc123def456",
                        "head_sha": "def456ghi789",
                        "start_sha": "abc123def456"
                    }
                }
            }
        }
    
    async def get_mr_basic_info(self, project_id: str, mr_id: int) -> Dict[str, Any]:
        """获取MR基本信息（模拟）"""
        await asyncio.sleep(0.1)  # 模拟网络延迟
        
        if str(mr_id) in self._mock_data["merge_requests"]:
            return self._mock_data["merge_requests"][str(mr_id)]
        else:
            # 生成随机MR数据
            return {
                "id": mr_id,
                "iid": mr_id,
                "title": f"测试MR #{mr_id}",
                "description": f"这是一个测试用的MR #{mr_id}",
                "source_branch": f"feature/test-{mr_id}",
                "target_branch": "main",
                "author": {
                    "id": random.randint(1, 100),
                    "name": f"用户{random.randint(1, 10)}",
                    "username": f"user{random.randint(1, 10)}"
                },
                "web_url": f"{self.gitlab_url}/project/-/merge_requests/{mr_id}",
                "created_at": (datetime.now() - timedelta(hours=random.randint(1, 24))).isoformat(),
                "updated_at": datetime.now().isoformat(),
                "state": "opened",
                "diff_refs": {
                    "base_sha": f"base{random.randint(1000, 9999)}",
                    "head_sha": f"head{random.randint(1000, 9999)}",
                    "start_sha": f"start{random.randint(1000, 9999)}"
                }
            }
    
    async def get_mr_changes(self, project_id: str, mr_id: int) -> Dict[str, Any]:
        """获取MR变更信息（模拟）"""
        await asyncio.sleep(0.2)  # 模拟网络延迟
        
        # 模拟不同类型的文件变更
        mock_changes = [
            {
                "old_path": "src/auth/login.py",
                "new_path": "src/auth/login.py",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": self._generate_python_diff("src/auth/login.py")
            },
            {
                "old_path": "tests/test_auth.py",
                "new_path": "tests/test_auth.py", 
                "new_file": True,
                "deleted_file": False,
                "renamed_file": False,
                "diff": self._generate_test_diff("tests/test_auth.py")
            },
            {
                "old_path": "src/middleware.py",
                "new_path": "src/middleware.py",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": self._generate_middleware_diff("src/middleware.py")
            },
            {
                "old_path": "docs/api.md",
                "new_path": "docs/api.md",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": self._generate_doc_diff("docs/api.md")
            }
        ]
        
        return {"changes": mock_changes}
    
    async def get_file_content(self, project_id: str, file_path: str, ref: str) -> str:
        """获取文件内容（模拟）"""
        await asyncio.sleep(0.05)  # 模拟网络延迟
        
        # 根据文件类型返回模拟内容
        if file_path.endswith('.py'):
            return self._generate_python_content(file_path)
        elif file_path.endswith('.js'):
            return self._generate_js_content(file_path)
        elif file_path.endswith('.md'):
            return self._generate_md_content(file_path)
        else:
            return f"# {file_path}\n这是一个模拟的文件内容"
    
    async def get_diff_files(self, project_id: str, mr_id: int) -> List[FilePatchInfo]:
        """获取MR的差异文件列表（模拟）"""
        changes_data = await self.get_mr_changes(project_id, mr_id)
        changes = changes_data.get('changes', [])
        
        diff_files = []
        for change in changes:
            # 模拟异步获取文件内容
            old_content = await self.get_file_content(project_id, change['old_path'], 'base')
            new_content = await self.get_file_content(project_id, change['new_path'], 'head')
            
            edit_type = self._determine_edit_type(change)
            
            diff_files.append(FilePatchInfo(
                filename=change['new_path'],
                old_content=old_content if not change['new_file'] else "",
                new_content=new_content if not change['deleted_file'] else "",
                patch=change['diff'],
                edit_type=edit_type,
                old_filename=change['old_path'] if change['old_path'] != change['new_path'] else None
            ))
        
        return diff_files
    
    async def create_mr_note(self, project_id: str, mr_id: int, body: str) -> Dict:
        """在MR上创建评论（模拟）"""
        await asyncio.sleep(0.3)  # 模拟网络延迟
        
        note_id = random.randint(1000, 9999)
        return {
            "id": note_id,
            "body": body,
            "created_at": datetime.now().isoformat(),
            "web_url": f"{self.gitlab_url}/project/-/merge_requests/{mr_id}#note_{note_id}"
        }
    
    async def update_mr_description(self, project_id: str, mr_id: int, 
                                   title: Optional[str] = None, 
                                   description: Optional[str] = None) -> bool:
        """更新MR描述（模拟）"""
        await asyncio.sleep(0.2)  # 模拟网络延迟
        return True
    
    def get_mr_url(self, project_id: str, mr_id: int) -> str:
        """获取MR的Web URL"""
        return f"{self.gitlab_url}/{project_id}/-/merge_requests/{mr_id}"
    
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
    
    def _generate_python_diff(self, file_path: str) -> str:
        """生成Python文件的diff"""
        return '''@@ -15,6 +15,23 @@ from flask import request, jsonify
 from werkzeug.security import check_password_hash, generate_password_hash
 import jwt
 
+def validate_token(token):
+    """验证JWT token"""
+    try:
+        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
+        return payload['user_id']
+    except jwt.ExpiredSignatureError:
+        return None
+    except jwt.InvalidTokenError:
+        return None
+
+def generate_token(user_id):
+    """生成JWT token"""
+    payload = {
+        'user_id': user_id,
+        'exp': datetime.utcnow() + timedelta(hours=24)
+    }
+    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')
+
 @app.route('/login', methods=['POST'])
 def login():
     data = request.get_json()
@@ -25,10 +42,15 @@ def login():
     user = User.query.filter_by(username=username).first()
     
     if user and check_password_hash(user.password, password):
-        # TODO: 添加JWT token生成
-        return jsonify({'message': 'Login successful'}), 200
+        token = generate_token(user.id)
+        return jsonify({
+            'message': 'Login successful',
+            'token': token,
+            'user_id': user.id
+        }), 200
     else:
-        return jsonify({'error': 'Invalid credentials'}), 401
+        return jsonify({'error': 'Invalid username or password'}), 401
+
 
 @app.route('/register', methods=['POST'])
 def register():'''
    
    def _generate_test_diff(self, file_path: str) -> str:
        """生成测试文件的diff"""
        return '''@@ -0,0 +1,45 @@
+import unittest
+import json
+from app import app, db
+from models import User
+
+class AuthTestCase(unittest.TestCase):
+    def setUp(self):
+        self.app = app.test_client()
+        self.app.testing = True
+        db.create_all()
+        
+    def tearDown(self):
+        db.session.remove()
+        db.drop_all()
+    
+    def test_user_registration(self):
+        """测试用户注册"""
+        response = self.app.post('/register', 
+                               data=json.dumps({
+                                   'username': 'testuser',
+                                   'password': 'testpass123'
+                               }),
+                               content_type='application/json')
+        self.assertEqual(response.status_code, 201)
+        data = json.loads(response.data)
+        self.assertIn('message', data)
+    
+    def test_user_login_success(self):
+        """测试用户登录成功"""
+        # 先注册用户
+        self.app.post('/register', 
+                     data=json.dumps({
+                         'username': 'testuser',
+                         'password': 'testpass123'
+                     }),
+                     content_type='application/json')
+        
+        # 登录
+        response = self.app.post('/login',
+                               data=json.dumps({
+                                   'username': 'testuser',
+                                   'password': 'testpass123'
+                               }),
+                               content_type='application/json')
+        self.assertEqual(response.status_code, 200)
+        data = json.loads(response.data)
+        self.assertIn('token', data)
+
+if __name__ == '__main__':
+    unittest.main()'''

    def _generate_middleware_diff(self, file_path: str) -> str:
        """生成中间件文件的diff"""
        return '''@@ -1,8 +1,25 @@
 from functools import wraps
 from flask import request, jsonify, current_app
+from auth.login import validate_token
 
-def auth_required(f):
+def token_required(f):
+    """JWT token验证装饰器"""
     @wraps(f)
     def decorated(*args, **kwargs):
-        # TODO: 添加认证逻辑
-        return f(*args, **kwargs)
+        token = request.headers.get('Authorization')
+        
+        if not token:
+            return jsonify({'error': 'Token is missing'}), 401
+        
+        # 移除 'Bearer ' 前缀
+        if token.startswith('Bearer '):
+            token = token[7:]
+        
+        user_id = validate_token(token)
+        if user_id is None:
+            return jsonify({'error': 'Token is invalid or expired'}), 401
+            
+        # 将用户ID传递给路由函数
+        return f(user_id=user_id, *args, **kwargs)
+    
     return decorated'''

    def _generate_doc_diff(self, file_path: str) -> str:
        """生成文档文件的diff"""
        return '''@@ -12,6 +12,35 @@ API接口文档
 ### 用户注册
 `POST /register`
 
+### 用户登录
+`POST /login`
+
+请求体:
+```json
+{
+    "username": "用户名",
+    "password": "密码"
+}
+```
+
+响应:
+```json
+{
+    "message": "Login successful",
+    "token": "jwt_token_here",
+    "user_id": 123
+}
+```
+
+### 认证说明
+
+- 登录成功后会返回JWT token
+- 需要认证的接口需要在请求头添加: `Authorization: Bearer <token>`
+- Token有效期为24小时
+
+### 受保护的接口
+所有需要认证的接口都需要携带有效的JWT token。
+
 ## 错误代码
 
 - 400: 请求参数错误'''

    def _generate_python_content(self, file_path: str) -> str:
        """生成Python文件内容"""
        if "auth" in file_path:
            return '''from flask import Flask, request, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
import jwt
from datetime import datetime, timedelta

app = Flask(__name__)

def login():
    """用户登录接口"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    # 验证用户凭据
    user = User.query.filter_by(username=username).first()
    
    if user and check_password_hash(user.password, password):
        return jsonify({'message': 'Login successful'}), 200
    else:
        return jsonify({'error': 'Invalid credentials'}), 401
'''
        else:
            return f'''# {file_path}
"""
这是一个模拟的Python文件
"""

def example_function():
    """示例函数"""
    pass
'''

    def _generate_js_content(self, file_path: str) -> str:
        """生成JavaScript文件内容"""
        return f'''// {file_path}
/**
 * 这是一个模拟的JavaScript文件
 */

function exampleFunction() {{
    console.log("Hello from {file_path}");
}}

export default exampleFunction;
'''

    def _generate_md_content(self, file_path: str) -> str:
        """生成Markdown文件内容"""
        return f'''# {file_path.split('/')[-1]}

这是一个模拟的Markdown文件。

## 功能说明

这个文件包含了项目的相关文档。

## 使用方法

1. 步骤一
2. 步骤二
3. 步骤三
'''