#!/usr/bin/env bash
# Lader GitHub Actions logge ind i Azure med OIDC (workload identity federation).
# Ingen adgangskode eller nøgle gemmes i GitHub, kun tre id'er, som ikke er hemmelige.
set -euo pipefail

REPO="iamboehnke/azure-kroner-og-renter"
RG="rg-kroner-og-renter"

APP_ID=$(az ad app create --display-name "gh-kroner-og-renter" --query appId -o tsv)
az ad sp create --id "$APP_ID" -o none
az ad app federated-credential create --id "$APP_ID" --parameters "{
  \"name\": \"main-branch\",
  \"issuer\": \"https://token.actions.githubusercontent.com\",
  \"subject\": \"repo:${REPO}:ref:refs/heads/main\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}" -o none

# Kun adgang til projektets egen ressourcegruppe
RG_ID=$(az group show -n "$RG" --query id -o tsv)
az role assignment create --assignee "$APP_ID" --role "Contributor" --scope "$RG_ID" -o none

cat <<EOF

Tilføj i GitHub: Settings > Secrets and variables > Actions

  Secrets:
    AZURE_CLIENT_ID       = $APP_ID
    AZURE_TENANT_ID       = $(az account show --query tenantId -o tsv)
    AZURE_SUBSCRIPTION_ID = $(az account show --query id -o tsv)

  Variables:
    FUNCTION_APP_NAME     = <navnet på din function app>
    API_APP_NAME          = <navnet på din Django-app>
EOF
