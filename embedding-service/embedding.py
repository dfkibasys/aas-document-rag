import os
import requests
from dotenv import load_dotenv
import weaviate
import weaviate.collections.classes.config as wvc
import weaviate.collections.classes.data as wcd
import weaviate.collections.classes.filters as wvf
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from werkzeug.utils import secure_filename
from langchain_openai import OpenAIEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_voyageai import VoyageAIEmbeddings
from collections import deque
import base64

load_dotenv('.env.embedding')
load_dotenv('.env.secrets')

WEAVIATE_HOST = os.getenv("WEAVIATE_HOST", "weaviate")
CLASS_NAME = "Docs"
UPLOAD_FOLDER = './pdfs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_embedding_model():
    embedding_config = os.getenv("EMBEDDING_MODEL")
    if not embedding_config:
        raise ValueError("EMBEDDING_MODEL not set in .env.embedding")
    provider, model = embedding_config.split(":", 1)
    
    api_key_map = {
        "openai": "OPENAI_API_KEY",
        "google_genai": "GOOGLE_API_KEY",
        "voyageai": "VOYAGE_API_KEY"
    }
    api_key = os.getenv(api_key_map.get(provider, ""))
    if not api_key:
        raise ValueError(f"No API key found for provider {provider}")

    if provider == "openai":
        return OpenAIEmbeddings(model=model, api_key=api_key)
    elif provider == "google_genai":
        return GoogleGenerativeAIEmbeddings(model=model, google_api_key=api_key)
    elif provider == "voyageai":
        return VoyageAIEmbeddings(model=model, api_key=api_key)
    raise ValueError(f"Unsupported provider: {provider}")

embedding_model = get_embedding_model()

def is_pdf(el):
    return el.get("modelType") == "File" and "application/pdf" in str(el.get("contentType", "")).lower()

def get_ids(event):
    return event.get("id"), event.get("smElementPath")

def clean_text_for_utf8(text):
    if not text: return ""
    return "".join(char for char in text if char.isprintable() or char in "\n\r\t")

def get_markdown_text(path):
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_table_structure = True
    pipeline_options.do_ocr = False
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )
    result = converter.convert(path)
    return result.document.export_to_markdown()

def chunks_from_text(markdown_text):
    cleaned_text = markdown_text.encode("utf-8", "ignore").decode("utf-8")
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)
    parts = splitter.split_documents([Document(page_content=cleaned_text)])
    return [clean_text_for_utf8(p.page_content) for p in parts]

def compute_embeddings_batched(texts):
    MAX_BATCH_SIZE = 100
    embs = []
    for i in range(0, len(texts), MAX_BATCH_SIZE):
        batch = texts[i:i + MAX_BATCH_SIZE]
        embs.extend(embedding_model.embed_documents(batch))
    return embs

def document_exists(client, sm_id, sm_element_path):
    if not client.collections.exists(CLASS_NAME):
        return False
    
    collection = client.collections.get(CLASS_NAME)
    response = collection.query.fetch_objects(
        filters=(
            wvf.Filter.by_property("submodel_id").equal(sm_id) &
            wvf.Filter.by_property("idShortPath").equal(sm_element_path)
        ),
        limit=1
    )
    return len(response.objects) > 0

def ingest_from_url(url, id_s, sm_id, sm_element_path):
    client = None
    path = None
    try:
        client = weaviate.connect_to_custom(
            http_host=WEAVIATE_HOST, http_port=8080, http_secure=False,
            grpc_host=WEAVIATE_HOST, grpc_port=50051, grpc_secure=False,
            skip_init_checks=True
        )

        if document_exists(client, sm_id, sm_element_path):
            print(f"Abort: {sm_element_path} (Submodel: {sm_id}) is already indexed.")
            return

        if not url or not url.startswith("http"):
            sm_id_b64 = base64.urlsafe_b64encode(sm_id.encode()).decode().rstrip("=")
            base_url = os.getenv("BASYX_SUBMODEL_REPO", "http://basyx-repo")
            url = f"{base_url}/submodels/{sm_id_b64}/submodel-elements/{id_s}/attachment"

        raw_name = url.split('/')[-1].split('?')[0]
        fname = f"{secure_filename(sm_id)}_{secure_filename(id_s)}_{secure_filename(raw_name)}.pdf"
        path = os.path.join(UPLOAD_FOLDER, fname)

        res = requests.get(url, timeout=30)
        res.raise_for_status()
        with open(path, 'wb') as f:
            f.write(res.content)

        markdown_text = get_markdown_text(path)
        texts = chunks_from_text(markdown_text)
        if not texts or all(not t.strip() for t in texts): return

        embeddings = compute_embeddings_batched(texts)

        if not client.collections.exists(CLASS_NAME):
            client.collections.create(
                name=CLASS_NAME,
                vector_config=wvc.Configure.Vectors.self_provided(),
                properties=[
                    wvc.Property(name="text", data_type=wvc.DataType.TEXT),
                    wvc.Property(name="source", data_type=wvc.DataType.TEXT),
                    wvc.Property(name="submodel_id", data_type=wvc.DataType.TEXT),
                    wvc.Property(name="idShortPath", data_type=wvc.DataType.TEXT)
                ]
            )

        collection = client.collections.get(CLASS_NAME)
        data_objects = [
            wcd.DataObject(
                properties={
                    "text": t, 
                    "source": raw_name,
                    "submodel_id": sm_id, 
                    "idShortPath": sm_element_path
                },
                vector=v
            ) for t, v in zip(texts, embeddings)
        ]
        collection.data.insert_many(data_objects)

    except Exception as e:
        print(f"Error during Ingest of {sm_element_path}: {e}")
    finally:
        if client: client.close()
        if path and os.path.exists(path): os.remove(path)

