# AAS Weaviate MCP Server

MCP (Model Context Protocol) server for querying AAS documentation in Weaviate with metadata filtering.

## Features

- **search_documents**: Semantic search with required `submodel_id` and optional `idShortPath` filtering
- **list_metadata_values**: Discover available metadata values

## Installation

```bash
pip install -e .
```

## Usage

### Local (stdio transport)

```bash
export WEAVIATE_HOST=localhost
export WEAVIATE_PORT=8070
python -m aas_weaviate_mcp.server
```

### Docker

```bash
docker build -t aas-weaviate-mcp:latest .
docker run -p 8000:8000 \
  -e WEAVIATE_HOST=weaviate \
  -e WEAVIATE_PORT=8080 \
  aas-weaviate-mcp:latest
```

### In docker-compose

```yaml
aas-weaviate-mcp:
  image: aas-weaviate-mcp:latest
  build: ./aas-weaviate-mcp
  ports:
    - "8113:8000"
  environment:
    - WEAVIATE_HOST=weaviate
    - WEAVIATE_PORT=8080
  networks:
    - embedding
```

## MCP Client Configuration

### Claude Desktop / Cline

```json
{
  "mcpServers": {
    "aas-weaviate": {
      "url": "http://localhost:8113",
      "transport": "http"
    }
  }
}
```

### Flowise

Add as Custom MCP Tool:
- URL: `http://localhost:8113` (or `http://aas-weaviate-mcp:8000` from within Docker)
- Transport: HTTP

## Tools

### search_documents

```python
search_documents(
    query="temperature specifications",
    submodel_id="http://aas.dfki.de/ids/sm/identification_10000000",
    idShortPath="Documentation",  # optional
    limit=5
)
```

Returns:
```json
{
  "results": [
    {
      "text": "Chunk content...",
      "metadata": {
        "submodel_id": "http://...",
        "idShortPath": "Documentation",
        "source": "/aasx/MiR100-User-guide.pdf"
      },
      "distance": 0.123
    }
  ],
  "total": 5,
  "query": "temperature specifications",
  "filters_applied": {
    "submodel_id": "http://...",
    "idShortPath": "Documentation"
  }
}
```

### list_metadata_values

```python
list_metadata_values(
    field="submodel_id",
    limit=20
)
```

## Environment Variables

### Weaviate Connection

| Variable | Description | Default |
|----------|-------------|----------|
| `WEAVIATE_SCHEME` | http or https | `http` |
| `WEAVIATE_HOST` | Weaviate host | `localhost` |
| `WEAVIATE_PORT` | Weaviate HTTP port | `8080` |
| `WEAVIATE_GRPC_PORT` | Weaviate gRPC port | `50051` |
| `WEAVIATE_COLLECTION` | Collection name | `Docs` |

### Embedding Model (required)

| Variable | Description | Example |
|----------|-------------|----------|
| `EMBEDDING_MODEL` | Model in `provider:model` format | `openai:text-embedding-3-small` |

Supported providers: `openai`, `google_vertexai`, `ollama`, `cohere`, `mistralai`, `huggingface`, `bedrock`, `azure_openai`

### API Keys (depending on provider)

| Variable | Provider | Required |
|----------|----------|----------|
| `OPENAI_API_KEY` | OpenAI | Yes for `openai:*` |
| `GOOGLE_API_KEY` | Google/Gemini | Yes for `google_genai:*` |
| `VOYAGE_API_KEY` | Voyage AI (Anthropic-recommended) | Yes for `voyageai:*` |
| `OLLAMA_HOST` | Ollama (local) | No key needed, default: `http://localhost:11434` |

### Example Configurations

**OpenAI (cloud):**
```bash
EMBEDDING_MODEL=openai:text-embedding-3-small
OPENAI_API_KEY=sk-...
```

**Voyage AI (Anthropic-recommended):**
```bash
EMBEDDING_MODEL=voyageai:voyage-3
VOYAGE_API_KEY=pa-...
```

**Ollama (local, no API costs):**
```bash
EMBEDDING_MODEL=ollama:nomic-embed-text
OLLAMA_HOST=http://localhost:11434
```

