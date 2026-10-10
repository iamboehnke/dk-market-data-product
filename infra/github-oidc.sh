#!/usr/bin/env bash
set -euo pipefail

REPO="iamboehnke/dk-market-data-product"
RG="group-dk-market-data-product"
APP_NAME="gh-kroner-og-renter"

APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
if [ -z "$APP_ID" ]; then
  APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
fi

if [ -z "$(az ad sp list --filter "appId eq '$APP_ID'" --query "[0].id" -o tsv)" ]; then
  az ad sp create --id "$APP_ID" -o none
fi

if [ -z "$(az ad app federated-credential list --id "$APP_ID" --query "[?name=='main-branch'].name" -o tsv)" ]; then
  az ad app federated-credential create --id "$APP_ID" --parameters "{
    \"name\": \"main-branch\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:${REPO}:ref:refs/heads/main\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }" -o none
fi

RG_ID=$(az group show -n "$RG" --query id -o tsv)
if [ -z "$(az role assignment list --assignee "$APP_ID" --scope "$RG_ID" --role Contributor --query "[0].id" -o tsv)" ]; then
  az role assignment create --assignee "$APP_ID" --role "Contributor" --scope "$RG_ID" -o none
fi

cat <<EOT

Tilføj i GitHub: Settings > Secrets and variables > Actions

  Secrets:
    AZURE_CLIENT_ID       = $APP_ID
    AZURE_TENANT_ID       = $(az account show --query tenantId -o tsv)
    AZURE_SUBSCRIPTION_ID = $(az account show --query id -o tsv)

  Variables:
    FUNCTION_APP_NAME     = func-kroner-og-renter-mb
    API_APP_NAME          = app-kroner-og-renter-mb
EOT
