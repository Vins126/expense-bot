#!/bin/bash
set -e

REMOTE="expense-bot"
ZONE="us-central1-a"
PROJECT="botexcel-495709"

echo "📦 Creo archivio..."
tar --exclude='./.venv' --exclude='./__pycache__' --exclude='./*.pyc' \
    --exclude='./deploy.sh' \
    -czf /tmp/expense-bot.tar.gz -C "$(dirname "$0")" expense-bot

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
