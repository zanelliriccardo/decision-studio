#!/usr/bin/env bash
#
# Deploy Decision Studio to Azure as a single Web App.
#
# Idempotent: every step checks whether the resource already exists, so a
# re-run after a failure continues rather than erroring out.
#
#   ./deploy-azure.sh                 # full deploy
#   ./deploy-azure.sh --redeploy      # rebuild the image and restart only
#
set -euo pipefail

# ── Settings ────────────────────────────────────────────────────────────────
RG="${RG:-decision-studio-rg}"
LOC="${LOC:-westeurope}"
PREFIX="${PREFIX:-decision-studio}"
PG_PASSWORD="${PG_PASSWORD:-}"
OPENAI_KEY="${OPENAI_KEY:-}"
BRAVE_KEY="${BRAVE_KEY:-}"

# Names must be globally unique, so they are derived from the subscription id:
# stable across re-runs, unlike $RANDOM, which would orphan resources.
SUB_HASH=$(az account show --query id -o tsv | tr -d '-' | cut -c1-6)
ACR="$(echo "${PREFIX}acr${SUB_HASH}" | tr -d "-_")"
PG="${PREFIX}-pg-${SUB_HASH}"
APP="${PREFIX}-${SUB_HASH}"
PLAN="${PREFIX}-plan"

info()  { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
fail()  { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

exists() { az "$@" >/dev/null 2>&1; }

# ── Redeploy shortcut ───────────────────────────────────────────────────────
if [[ "${1:-}" == "--redeploy" ]]; then
  info "Rebuilding the image"
  az acr build -r "$ACR" -t decision_studio:latest . -o none
  info "Restarting the app"
  az webapp restart -g "$RG" -n "$APP" -o none
  echo "Done. Migrations run on startup and are idempotent."
  echo "https://${APP}.azurewebsites.net"
  exit 0
fi

# ── Preflight ───────────────────────────────────────────────────────────────
[[ -n "$PG_PASSWORD" ]] || fail "Set PG_PASSWORD (a strong PostgreSQL password)."
[[ -n "$OPENAI_KEY"  ]] || fail "Set OPENAI_KEY."
command -v az >/dev/null || fail "Azure CLI not found."
az account show >/dev/null 2>&1 || fail "Run 'az login' first."

echo "Resource group : $RG ($LOC)"
echo "Registry       : $ACR"
echo "Database       : $PG"
echo "Web App        : $APP"

# ── 1. Resource group ───────────────────────────────────────────────────────
info "1/6  Resource group"
az group create -n "$RG" -l "$LOC" -o none

# ── 2. Container registry ───────────────────────────────────────────────────
info "2/6  Container registry"
if exists acr show -n "$ACR" -g "$RG"; then
  echo "already exists"
else
  az acr create -g "$RG" -n "$ACR" --sku Basic --admin-enabled true -o none
fi

# ── 3. PostgreSQL ───────────────────────────────────────────────────────────
# Flexible Server, not Cosmos DB for PostgreSQL: the latter is on a retirement
# path and Microsoft no longer recommends it for new projects.
info "3/6  PostgreSQL (this is the slow step, ~5 minutes)"
if exists postgres flexible-server show -g "$RG" -n "$PG"; then
  echo "already exists"
else
  az postgres flexible-server create \
    -g "$RG" -n "$PG" -l "$LOC" \
    --version 16 \
    --tier Burstable --sku-name Standard_B1ms \
    --storage-size 32 \
    --admin-user dsadmin \
    --admin-password "$PG_PASSWORD" \
    --database-name decision_studio \
    --public-access 0.0.0.0 \
    --yes -o none
fi

# pgvector is not on by default. Without it the first migration fails with a
# confusing "type vector does not exist", so it is allowlisted and created here.
info "      Enabling pgvector"
az postgres flexible-server parameter set \
  -g "$RG" -s "$PG" --name azure.extensions --value vector -o none

az postgres flexible-server execute \
  -n "$PG" -u dsadmin -p "$PG_PASSWORD" -d decision_studio \
  --querytext "CREATE EXTENSION IF NOT EXISTS vector;" -o none \
  || echo "  (could not run remotely — run it once by hand with psql)"

# ── 4. Image ────────────────────────────────────────────────────────────────
# Built in ACR rather than locally: no Docker needed, and no architecture
# mismatch when building on an Apple Silicon machine.
info "4/6  Building the image in ACR (~5 minutes)"
az acr build -r "$ACR" -t decision_studio:latest . -o none

# ── 5. Web App ──────────────────────────────────────────────────────────────
info "5/6  Web App"
if ! exists appservice plan show -g "$RG" -n "$PLAN"; then
  # B1 is the smallest tier that stays warm. Below it the container is evicted
  # between requests and every cold start re-runs migrations.
  az appservice plan create -g "$RG" -n "$PLAN" --is-linux --sku B1 -o none
fi

ACR_USER=$(az acr credential show -n "$ACR" --query username -o tsv)
ACR_PASS=$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv)

if exists webapp show -g "$RG" -n "$APP"; then
  echo "already exists"
else
  az webapp create -g "$RG" -p "$PLAN" -n "$APP" \
    --deployment-container-image-name "$ACR.azurecr.io/decision_studio:latest" -o none
fi

az webapp config container set -g "$RG" -n "$APP" \
  --docker-custom-image-name "$ACR.azurecr.io/decision_studio:latest" \
  --docker-registry-server-url "https://$ACR.azurecr.io" \
  --docker-registry-server-user "$ACR_USER" \
  --docker-registry-server-password "$ACR_PASS" -o none

# ── 6. Configuration ────────────────────────────────────────────────────────
info "6/6  Configuration"
PG_HOST="${PG}.postgres.database.azure.com"

# Three settings that are easy to miss and fail confusingly:
#   ?ssl=require   asyncpg spells it 'ssl', not libpq's 'sslmode'
#   WEBSITES_PORT  App Service ignores EXPOSE and would probe port 80
#   always-on      long generations otherwise get cut by the idle timeout
az webapp config appsettings set -g "$RG" -n "$APP" --settings \
  DATABASE_URL="postgresql+asyncpg://dsadmin:${PG_PASSWORD}@${PG_HOST}:5432/decision_studio?ssl=require" \
  LLM_PROVIDER=openai \
  LLM_MODEL=gpt-4o \
  OPENAI_API_KEY="$OPENAI_KEY" \
  EMBEDDING_API_KEY="$OPENAI_KEY" \
  BRAVE_SEARCH_API_KEY="$BRAVE_KEY" \
  CORS_ORIGINS="[\"https://${APP}.azurewebsites.net\"]" \
  WEBSITES_PORT=8000 \
  WEBSITES_CONTAINER_START_TIME_LIMIT=600 \
  -o none

az webapp config set -g "$RG" -n "$APP" \
  --always-on true --web-sockets-enabled true -o none

az webapp restart -g "$RG" -n "$APP" -o none

# ── Done ────────────────────────────────────────────────────────────────────
URL="https://${APP}.azurewebsites.net"
info "Deployed"
echo "  $URL"
echo
echo "First boot runs the migrations, so give it a couple of minutes."
echo
echo "  az webapp log tail -g $RG -n $APP     # watch alembic, then uvicorn"
echo "  curl $URL/health"
echo
echo "Redeploy after a change:  ./deploy-azure.sh --redeploy"
