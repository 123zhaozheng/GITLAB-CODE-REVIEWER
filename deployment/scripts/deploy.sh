#!/bin/bash
# GitLab Code Reviewer 快速部署脚本
# 支持开发和生产环境部署

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

# 检查依赖
check_dependencies() {
    log_info "检查系统依赖..."
    
    # 检查Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker未安装，请先安装Docker"
        exit 1
    fi
    
    # 检查Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose未安装，请先安装Docker Compose"
        exit 1
    fi
    
    log_info "依赖检查完成 ✓"
}

# 环境配置
setup_environment() {
    log_info "配置环境变量..."
    
    # 如果.env文件不存在，从示例创建
    if [ ! -f .env ]; then
        log_warn ".env文件不存在，从.env.example创建"
        cp .env.example .env
        
        log_warn "请编辑.env文件，设置必要的API密钥："
        log_warn "- OPENAI_API_KEY: OpenAI API密钥"
        log_warn "- DEFAULT_AI_MODEL: 默认AI模型"
        
        read -p "是否现在编辑.env文件? (y/n): " edit_env
        if [ "$edit_env" = "y" ] || [ "$edit_env" = "Y" ]; then
            ${EDITOR:-nano} .env
        fi
    fi
    
    log_info "环境配置完成 ✓"
}

# 创建必要目录
create_directories() {
    log_info "创建必要目录..."
    
    mkdir -p logs/nginx
    mkdir -p deployment/ssl
    
    # 创建自签名SSL证书（开发环境）
    if [ ! -f deployment/ssl/server.crt ]; then
        log_info "生成自签名SSL证书（仅用于开发）..."
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout deployment/ssl/server.key \
            -out deployment/ssl/server.crt \
            -subj "/C=CN/ST=Beijing/L=Beijing/O=Dev/CN=localhost" \
            2>/dev/null || log_warn "SSL证书生成失败，将使用HTTP"
    fi
    
    log_info "目录创建完成 ✓"
}

# 部署开发环境
deploy_development() {
    log_info "部署开发环境..."
    
    # 停止现有容器
    docker-compose down
    
    # 构建并启动服务
    docker-compose up --build -d reviewer-api redis postgres
    
    # 等待服务启动
    log_info "等待服务启动..."
    sleep 30
    
    # 健康检查
    if curl -f http://localhost:8000/health &>/dev/null; then
        log_info "开发环境部署成功！"
        log_info "API文档: http://localhost:8000/docs"
        log_info "健康检查: http://localhost:8000/health"
    else
        log_error "服务启动失败，请检查日志"
        docker-compose logs reviewer-api
        exit 1
    fi
}

# 部署生产环境
deploy_production() {
    log_info "部署生产环境..."
    
    # 停止现有容器
    docker-compose --profile production down
    
    # 构建并启动所有服务
    docker-compose --profile production up --build -d
    
    # 等待服务启动
    log_info "等待服务启动..."
    sleep 60
    
    # 健康检查
    if curl -f http://localhost/health &>/dev/null; then
        log_info "生产环境部署成功！"
        log_info "API访问: https://localhost"
        log_info "API文档: https://localhost/docs"
        log_info "监控面板: http://localhost:3000 (如果启用了监控)"
    else
        log_error "服务启动失败，请检查日志"
        docker-compose --profile production logs
        exit 1
    fi
}

# 部署监控服务
deploy_monitoring() {
    log_info "部署监控服务..."
    
    docker-compose --profile monitoring up -d prometheus grafana
    
    log_info "监控服务部署完成！"
    log_info "Prometheus: http://localhost:9090"
    log_info "Grafana: http://localhost:3000 (admin/admin)"
}

# 查看日志
view_logs() {
    local service=${1:-reviewer-api}
    log_info "查看 $service 服务日志..."
    docker-compose logs -f $service
}

# 停止服务
stop_services() {
    log_info "停止所有服务..."
    docker-compose --profile production --profile monitoring down
    log_info "服务已停止"
}

# 清理环境
cleanup() {
    log_warn "这将删除所有容器、镜像和数据卷，确认吗? (y/N)"
    read -r confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        log_info "清理环境..."
        docker-compose --profile production --profile monitoring down -v --rmi all
        docker system prune -f
        log_info "清理完成"
    else
        log_info "清理已取消"
    fi
}

# 显示帮助
show_help() {
    echo "GitLab Code Reviewer 部署脚本"
    echo ""
    echo "用法: $0 [命令]"
    echo ""
    echo "命令:"
    echo "  dev         部署开发环境"
    echo "  prod        部署生产环境"
    echo "  monitoring  部署监控服务"
    echo "  logs [服务] 查看服务日志"
    echo "  stop        停止所有服务"
    echo "  cleanup     清理环境（危险操作）"
    echo "  help        显示此帮助"
    echo ""
    echo "示例:"
    echo "  $0 dev                  # 部署开发环境"
    echo "  $0 prod                 # 部署生产环境"
    echo "  $0 logs reviewer-api    # 查看API服务日志"
    echo ""
}

# 主函数
main() {
    case "${1:-help}" in
        "dev"|"development")
            check_dependencies
            setup_environment
            create_directories
            deploy_development
            ;;
        "prod"|"production")
            check_dependencies
            setup_environment
            create_directories
            deploy_production
            ;;
        "monitoring")
            deploy_monitoring
            ;;
        "logs")
            view_logs $2
            ;;
        "stop")
            stop_services
            ;;
        "cleanup")
            cleanup
            ;;
        "help"|*)
            show_help
            ;;
    esac
}

# 执行主函数
main "$@"