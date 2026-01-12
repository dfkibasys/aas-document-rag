"""
MCP Server for Weaviate with AAS Metadata Filtering
(final, stable version)
"""

import logging
import os
from typing import Any

import uvicorn
import weaviate
from weaviate.classes.query import Filter, MetadataQuery
from fastmcp import FastMCP
from langchain.embeddings.base import init_embeddings

# -------------------------------------------------
# Logging
# -------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------------------------
# FastMCP setup
# -------------------------------------------------
mcp = FastMCP("aas-weaviate-mcp")

# -------------------------------------------------
# Embedding model (singleton)
# -------------------------------------------------
_embeddings = None


def get_embeddings():
    """
    Initialize embedding model from EMBEDDING_MODEL env var.
    Format: 'provider:model-name' e.g. 'openai:text-embedding-3-small'
    API keys are read automatically from standard env vars (OPENAI_API_KEY, etc.)
    """
    global _embeddings

    if _embeddings is None:
        model = os.getenv("EMBEDDING_MODEL")
        if not model:
            raise RuntimeError(
                "EMBEDDING_MODEL env var required. "
                "Format: 'provider:model-name' e.g. 'openai:text-embedding-3-small'"
            )
        logger.info(f"Initializing embedding model: {model}")
        _embeddings = init_embeddings(model)

    return _embeddings

# -------------------------------------------------
# Weaviate client (singleton)
# -------------------------------------------------
_client: weaviate.WeaviateClient | None = None


def get_client() -> weaviate.WeaviateClient:
    """
    Create or return a singleton Weaviate v4 client.
    Uses the OFFICIAL v4 helper API.
    """
    global _client

    if _client is None:
        scheme = os.getenv("WEAVIATE_SCHEME", "http")
        host = os.getenv("WEAVIATE_HOST", "localhost")
        port = int(os.getenv("WEAVIATE_PORT", "8080"))

        logger.info(f"Connecting to Weaviate at {scheme}://{host}:{port}")

        if scheme != "http":
            raise RuntimeError("Only http scheme supported in this setup")

        # ✅ OFFICIAL & STABLE v4 API
        _client = weaviate.connect_to_local(
            host=host,
            port=port,
        )

    return _client


# -------------------------------------------------
# Tools
# -------------------------------------------------
@mcp.tool()
def search_documents(
    query: str,
    submodel_id: str,
    idShortPath: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """
        Semantic search over AAS documentation stored in Weaviate.

        IMPORTANT:
        - `submodel_id` is REQUIRED.
        It must be obtained beforehand from the AAS/Submodel registry
        (e.g. via a Neo4j query over the AAS graph).
        - `idShortPath` is OPTIONAL and can be used to narrow the search
        to a specific SubmodelElement or section.

        Typical workflow for agents:
        1. Query the AAS knowledge graph (Neo4j) to determine the relevant submodel_id.
        2. Optionally determine an idShortPath for a specific element.
        3. Call this tool with the resolved identifiers.

        Args:
            query: Natural language search query.
            submodel_id: AAS Submodel ID (required).
            idShortPath: Optional path of a SubmodelElement.
            limit: Maximum number of results.

        Returns:
            Search results with text chunks, metadata and vector distance.
        """
    if not submodel_id:
        raise ValueError(
            "submodel_id is required. "
            "It must be obtained from the AAS / Submodel lookup (e.g. Neo4j) before calling this tool."
        )
    try:
        client = get_client()

        collection_name = os.getenv("WEAVIATE_COLLECTION", "Docs")
        collection = client.collections.get(collection_name)

        filters_applied = {"submodel_id": submodel_id}

        where_filter = Filter.by_property("submodel_id").equal(submodel_id)

        if idShortPath:
            where_filter &= Filter.by_property("idShortPath").equal(idShortPath)
            filters_applied["idShortPath"] = idShortPath

        logger.info(
            f"Searching query='{query}' filters={filters_applied}"
        )

        # Embed query text using configured embedding model
        embeddings = get_embeddings()
        query_vector = embeddings.embed_query(query)

        response = collection.query.near_vector(
            near_vector=query_vector,
            limit=limit,
            filters=where_filter,
            return_metadata=MetadataQuery(distance=True),
        )

        results = []
        for obj in response.objects:
            results.append(
                {
                    "text": obj.properties.get("text"),
                    "metadata": {
                        "submodel_id": obj.properties.get("submodel_id"),
                        "idShortPath": obj.properties.get("idShortPath"),
                        "source": obj.properties.get("source"),
                    },
                    "distance": float(obj.metadata.distance)
                    if obj.metadata and obj.metadata.distance is not None
                    else None,
                }
            )

        return {
            "results": results,
            "total": len(results),
            "query": query,
            "filters_applied": filters_applied,
            "collection": collection_name,
        }

    except Exception as e:
        logger.error("Search error", exc_info=True)
        return {
            "error": str(e),
            "results": [],
            "total": 0,
            "query": query,
            "filters_applied": {},
        }


@mcp.tool()
def list_metadata_values(
    field: str = "submodel_id",
    limit: int = 20,
) -> dict[str, Any]:
    """
    List unique metadata values from the collection.
    """
    try:
        client = get_client()
        collection_name = os.getenv("WEAVIATE_COLLECTION", "AASDocument")
        collection = client.collections.get(collection_name)

        response = collection.aggregate.over_all(
            group_by=field
        )

        values = []
        for group in response.groups[:limit]:
            if group.grouped_by and group.grouped_by.value:
                values.append(str(group.grouped_by.value))

        return {
            "values": values,
            "field": field,
            "total": len(values),
            "collection": collection_name,
        }

    except Exception as e:
        logger.error("Metadata listing error", exc_info=True)
        return {
            "error": str(e),
            "values": [],
            "field": field,
            "total": 0,
        }


# -------------------------------------------------
# HTTP / ASGI entrypoint
# -------------------------------------------------
if __name__ == "__main__":
    app = mcp.http_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        log_level="info",
    )
