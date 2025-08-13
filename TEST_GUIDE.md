# 🧪 GitLab Code Reviewer 内测指南

## 🚀 快速开始内测（无需真实GitLab）

### 1. 准备环境

```bash
# 确保安装了Python依赖
pip install -r requirements.txt

# 配置环境变量（可选，内测模式不强制要求）
cp .env.example .env
```

**注意**: 内测模式使用Mock数据，**不需要真实的GitLab实例和API密钥**！

### 2. 启动内测服务

```bash
# 启动内测API服务器
python test_api.py
```

服务启动后：
- 🌐 API文档: http://localhost:8001/docs
- 🏠 内测首页: http://localhost:8001

### 3. 一键快速测试

```bash
# 运行完整测试套件
python quick_test.py

# 或者测试特定场景
python quick_test.py --scenario security_issues
python quick_test.py --performance
python quick_test.py --ai
```

## 📋 可用的测试场景

### 🎯 内置Mock场景

| 场景 | 描述 | 模拟内容 |
|------|------|----------|
| `default` | 默认场景 | Python认证功能MR，中等质量代码 |
| `high_quality` | 高质量代码 | 完美代码示例，几乎无问题 |
| `security_issues` | 安全问题 | 包含SQL注入、XSS等安全漏洞 |
| `performance_issues` | 性能问题 | N+1查询、内存泄漏等性能瓶颈 |
| `large_mr` | 大型MR | 多文件复杂重构 |

### 🔍 审查类型测试

- **full**: 全面代码质量审查
- **security**: 安全漏洞专项检测  
- **performance**: 性能问题分析
- **quick**: 快速基础检查

## 🧪 内测方式

### 方式1: API调用测试

```bash
# 测试默认场景
curl -X POST "http://localhost:8001/test/review" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "123",
    "mr_id": 456,
    "review_type": "full", 
    "mock_scenario": "default"
  }'

# 测试安全问题场景
curl -X POST "http://localhost:8001/test/review" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "123",
    "mr_id": 456,
    "review_type": "security",
    "mock_scenario": "security_issues"
  }'
```

### 方式2: Web界面测试

访问 http://localhost:8001/docs 使用Swagger UI：

1. 点击 `POST /test/review`
2. 点击 "Try it out"
3. 修改请求参数
4. 点击 "Execute"

### 方式3: Python代码测试

```python
import asyncio
import aiohttp

async def test_review():
    async with aiohttp.ClientSession() as session:
        payload = {
            "project_id": "123",
            "mr_id": 456,
            "review_type": "full",
            "mock_scenario": "default"
        }
        
        async with session.post(
            "http://localhost:8001/test/review",
            json=payload
        ) as response:
            result = await response.json()
            print(f"评分: {result['score']}/10.0")
            print(f"问题数: {len(result['findings'])}")

asyncio.run(test_review())
```

## 📊 内测功能列表

### ✅ 可用功能

- [x] **Mock GitLab数据**: 无需真实GitLab实例
- [x] **多场景测试**: 5种预设测试场景
- [x] **AI分析测试**: 测试AI模型连接和分析
- [x] **性能测试**: 并发请求性能测试
- [x] **批量测试**: 一次测试多个场景
- [x] **完整API**: 所有审查功能都可测试
- [x] **实时日志**: 详细的执行日志
- [x] **错误处理**: 完善的异常处理测试

### 🧪 内测接口列表

| 接口 | 功能 | 说明 |
|------|------|------|
| `GET /` | 内测首页 | 查看内测环境信息 |
| `GET /health` | 健康检查 | 验证服务状态 |
| `POST /test/review` | 审查测试 | 主要测试接口 |
| `GET /test/scenarios` | 场景列表 | 查看可用测试场景 |
| `GET /test/demo-data` | 演示数据 | 获取示例数据 |
| `GET /test/ai-models` | AI测试 | 测试AI模型连接 |
| `POST /test/batch-review` | 批量测试 | 批量场景测试 |
| `POST /test/performance` | 性能测试 | 并发性能测试 |

## 🎯 内测重点

### 🔍 功能验证

1. **审查逻辑**: 验证不同场景的审查结果
2. **评分机制**: 检查评分是否合理
3. **问题检测**: 确认能正确识别代码问题
4. **性能表现**: 测试响应速度和并发能力

### 🐛 问题排查

1. **AI模型连接**: 检查OpenAI/Claude API配置
2. **内存使用**: 监控大文件处理时的内存占用
3. **错误处理**: 验证异常情况的处理
4. **日志输出**: 检查日志信息的完整性

## 🔄 从内测到生产

### 阶段1: 内测验证 ✅
```bash
# 当前阶段 - 使用Mock数据测试
python test_api.py
python quick_test.py
```

### 阶段2: 真实集成测试
```bash
# 配置真实GitLab信息
export GITLAB_URL="https://your-gitlab.com"
export GITLAB_TOKEN="glpat-xxxx"

# 启动真实服务
python -m uvicorn api.main:app --port 8000

# 测试真实MR
curl -X POST "http://localhost:8000/review" \
  -d '{"gitlab_url":"https://your-gitlab.com","project_id":"123","mr_id":456,"access_token":"glpat-xxxx"}'
```

### 阶段3: 生产部署
```bash
# 生产环境部署
./deployment/scripts/deploy.sh prod
```

## 💡 内测技巧

### 🎪 场景组合测试

```bash
# 测试不同审查类型 + 场景组合
for scenario in default security_issues performance_issues; do
  for type in full security performance quick; do
    echo "测试: $scenario + $type"
    curl -X POST "http://localhost:8001/test/review" \
      -H "Content-Type: application/json" \
      -d "{\"mock_scenario\":\"$scenario\",\"review_type\":\"$type\"}"
  done
done
```

### 📈 性能基准测试

```bash
# 记录性能基准
python quick_test.py --performance > performance_baseline.txt

# 对比性能变化
diff performance_baseline.txt performance_current.txt
```

### 🔧 自定义Mock数据

修改 `tests/mock_gitlab_client.py` 添加你的测试场景：

```python
# 在_generate_mock_data中添加新场景
"custom_scenario": {
    "files": ["your_file.py"],
    "changes": [/* 你的变更数据 */]
}
```

## ⚠️ 注意事项

1. **内测模式限制**: 
   - 使用模拟数据，不会访问真实GitLab
   - AI分析结果可能与真实场景有差异

2. **AI API使用**:
   - 内测时仍会调用真实AI API
   - 建议设置较低的成本限制

3. **端口冲突**:
   - 内测服务使用8001端口
   - 真实服务使用8000端口

## 🆘 故障排除

### 常见问题

**Q: 内测服务启动失败**
```bash
# 检查依赖
pip install -r requirements.txt

# 检查端口占用
netstat -tlnp | grep 8001
```

**Q: AI模型测试失败**
```bash
# 检查环境变量
echo $OPENAI_API_KEY

# 测试网络连接
curl -I https://api.openai.com
```

**Q: Mock数据不符合预期**
```bash
# 查看Mock数据生成逻辑
python -c "from tests.mock_gitlab_client import MockGitLabClient; print(MockGitLabClient('','')._generate_mock_data())"
```

---

## 🎉 开始内测！

```bash
# 一键启动内测
python test_api.py &
python quick_test.py

# 访问Web界面
open http://localhost:8001/docs
```

**享受快速、无依赖的AI代码审查内测体验！** 🚀