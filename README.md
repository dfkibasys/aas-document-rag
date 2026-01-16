# AAS Document RAG - Kafka Integration

Kafka Connect stack for AAS event processing with FileStreamSink. Events from Asset Administration Shells are streamed to a log file for processing by a Python-based RAG system.

## Quick Start

**Start the stack:**
```bash
docker-compose up --detach --build
```

**Stop the stack:**
```bash
docker-compose down
```

**Stop and remove volumes (full cleanup):**
```bash
docker-compose down --volumes
```

## Services

- **AAS Environment:** http://localhost:8081 (loads MiR100 AASX files with PDFs)
- **AAS GUI:** http://localhost:8099
- **Kafka AKHQ:** http://localhost:8086 (Kafka management UI)
- **Kafka Connect RAG:** http://localhost:8085
- **MongoDB:** Internal (AAS storage backend)
- **Neo4j:** http://localhost:7474 (Graph database for AAS metadata)
- **Neo4j MCP Server:** http://localhost:8112/api/mcp/ (MCP interface for Neo4j queries)
- **MCP Inspector:** http://localhost:6274 (MCP debugging interface)
- **Embedding Service:** http://localhost:8000 (Receives events, processes PDFs)
- **Weaviate:** http://localhost:8070 (Vector database for embeddings)
- **Flowise:** http://localhost:3000 (AI agent builder)

**Events are sent to:** `embedding-service` via HTTP Sink Connector

## Event Flow

```
AAS Environment (CREATE/UPDATE/DELETE)
  → Kafka Topics (aas-events, submodel-events)
  → Kafka Connect HTTP Sink
  → Embedding Service (Flask)
  → PDF extraction & chunking
  → Weaviate (Vector DB with AAS metadata)
```

## Working with Events

**View embedding service logs:**
```bash
docker logs -f embedding-service
```

**View specific service logs:**
```bash
docker-compose logs -f kafka-connect-rag
docker-compose logs -f aas-environment
docker-compose logs -f kafka
```

**Example events received by embedding-service:**
- Submodel metadata (Identification, Signals, TechnicalData, etc.)
- PDF references: `"value": "/aasx/MiR100-User-guide.pdf"`
- Event types: `SM_CREATED`, `SM_UPDATED`, `AAS_CREATED`, etc.

## Kafka Connect Configuration

**Current setup:** Single events (`max.poll.records=1`)
- Each event processed individually
- Good for debugging and PoC
- Easy to trace which event causes issues

**For batching** (edit `kafka-connect/config/http-sink-connector.json`):
```json
"consumer.override.max.poll.records": "100"
```

## Connector Management

**Check connector status:**
```bash
curl http://localhost:8085/connectors/AasEventsHttpStreamSink/status
```

**Restart connector:**
```bash
curl -X POST http://localhost:8085/connectors/AasEventsHttpStreamSink/restart
```

**List all connectors:**
```bash
curl http://localhost:8085/connectors
```

## AASX Files and PDFs

The stack loads AASX files from `./aasx/` directory:
- Files contain Asset Administration Shells with **embedded PDFs**
- PDFs referenced in Identification submodels (Documentation field)
- Example event shows: `"value": "/aasx/MiR100-User-guide.pdf"` (path inside container)

**Important for PDF extraction:**
- PDFs are **embedded inside the AASX files** but accessible via BaSyx REST API
- Extract PDF path from event: `"value": "/aasx/MiR100-User-guide.pdf"` or from SubmodelElement `"idShort": "Documentation"`
- Download PDF via BaSyx API:
  ```bash
  # Get SubmodelElement metadata
  GET http://localhost:8081/submodels/{base64_submodel_id}/submodel-elements/Documentation
  
  # Download PDF binary
  GET http://localhost:8081/submodels/{base64_submodel_id}/submodel-elements/Documentation/attachment
  ```
- Pass BaSyx base URL as environment variable to your Flask service
- Note: A copy of the PDF is available in `./doc/` for local testing of your Python code (without running the full stack)

