#!/bin/bash
# 자동매매 서버 + 대시보드 통합 실행 스크립트
# Usage: ./start.sh        (둘 다 시작)
#        ./start.sh stop   (둘 다 종료)

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID_FILE="$PROJECT_DIR/.backend.pid"
FRONTEND_PID_FILE="$PROJECT_DIR/.frontend.pid"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

stop_all() {
    echo -e "${YELLOW}서버 종료 중...${NC}"

    if [ -f "$BACKEND_PID_FILE" ]; then
        PID=$(cat "$BACKEND_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            echo -e "${GREEN}  FastAPI 서버 종료 (PID $PID)${NC}"
        fi
        rm -f "$BACKEND_PID_FILE"
    fi

    if [ -f "$FRONTEND_PID_FILE" ]; then
        PID=$(cat "$FRONTEND_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            echo -e "${GREEN}  Next.js 대시보드 종료 (PID $PID)${NC}"
        fi
        rm -f "$FRONTEND_PID_FILE"
    fi

    # 혹시 남은 프로세스 정리
    lsof -ti:8088 | xargs kill -9 2>/dev/null
    lsof -ti:3007 | xargs kill -9 2>/dev/null

    echo -e "${GREEN}완료${NC}"
}

start_all() {
    # 기존 프로세스 정리
    stop_all 2>/dev/null

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  자동매매 시스템 시작${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""

    # 1. FastAPI 백엔드
    echo -e "${YELLOW}[1/2] FastAPI 서버 시작 (port 8088)...${NC}"
    cd "$PROJECT_DIR"
    source .venv/bin/activate
    nohup python run_server.py > logs/server.log 2>&1 &
    echo $! > "$BACKEND_PID_FILE"
    echo -e "${GREEN}  PID: $(cat $BACKEND_PID_FILE)${NC}"

    # 서버 준비 대기
    for i in $(seq 1 10); do
        if curl -s http://localhost:8088/api/system/health > /dev/null 2>&1; then
            echo -e "${GREEN}  FastAPI 서버 준비 완료${NC}"
            break
        fi
        sleep 1
    done

    # 2. Next.js 프론트엔드
    echo -e "${YELLOW}[2/2] Next.js 대시보드 시작 (port 3007)...${NC}"
    cd "$PROJECT_DIR/frontend"

    if [ ! -d "node_modules" ]; then
        echo -e "${YELLOW}  npm install 실행 중...${NC}"
        npm install > /dev/null 2>&1
    fi

    nohup npx next dev -p 3007 > "$PROJECT_DIR/logs/frontend.log" 2>&1 &
    echo $! > "$FRONTEND_PID_FILE"
    echo -e "${GREEN}  PID: $(cat $FRONTEND_PID_FILE)${NC}"

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  시작 완료!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo -e "  API 서버:   ${YELLOW}http://localhost:8088${NC}"
    echo -e "  API 문서:   ${YELLOW}http://localhost:8088/docs${NC}"
    echo -e "  대시보드:   ${YELLOW}http://localhost:3007${NC}"
    echo ""
    echo -e "  종료: ${RED}./start.sh stop${NC}"
    echo ""
}

# 로그 디렉토리 생성
mkdir -p "$PROJECT_DIR/logs"

case "${1:-start}" in
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 1
        start_all
        ;;
    *)
        start_all
        ;;
esac