**Google Gemini:**
```bash
EMBEDDING_MODEL=google_genai:text-embedding-004
GOOGLE_API_KEY=...
```

## License

MIT

---

## TODO: Embedding-Architektur

### Problem (Stand Januar 2026)

Der MCP-Server nutzt `near_text()` für semantische Suche. Das erfordert einen konfigurierten Vectorizer in Weaviate. Aktuell wird die Collection aber mit `self_provided` Vektoren befüllt (embedding-service nutzt Gemini), d.h. Weaviate hat keinen eigenen Vectorizer.

**Fehlermeldung:**
```
vectorize params: could not vectorize input for collection Docs with search-type nearText.
Make sure a vectorizer module is configured for this collection.
```

### Ursache

| Komponente | Embedding-Modell | Vektordimension |
|------------|------------------|------------------|
| embedding-service | Gemini text-embedding-004 | 768 |
| Flowise (Test) | OpenAI text-embedding-3-small | 1536 |
| MCP-Server | keins (erwartet Weaviate-Vectorizer) | - |

→ Inkompatible Vektorräume, `near_text()` funktioniert nicht ohne Vectorizer.

### Lösung: Konfigurierbarer Embedding-Provider

Für Industrie 4.0 / souveräne KI muss das Setup unabhängig von externen APIs funktionieren können. Ziel: **Ein konfigurierbarer Embedding-Client**, der sowohl beim Ingest als auch bei Queries genutzt wird.

**Architektur:**
```
┌─────────────────────────────────────────────────────┐
│           Embedding Provider (konfigurierbar)       │
├─────────────────────────────────────────────────────┤
│  EMBEDDING_PROVIDER=openai|gemini|local|custom      │
│  EMBEDDING_MODEL=text-embedding-3-small|...         │
│  EMBEDDING_API_KEY=xxx (optional bei local)         │
│  EMBEDDING_BASE_URL=http://... (für custom/local)   │
└─────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
   ┌──────────┐                  ┌──────────────┐
   │  Ingest  │                  │  MCP Query   │
   │ (embed-  │                  │  (near_     │
   │  ding-   │                  │   vector)   │
   │ service) │                  │              │
   └──────────┘                  └──────────────┘
         │                              │
         └──────────┬───────────────────┘
                    ▼
              ┌──────────┐
              │ Weaviate │ (nur Vektorspeicher,
              │          │  kein Vectorizer)
              └──────────┘
```

### Umgebungsvariablen (geplant)

```bash
# Provider: openai, gemini, ollama, tei, custom
EMBEDDING_PROVIDER=openai

# Modellname (abhängig vom Provider)
EMBEDDING_MODEL=text-embedding-3-small

# API Key (nicht nötig bei local/ollama)
EMBEDDING_API_KEY=sk-...

# Base URL für custom/local Provider
EMBEDDING_BASE_URL=http://localhost:11434
```

### Lokale Embedding-Optionen für Produktion

| Option | Beschreibung | Docker-ready |
|--------|--------------|---------------|
| Ollama | `nomic-embed-text`, `mxbai-embed-large` | ✓ |
| TEI (HuggingFace) | Text Embeddings Inference, performant | ✓ |
| vLLM | Mit Embedding-Modellen | ✓ |
| Firmenintern | OpenAI-kompatibles API | - |

### Implementierungs-Tasks

- [x] **MCP-Server** anpassen:
  - `near_text()` → `near_vector()` 
  - Query-Text erst embedden, dann mit Vektor suchen
  - Konfigurierbares Embedding-Modell via `EMBEDDING_MODEL` env var
  - Nutzt LangChain `init_embeddings()` für Provider-Abstraktion
- [x] **Docker-Compose** erweitern:
  - Embedding-Modell und API-Keys als Umgebungsvariablen
- [x] **Dokumentation** für Wechsel auf lokales Modell
- [ ] **embedding-service** auf LangChain `init_embeddings()` umstellen (für Konsistenz)
- [ ] **Collection-Schema** vereinheitlichen:
  - Property-Namen: `submodel_id` vs `submodelId` angleichen
  - `idShortPath` vs `idShort` klären
- [ ] **Optionaler Ollama Container** in docker-compose für komplett lokales Setup