def delete_specific_document(sm_id, sm_element_path=None):
    client = None
    try:
        client = weaviate.connect_to_custom(
            http_host=WEAVIATE_HOST, http_port=8080, http_secure=False,
            grpc_host=WEAVIATE_HOST, grpc_port=50051, grpc_secure=False,
            skip_init_checks=True
        )
        if not client.collections.exists(CLASS_NAME): return

        collection = client.collections.get(CLASS_NAME)
        where_filter = wvf.Filter.by_property("submodel_id").equal(sm_id)
        if sm_element_path:
            where_filter = where_filter & wvf.Filter.by_property("idShortPath").equal(sm_element_path)
        
        collection.data.delete_many(where=where_filter)
    except Exception:
        pass
    finally:
        if client: client.close()

class DefaultStackSmePathInfo:
    def __init__(self, repo=None, submodel_id=None, id_short_path=None):
        self._referable_stack = deque()
        self.submodel_id = submodel_id
        self.base_id_short_path = id_short_path

    def _build_path_from_stack(self):
        if not self._referable_stack: return ""
        builder = []
        for i, ref in enumerate(self._referable_stack):
            name = ref.get("idShort") if isinstance(ref, dict) else getattr(ref, 'id_short', None)
            if name and i > 0: 
                builder.append(name)
        return ".".join(builder)

    def get_id_short_path(self):
        stack_path = self._build_path_from_stack()
        if self.base_id_short_path:
            return f"{self.base_id_short_path}.{stack_path}" if stack_path else self.base_id_short_path
        return stack_path

    def offer(self, referable): self._referable_stack.append(referable)
    def pop(self): 
        if self._referable_stack: self._referable_stack.pop()

def process_element(path_info, el, sm_id):
    path_info.offer(el)
    
    if is_pdf(el):
        current_id_short_path = path_info.get_id_short_path()
        ingest_from_url(el.get("value"), el.get("idShort"), sm_id, current_id_short_path)
    
    sub_elements = el.get("submodelElements", [])
    if not sub_elements and isinstance(el.get("value"), list):
        sub_elements = el["value"]
        
    for sub_el in sub_elements:
        if isinstance(sub_el, dict):
            process_element(path_info, sub_el, sm_id)
            
    path_info.pop()

def handle_create(event):
    sm_id, _ = get_ids(event)
    
    if "submodel" in event:
        path_info = DefaultStackSmePathInfo(submodel_id=sm_id)
        path_info.offer(event["submodel"])
        for el in event["submodel"].get("submodelElements", []):
            process_element(path_info, el, sm_id)
            
    elif "smElement" in event:
        el = event["smElement"]
        if is_pdf(el):
            path_info = DefaultStackSmePathInfo(submodel_id=sm_id, id_short_path=el.get("idShort"))
            ingest_from_url(el.get("value"), el.get("idShort"), sm_id, path_info.get_id_short_path())

def handle_update(event):
    sm_id, event_path = get_ids(event)
    if "smElement" in event:
        el = event["smElement"]
        if is_pdf(el):
            final_path = event_path or el.get("idShort")
            delete_specific_document(sm_id, final_path)
            ingest_from_url(el.get("value"), el.get("idShort"), sm_id, final_path)
    elif "submodel" in event:
        delete_specific_document(sm_id)
        handle_create(event)

def handle_delete(event):
    sm_id, sm_path = get_ids(event)
    delete_specific_document(sm_id, sm_path)