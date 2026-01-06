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

**Events are logged to:** `./logs/aas-events.log`

## Event Flow

```
AAS Environment (CREATE/UPDATE/DELETE)
  → Kafka Topics (aas-events, submodel-events)
  → Kafka Connect FileStreamSink
  → ./logs/aas-events.log
```

## Working with Events

**Watch logs live:**
```bash
tail -f logs/aas-events.log
```

**View specific service logs:**
```bash
docker-compose logs -f kafka-connect-rag
docker-compose logs -f aas-environment
docker-compose logs -f kafka
```

**Example events contain:**
- Submodel metadata (Identification, Signals, TechnicalData, etc.)
- PDF references: `"value": "/aasx/MiR100-User-guide.pdf"`
- File references for images and schemas

## Kafka Connect Configuration

**Current setup:** Single events (`max.poll.records=1`)
- Each event processed individually
- Good for debugging and PoC
- Easy to trace which event causes issues

**For batching** (edit `kafka-connect/config/file-sink-connector.json`):
```json
"consumer.override.max.poll.records": "100"
```

## Connector Management

**Check connector status:**
```bash
curl http://localhost:8085/connectors/AasEventsFileStreamSink/status
```

**Restart connector:**
```bash
curl -X POST http://localhost:8085/connectors/AasEventsFileStreamSink/restart
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

## Next Steps (TODOs)

### Phase 1: RAG Pipeline (Bachelor Thesis Focus)
- [ ] Replace FileStreamSink with HTTP Sink Connector
- [ ] Implement Flask service to receive events via HTTP
- [ ] Extract PDF paths from events (e.g., `/aasx/MiR100-User-guide.pdf`)
- [ ] Download and chunk PDFs using docling
- [ ] Generate embeddings for chunks
- [ ] Store embeddings in vector database (Qdrant/Pinecone/Chroma) with AAS metadata:
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
- [ ] Setup Flowise (LangChain-based low-code agent builder)
- [ ] Configure agent with two tools:
  - **Neo4j MCP Server** (existing): Query AAS knowledge graph for metadata
  - **VectorDB Retriever** (Flowise built-in): Search documents with metadata filtering
- [ ] Implement two-stage retrieval via system prompt:
  1. Query Neo4j to get AAS ID (e.g., "Find MiR100 AAS")
  2. Query VectorDB with metadata filter: `{"aas_id": "<id-from-neo4j>"}`
- [ ] Flowise supports **Metadata Retriever** pattern: LLM extracts metadata from user question, then applies as filter
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
