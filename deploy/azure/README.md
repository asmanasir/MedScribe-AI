# Azure Deployment — MedScribe AI

## Architecture

```
Azure Norway East (norwayeast)
├── Resource Group: rg-medscribe-prod
│   ├── AKS Cluster (Kubernetes)
│   │   ├── medscribe-api (FastAPI)
│   │   ├── medscribe-whisper (STT)
│   │   └── medscribe-ollama (LLM)
│   ├── Azure Database for PostgreSQL
│   ├── Azure Key Vault (HSM)
│   ├── Azure Container Registry
│   ├── Azure VNet (private network)
│   └── Azure Monitor (logging)
```

## Deployment Steps

### 1. Create Azure resources
```bash
az group create --name rg-medscribe-prod --location norwayeast
az aks create --name aks-medscribe --resource-group rg-medscribe-prod \
  --node-count 2 --node-vm-size Standard_NC4as_T4_v3  # GPU nodes for AI
az postgres flexible-server create --name pg-medscribe \
  --resource-group rg-medscribe-prod --location norwayeast
az keyvault create --name kv-medscribe \
  --resource-group rg-medscribe-prod --location norwayeast
```

### 2. Build and push containers
```bash
az acr create --name crmedscribe --resource-group rg-medscribe-prod --sku Standard
az acr build --registry crmedscribe --image medscribe-api:latest .
```

### 3. Deploy to AKS
```bash
kubectl apply -f deploy/azure/k8s/
```
