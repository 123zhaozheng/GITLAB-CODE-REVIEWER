# GitLab Code Reviewer - 快速开始指南

## 🚀 5分钟快速部署

### 1. 环境准备

确保已安装：
- Docker 20.10+
- Docker Compose 2.0+

### 2. 克隆和配置

```bash
# 克隆项目（如果从现有项目复制，跳过此步）
git clone <your-repo-url>
cd gitlab-code-reviewer

# 配置环境变量
cp .env.example .env

# 编辑配置文件，设置必要的API密钥
nano .env
```

**必须设置的环境变量：**
```bash
OPENAI_API_KEY=sk-your-openai-api-key-here
DEFAULT_AI_MODEL=gpt-4

# 如果使用OpenAI兼容的服务，还需设置：
# OPENAI_API_BASE=https://your-custom-openai-compatible-service.com/v1
# OPENAI_API_URL=https://your-custom-openai-compatible-service.com/v1  # 与OPENAI_API_BASE功能相同
```

**支持的AI服务配置示例：**

1. **标准OpenAI服务：**
```bash
OPENAI_API_KEY=sk-your-openai-api-key
DEFAULT_AI_MODEL=gpt-4
FALLBACK_AI_MODEL=gpt-3.5-turbo
```

2. **Azure OpenAI服务：**
```bash
OPENAI_API_KEY=your-azure-api-key
OPENAI_API_BASE=https://your-resource.openai.azure.com/
DEFAULT_AI_MODEL=gpt-4
AI_PROVIDER=azure
```

3. **自定义OpenAI兼容服务：**
```bash
OPENAI_API_KEY=your-custom-api-key
OPENAI_API_BASE=https://api.your-service.com/v1
DEFAULT_AI_MODEL=your-model-name
CUSTOM_LLM_PROVIDER=custom
```

### 3. 一键启动

```bash
# 使用部署脚本（推荐）
chmod +x deployment/scripts/deploy.sh
./deployment/scripts/deploy.sh dev

# 或手动启动
docker-compose up -d
```

### 4. 验证部署

```bash
# 健康检查
curl http://localhost:8000/health

# 查看API文档
open http://localhost:8000/docs
```

## 📖 基本使用

### 1. 审查单个MR

```bash
curl -X POST "http://localhost:8000/review" \
  -H "Content-Type: application/json" \
  -d '{
    "gitlab_url": "https://gitlab.example.com",
    "project_id": "123",
    "mr_id": 456,
    "access_token": "glpat-xxxx",
    "review_type": "full"
  }'
```

### 2. 支持的审查类型

- **full**: 全面代码质量审查
- **security**: 安全漏洞专项检测
- **performance**: 性能问题分析
- **quick**: 快速基础检查

### 3. Python客户端示例

```python
import aiohttp
import asyncio

async def review_mr():
    async with aiohttp.ClientSession() as session:
        payload = {
            "gitlab_url": "https://gitlab.example.com",
            "project_id": "123",
            "mr_id": 456,
            "access_token": "glpat-xxxx",
            "review_type": "full"
        }
        
        async with session.post(
            "http://localhost:8000/review",
            json=payload
        ) as response:
            result = await response.json()
            print(f"评分: {result['score']}/10.0")
            print(f"摘要: {result['summary']}")

# 运行
asyncio.run(review_mr())
```

## 🔧 GitLab CI/CD集成

### 1. 添加CI变量

在GitLab项目设置中添加：
- `GITLAB_TOKEN`: GitLab访问令牌
- `REVIEWER_API_URL`: 审查服务地址

### 2. 更新.gitlab-ci.yml

```yaml
stages:
  - code-review
  - test
  - deploy

code_review:
  stage: code-review
  image: curlimages/curl:latest
  script:
    - |
      if [ -z "$CI_MERGE_REQUEST_IID" ]; then
        echo "不是MR，跳过审查"
        exit 0
      fi
      
      echo "审查 MR $CI_MERGE_REQUEST_IID..."
      
      RESULT=$(curl -s -X POST "$REVIEWER_API_URL/review" \
        -H "Content-Type: application/json" \
        -d "{
          \"gitlab_url\": \"$CI_SERVER_URL\",
          \"project_id\": \"$CI_PROJECT_ID\",
          \"mr_id\": $CI_MERGE_REQUEST_IID,
          \"access_token\": \"$GITLAB_TOKEN\",
          \"review_type\": \"full\"
        }")
      
      SCORE=$(echo "$RESULT" | jq -r '.score')
      echo "代码质量评分: $SCORE/10.0"
      
      if [ "$(echo "$SCORE < 6.0" | bc)" -eq 1 ]; then
        echo "❌ 评分过低，需要改进"
        exit 1
      else
        echo "✅ 代码审查通过"
      fi
  only:
    - merge_requests
```

## 🎯 常见使用场景

### 1. 自动审查新MR

```bash
# 监听GitLab Webhook（如果实现）
# 或在CI/CD中自动触发
```

### 2. 批量审查历史MR

```python
import asyncio
import aiohttp

async def batch_review():
    mr_list = [123, 124, 125]  # MR ID列表
    
    async with aiohttp.ClientSession() as session:
        for mr_id in mr_list:
            # 审查逻辑
            pass

asyncio.run(batch_review())
```

### 3. 定制化审查规则

通过修改 `config/prompts.toml` 自定义审查标准：

```toml
[system_prompts.custom]
content = """
你是一个专门审查Python代码的专家。
重点关注：
1. PEP 8编码规范
2. 类型注解完整性
3. 单元测试覆盖度
"""
```

## 📊 监控和日志

### 1. 查看服务日志

```bash
# 查看API服务日志
docker-compose logs -f reviewer-api

# 查看所有服务日志
docker-compose logs -f
```

### 2. 监控面板（可选）

```bash
# 启动监控服务
./deployment/scripts/deploy.sh monitoring

# 访问监控
open http://localhost:3000  # Grafana
open http://localhost:9090  # Prometheus
```

## 🔒 安全配置

### 1. 生产环境SSL

```bash
# 替换自签名证书
cp your-cert.crt deployment/ssl/server.crt
cp your-key.key deployment/ssl/server.key

# 重启服务
./deployment/scripts/deploy.sh prod
```

### 2. API访问控制

在 `.env` 中配置：
```bash
RATE_LIMIT_PER_MINUTE=60
ALLOWED_HOSTS=your-domain.com
```

## 🛠️ 故障排除

### 1. 服务无法启动

```bash
# 检查日志
docker-compose logs reviewer-api

# 检查端口占用
netstat -tlnp | grep 8000

# 重新构建
docker-compose build --no-cache reviewer-api
```

### 2. API调用失败

```bash
# 检查网络连接
curl -v http://localhost:8000/health

# 检查环境变量
docker-compose exec reviewer-api env | grep -E "(OPENAI|GITLAB)"
```

### 3. 审查质量问题

1. 检查AI模型配置
2. 调整提示模板
3. 增加文件过滤规则

## 📞 获取帮助

- 查看完整文档：`docs/`
- 运行示例代码：`examples/`
- 查看API文档：http://localhost:8000/docs
- 检查配置：`config/settings.py`

## 🔄 升级指南

```bash
# 备份数据
docker-compose exec postgres pg_dump -U reviewer reviewer_db > backup.sql

# 更新代码
git pull origin main

# 重新部署
./deployment/scripts/deploy.sh prod
```

---

**🎉 恭喜！你的GitLab代码审查系统已经就绪！**

开始享受AI驱动的智能代码审查吧！