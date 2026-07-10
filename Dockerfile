FROM node:20

WORKDIR /app

# 安装 Python
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

# 安装依赖
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install

# 复制代码
COPY src/ ./src/
COPY frontend/ ./frontend/

# 构建前端（生成静态文件）
RUN cd frontend && npm run build

# 暴露端口
EXPOSE 5173 9999

# 启动：Express 后端 + 静态文件托管
CMD ["node", "frontend/server.js"]
