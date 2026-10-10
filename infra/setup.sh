#!/usr/bin/env bash
# Opretter alle Azure-ressourcer til kroner-og-renter med Azure CLI.
# Kør trin for trin i Azure Cloud Shell (Bash) eller lokalt efter `az login`.
# Databasen oprettes i portalen (se guiden), fordi gratis-tilbuddet vælges der.
set -euo pipefail

# Ret disse fire, før du kører
LOCATION="swedencentral"                 # samme region som din eksisterende gratis SQL-database
INITIALS="mb"                          # gør globale navne unikke
SQL_SERVER="sql-dk-market-data-mb"   # navnet på din SQL-server (uden .database.windows.net)
SQL_RG="group-dk-market-data-product"    # ressourcegruppen, serveren ligger i

RG="group-dk-market-data-product"
LAKE="stkrlake${INITIALS}$RANDOM"      # datasø, privat (ADLS Gen2)
PUB="stkrpub${INITIALS}$RANDOM"        # offentlig, kun ét container med færdige JSON-filer
FUNCSTORE="stkrfunc${INITIALS}$RANDOM" # funktionsappens egen lagerkonto
FUNC="func-kroner-og-renter-${INITIALS}"
PLAN="plan-kroner-og-renter"
API="app-kroner-og-renter-${INITIALS}"
SQL_DB="kroner-og-renter"

echo "== Ressourcegruppe"
az group create -n "$RG" -l "$LOCATION" -o none

echo "== Datasø (privat, hierarkisk navnerum)"
az storage account create -n "$LAKE" -g "$RG" -l "$LOCATION" --sku Standard_LRS --kind StorageV2 \
  --hns true --min-tls-version TLS1_2 --allow-blob-public-access false -o none
for c in bronze silver gold; do
  az storage container-rm create --storage-account "$LAKE" -g "$RG" -n "$c" -o none
done

echo "== Offentlig konto til færdige data (anonym læsning af ét container)"
az storage account create -n "$PUB" -g "$RG" -l "$LOCATION" --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access true -o none
az storage container-rm create --storage-account "$PUB" -g "$RG" -n public --public-access blob -o none
PUB_KEY=$(az storage account keys list -n "$PUB" -g "$RG" --query "[0].value" -o tsv)
az storage cors add --account-name "$PUB" --account-key "$PUB_KEY" --services b --methods GET HEAD OPTIONS \
  --origins "https://mikkelbohnke.com" "https://www.mikkelbohnke.com" "http://localhost:8000" \
  --allowed-headers "*" --exposed-headers "*" --max-age 3600

echo "== Function app (Flex Consumption, Python 3.12)"
az storage account create -n "$FUNCSTORE" -g "$RG" -l "$LOCATION" --sku Standard_LRS -o none
az functionapp create -g "$RG" -n "$FUNC" --storage-account "$FUNCSTORE" \
  --flexconsumption-location "$LOCATION" --runtime python --runtime-version 3.12 -o none
PRINCIPAL=$(az functionapp identity assign -g "$RG" -n "$FUNC" --query principalId -o tsv)

echo "== Rettigheder til funktionens managed identity"
for ACCOUNT in "$LAKE" "$PUB"; do
  SCOPE=$(az storage account show -n "$ACCOUNT" -g "$RG" --query id -o tsv)
  az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
    --role "Storage Blob Data Contributor" --scope "$SCOPE" -o none
done

echo "== App settings (ingen hemmeligheder, kun adresser)"
az functionapp config appsettings set -g "$RG" -n "$FUNC" -o none --settings \
  LAKE_ACCOUNT_URL="https://$LAKE.blob.core.windows.net" \
  PUBLIC_ACCOUNT_URL="https://$PUB.blob.core.windows.net" \
  PUBLIC_CONTAINER="public" PUBLIC_PREFIX="kroner-og-renter/v1" \
  SQL_SERVER="$SQL_SERVER.database.windows.net" SQL_DATABASE="$SQL_DB" \
  SQL_AUTHENTICATION="ActiveDirectoryMSI" LOOKBACK_PERIODS="10" BACKFILL_PERIODS="500"

echo "== SQL-serveren: Entra-admin og adgang for Azure-tjenester"
ME=$(az ad signed-in-user show --query id -o tsv)
ME_NAME=$(az ad signed-in-user show --query userPrincipalName -o tsv)
az sql server ad-admin create -g "$SQL_RG" -s "$SQL_SERVER" --display-name "$ME_NAME" --object-id "$ME" -o none
az sql server firewall-rule create -g "$SQL_RG" -s "$SQL_SERVER" -n AllowAzureServices \
  --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 -o none || true

echo "== Django på App Service F1 (gratis)"
az appservice plan create -g "$RG" -n "$PLAN" --is-linux --sku F1 -l "$LOCATION" -o none
az webapp create -g "$RG" -p "$PLAN" -n "$API" --runtime "PYTHON:3.12" -o none
az webapp config set -g "$RG" -n "$API" -o none \
  --startup-file "gunicorn --bind=0.0.0.0 --timeout 120 --workers 2 config.wsgi"
az webapp config appsettings set -g "$RG" -n "$API" -o none --settings \
  SCM_DO_BUILD_DURING_DEPLOYMENT="true" \
  DJANGO_SECRET_KEY="$(openssl rand -hex 32)" \
  DJANGO_ALLOWED_HOSTS="$API.azurewebsites.net" \
  DATA_BASE_URL="https://$PUB.blob.core.windows.net/public/kroner-og-renter/v1" \
  CORS_ALLOWED_ORIGINS="https://mikkelbohnke.com,https://www.mikkelbohnke.com" \
  GITHUB_REPO_URL="https://github.com/iamboehnke/dk-market-data-product"

cat <<EOF

Færdig. Gem disse værdier:
  Ressourcegruppe : $RG
  Datasø          : $LAKE
  Offentlig konto : $PUB
  Function app    : $FUNC
  Django-app      : https://$API.azurewebsites.net
  Widgettens data : https://$PUB.blob.core.windows.net/public/kroner-og-renter/v1/latest.json

Næste trin: opret databasen $SQL_DB i portalen med gratis-tilbuddet, kør sql/001_schema.sql,
og kør sql/002_access.sql med navnet $FUNC. Opsæt derefter GitHub OIDC med infra/github-oidc.sh.
EOF
