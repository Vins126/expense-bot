#!/bin/bash
set -e

REMOTE="expense-bot"
ZONE="us-central1-a"
PROJECT="botexcel-495709"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

echo "📦 Creo archivio..."
tar --exclude='expense-bot/.venv' --exclude='expense-bot/__pycache__' \
    --exclude='expense-bot/*.pyc' --exclude='expense-bot/deploy.sh' \
    -czf /tmp/expense-bot.tar.gz -C "$PARENT_DIR" expense-bot

echo "⬆️  Carico sulla VM..."
gcloud compute scp /tmp/expense-bot.tar.gz "$REMOTE":~ \
    --zone="$ZONE" --project="$PROJECT"

echo "🔄 Aggiorno ed riavvio il bot..."
gcloud compute ssh "$REMOTE" \
    --zone="$ZONE" --project="$PROJECT" \
    --command="
        tar -xzf expense-bot.tar.gz &&
        rm -f ~/expense-bot/deploy.sh &&
        sudo systemctl restart expense-bot &&
        sleep 2 &&
        sudo systemctl status expense-bot --no-pager | head -5
    "

echo "✅ Deploy completato"
