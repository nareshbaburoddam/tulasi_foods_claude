# 1. Get the OIDC issuer URL for your cluster
OIDC_ISSUER=$(az aks show --name tulasi-foods-aks --resource-group Nextcloud --query oidcIssuerProfile.issuerUrl -o tsv)
echo "OIDC Issuer: $OIDC_ISSUER"

# 2. Get the existing Key Vault addon identity's full resource ID
IDENTITY_RESOURCE_ID=$(az aks show --name tulasi-foods-aks --resource-group Nextcloud --query addonProfiles.azureKeyvaultSecretsProvider.identity.resourceId -o tsv)
echo "Identity Resource ID: $IDENTITY_RESOURCE_ID"

# 3. Extract the identity name and its (auto-generated) resource group from that ID
IDENTITY_NAME=$(basename "$IDENTITY_RESOURCE_ID")
IDENTITY_RG=$(echo "$IDENTITY_RESOURCE_ID" | cut -d'/' -f5)
echo "Identity Name: $IDENTITY_NAME"
echo "Identity Resource Group: $IDENTITY_RG"

# 4. Create the federated credential -- this tells Azure AD to trust tokens
#    from the specific Kubernetes ServiceAccount below, no node/VM involved at all.
az identity federated-credential create \
  --name tulasi-backend-federated-cred \
  --identity-name "$IDENTITY_NAME" \
  --resource-group "$IDENTITY_RG" \
  --issuer "$OIDC_ISSUER" \
  --subject "system:serviceaccount:tulasi-foods:tulasi-backend-sa" \
  --audience api://AzureADTokenExchange

# 5. Print the client ID -- you'll need this for the ServiceAccount annotation
az aks show --name tulasi-foods-aks --resource-group Nextcloud --query addonProfiles.azureKeyvaultSecretsProvider.identity.clientId -o tsv