**Add new AASX files:** Place them in `./aasx/` and restart `aas-environment`:
```bash
docker-compose restart aas-environment
```

## Neo4j Knowledge Graph and MCP Server

The stack includes Neo4j for storing AAS metadata as a knowledge graph and an MCP (Model Context Protocol) server for querying it.

**Neo4j Browser:** http://localhost:7474
- Explore the AAS knowledge graph visually
- Run Cypher queries directly
- No authentication required (development setup)

**MCP Inspector:** 
```
http://localhost:6274/?transport=http&serverUrl=http://localhost:8112/api/mcp/&MCP_PROXY_AUTH_TOKEN=dev-stack-token-12345

http://localhost:6274/?transport=http&serverUrl=http://localhost:8113/mcp/&MCP_PROXY_AUTH_TOKEN=dev-stack-token-12345
```
- Debug and test MCP server tools
- Inspect available Neo4j query capabilities
- Transport type: HTTP (displays as "Streamable HTTP" in UI)

**Example MCP Query Workflow:**
1. Open MCP Inspector at the URL above
2. Use "query_neo4j" tool to find AAS ID: `MATCH (aas:Shell {idShort: 'MiR100'}) RETURN aas.id`
3. Use returned ID to filter vector database queries in Flowise agent

## Next Steps (TODOs)

### Phase 1: RAG Pipeline (Bachelor Thesis Focus)
- [x] Replace FileStreamSink with HTTP Sink Connector ✅ DONE
- [x] Implement Flask service to receive events via HTTP ✅ DONE
- [ ] Extract PDF paths from events (e.g., `/aasx/MiR100-User-guide.pdf`)
- [ ] Download PDFs from BaSyx API (`/submodels/.../submodel-elements/Documentation/attachment`)
- [ ] Chunk PDFs using docling
- [ ] Generate embeddings for chunks
- [ ] Store embeddings in Weaviate with AAS metadata:
  ```json
  {
    "text": "chunk content",
    "metadata": {
      "aas_id": "http://aas.dfki.de/ids/aas/mir100_type",
      "submodel_id": "http://aas.dfki.de/ids/sm/identification_10000000",
      "source": "/aasx/MiR100-User-guide.pdf"
    }
  }
  ```

### Phase 2: Agent Interface with Flowise
- [x] Setup Neo4j and MCP Server ✅ DONE
- [x] Setup Weaviate vector database ✅ DONE
- [ ] Setup Flowise agent builder
- [ ] Configure Flowise agent with two data sources:
  - **Neo4j MCP Server** (at http://localhost:8112/api/mcp/): Query AAS knowledge graph for metadata
  - **Weaviate Retriever** (Flowise built-in): Search documents with metadata filtering
- [ ] Implement two-stage retrieval workflow:
  1. Query Neo4j via MCP to get AAS ID: `MATCH (aas:Shell {idShort: 'MiR100'}) RETURN aas.id`
  2. Query Weaviate with metadata filter: `{"aas_id": "<id-from-neo4j>"}`
- [ ] Test with MCP Inspector: http://localhost:6274/?transport=http&serverUrl=http://localhost:8112/api/mcp/&MCP_PROXY_AUTH_TOKEN=dev-stack-token-12345
- [ ] Reference: [Flowise Multiple Documents QnA](https://docs.flowiseai.com/use-cases/multiple-documents-qna)

### Phase 3: Optimization (Future Work / Thesis Outlook)
- [ ] **Optional:** Build custom MCP Server for VectorDB
  - Cleaner interface: `search_documents(query, aas_id=None)`
  - Encapsulates filtering logic (agent doesn't need to understand VectorDB internals)
  - Consistent with Neo4j MCP approach
  - ~200 lines Python, similar to Neo4j MCP implementation
- [ ] Evaluate: System Prompt approach vs. MCP Server approach
- [ ] Performance optimization: Caching, query routing, hybrid search

## Architecture Notes

This stack is designed to run alongside the Neo4j Knowledge Graph stack. Service names are prefixed (e.g., `kafka-connect-rag`) to avoid conflicts when both stacks run simultaneously.
