#!/bin/bash
# Village Planning Agent - Server Deployment Script
# Server: 114.132.186.148
# Ports: Frontend=3011, Backend=8011
# Run: sudo bash deploy.sh

set -e

echo "============================================"
echo "Village Planning Agent - Deployment Script"
echo "============================================"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
PROJECT_DIR="/opt/village-planning"
SERVER_IP="114.132.186.148"
FRONTEND_PORT="3011"
BACKEND_PORT="8011"

# Step 1: Check Docker
echo -e "${YELLOW}[Step 1] Checking Docker...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker not installed. Installing...${NC}"
    apt-get update
    apt-get install -y docker.io docker-compose-plugin
fi
docker --version
echo -e "${GREEN}Docker OK${NC}"

# Step 2: Start Docker service
echo -e "${YELLOW}[Step 2] Starting Docker service...${NC}"
systemctl start docker
systemctl enable docker
echo -e "${GREEN}Docker service started${NC}"

# Step 3: Create project directory
echo -e "${YELLOW}[Step 3] Creating project directory...${NC}"
mkdir -p $PROJECT_DIR
mkdir -p $PROJECT_DIR/data
mkdir -p $PROJECT_DIR/logs
mkdir -p $PROJECT_DIR/results
mkdir -p $PROJECT_DIR/knowledge_base
mkdir -p $PROJECT_DIR/models
echo -e "${GREEN}Directories created${NC}"

# Step 4: Check if code is present
echo -e "${YELLOW}[Step 4] Checking project files...${NC}"
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
    echo -e "${RED}ERROR: Project files not found in $PROJECT_DIR${NC}"
    echo "Please upload the project files first:"
    echo "  scp village-planning.zip zby@114.132.186.148:/opt/"
    echo "  unzip /opt/village-planning.zip -d $PROJECT_DIR"
    exit 1
fi
echo -e "${GREEN}Project files found${NC}"

# Step 5: Check .env file
echo -e "${YELLOW}[Step 5] Checking environment configuration...${NC}"
if [ ! -f "$PROJECT_DIR/.env" ]; then
    if [ -f "$PROJECT_DIR/.env.production" ]; then
        cp $PROJECT_DIR/.env.production $PROJECT_DIR/.env
        echo -e "${GREEN}.env created from .env.production${NC}"
    else
        echo -e "${RED}ERROR: .env file not found${NC}"
        echo "Please create .env file with required API keys"
        exit 1
    fi
fi
echo -e "${GREEN}Environment configured${NC}"

# Step 6: Open firewall ports
echo -e "${YELLOW}[Step 6] Configuring firewall...${NC}"
if command -v ufw &> /dev/null; then
    ufw allow $FRONTEND_PORT/tcp
    ufw allow $BACKEND_PORT/tcp
    echo -e "${GREEN}Firewall ports opened: $FRONTEND_PORT, $BACKEND_PORT${NC}"
else
    echo -e "${YELLOW}ufw not available, skipping firewall config${NC}"
fi

# Step 7: Build Docker images
echo -e "${YELLOW}[Step 7] Building Docker images (5-15 minutes)...${NC}"
cd $PROJECT_DIR
docker compose build --no-cache
echo -e "${GREEN}Docker images built${NC}"

# Step 8: Start services
echo -e "${YELLOW}[Step 8] Starting services...${NC}"
docker compose up -d
echo -e "${GREEN}Services started${NC}"

# Step 9: Wait for health check
echo -e "${YELLOW}[Step 9] Waiting for services to be healthy...${NC}"
sleep 30

# Step 10: Verify deployment
echo -e "${YELLOW}[Step 10] Verifying deployment...${NC}"
docker compose ps

# Health check
echo ""
echo -e "${YELLOW}Health check:${NC}"
curl -f http://localhost:$BACKEND_PORT/health && echo -e "${GREEN}Backend OK${NC}" || echo -e "${RED}Backend FAILED${NC}"
curl -f http://localhost:$FRONTEND_PORT && echo -e "${GREEN}Frontend OK${NC}" || echo -e "${RED}Frontend FAILED${NC}"

# Final message
echo ""
echo "============================================"
echo -e "${GREEN}Deployment Complete!${NC}"
echo "============================================"
echo ""
echo "Access URLs:"
echo "  Frontend:    http://$SERVER_IP:$FRONTEND_PORT"
echo "  Backend API: http://$SERVER_IP:$BACKEND_PORT"
echo "  API Docs:    http://$SERVER_IP:$BACKEND_PORT/docs"
echo "  Health:      http://$SERVER_IP:$BACKEND_PORT/health"
echo ""
echo "Useful commands:"
echo "  View logs:   docker compose logs -f"
echo "  Restart:     docker compose restart"
echo "  Stop:        docker compose down"
echo "============================================"