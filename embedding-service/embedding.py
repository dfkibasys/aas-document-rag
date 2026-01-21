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
CLASS_NAME = "aas_documents"
UPLOAD_FOLDER = './pdfs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_embedding_model():
    embedding_config = os.getenv("EMBEDDING_MODEL")
    if not embedding_config:
        raise ValueError("EMBEDDING_MODEL not set in .env.embedding")
    provider, model = embedding_config.split(":", 1)
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            return OpenAIEmbeddings(model=model, api_key=api_key)
    elif provider == "google_genai":
        api_key = os.getenv("GOOGLE_API_KEY")
        if api_key:
            return GoogleGenerativeAIEmbeddings(model=model, google_api_key=api_key)
    elif provider == "voyageai":
        api_key = os.getenv("VOYAGE_API_KEY")
        if api_key:
            return VoyageAIEmbeddings(model=model, api_key=api_key)
    raise ValueError(f"No valid API key found for provider {provider}")

embedding_model = get_embedding_model()

def is_pdf(el):
    return el.get("modelType") == "File" and "application/pdf" in str(el.get("contentType", "")).lower()

def get_ids(event, el=None):
    sm_id = event.get("id")
    smElementPath = event.get("smElementPath")
    return sm_id, smElementPath

def clean_text_for_utf8(text):
    if not text: return ""
    return "".join(char for char in text if char.isprintable() or char in "\n\r\t")

def get_markdown_text(path):
    try:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_table_structure = True
        pipeline_options.do_ocr = False
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        result = converter.convert(path)
        return result.document.export_to_markdown()
    except Exception as e:
        raise

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
        batch_embs = embedding_model.embed_documents(batch)
        embs.extend(batch_embs)
    return embs

def ingest_from_url(url, id_s, sm_id, sm_element_path=None):
    if not url or not url.startswith("http"):
        sm_id_b64 = base64.urlsafe_b64encode(sm_id.encode()).decode().rstrip("=")
        base_url = os.getenv("BASYX_SUBMODEL_REPO", "http://basyx-repo")
        url = f"{base_url}/submodels/{sm_id_b64}/submodel-elements/{id_s}/attachment"

    raw_name = url.split('/')[-1].split('?')[0]
    fname = f"{secure_filename(sm_id)}_{secure_filename(id_s)}_{secure_filename(raw_name)}"
    if not fname.lower().endswith('.pdf'):
        fname += ".pdf"
    path = os.path.join(UPLOAD_FOLDER, fname)

    client = None
    try:
        res = requests.get(url, timeout=30)
        res.raise_for_status()
        with open(path, 'wb') as f:
            f.write(res.content)

        markdown_text = get_markdown_text(path)
        texts = chunks_from_text(markdown_text)

        if not texts or all(not t.strip() for t in texts):
            return

        embeddings = compute_embeddings_batched(texts)

        client = weaviate.connect_to_custom(
            http_host=WEAVIATE_HOST, http_port=8080, http_secure=False,
            grpc_host=WEAVIATE_HOST, grpc_port=50051, grpc_secure=False,
            skip_init_checks=True
        )

        if not client.collections.exists(CLASS_NAME):
            client.collections.create(
                name=CLASS_NAME,
                vector_config=wvc.Configure.Vectors.self_provided(),
                properties=[
                    wvc.Property(name="text", data_type=wvc.DataType.TEXT),
                    wvc.Property(name="source", data_type=wvc.DataType.TEXT),
                    wvc.Property(name="submodelId", data_type=wvc.DataType.TEXT),
                    wvc.Property(name="smElementPath", data_type=wvc.DataType.TEXT),
                    wvc.Property(name="idShort", data_type=wvc.DataType.TEXT)
                ]
            )

        collection = client.collections.get(CLASS_NAME)
        data_objects = [
            wcd.DataObject(
                properties={
                    "text": t,
                    "source": raw_name,
                    "submodelId": sm_id,
                    "smElementPath": sm_element_path,
                    "idShort": id_s
                },
                vector=v
            ) for t, v in zip(texts, embeddings)
        ]
        collection.data.insert_many(data_objects)

    finally:
        if client:
            client.close()
        if os.path.exists(path):
            os.remove(path)

def delete_specific_document(sm_id, smElementPath=None):
    client = None
    try:
        client = weaviate.connect_to_custom(
            http_host=WEAVIATE_HOST, http_port=8080, http_secure=False,
            grpc_host=WEAVIATE_HOST, grpc_port=50051, grpc_secure=False,
            skip_init_checks=True
        )

        if not client.collections.exists(CLASS_NAME):
            return

        collection = client.collections.get(CLASS_NAME)
        where_filter = wvf.Filter.by_property("submodelId").equal(sm_id)

        if smElementPath:
            where_filter = where_filter & wvf.Filter.by_property("smElementPath").equal(smElementPath)

        collection.data.delete_many(where=where_filter)

    except Exception:
        pass
    finally:
        if client:
            client.close()

class DefaultStackSmePathInfo:
    def __init__(self, repo, submodel_id=None, id_short_path=None):
        self._referable_stack = deque()
        self.repo = repo
        self.submodel_id = submodel_id
        self.base_id_short_path = id_short_path

    def get_submodel_id(self):
        if self.submodel_id is None and len(self._referable_stack) > 0:
            ref = self._referable_stack[0]
            if hasattr(ref, 'id'):
                self.submodel_id = ref.id
        return self.submodel_id

    def _build_path_from_stack(self):
        if not self._referable_stack:
            return ""

        builder = []
        ref_iter = iter(self._referable_stack)
        
        try:
            first = next(ref_iter)
        except StopIteration:
            return ""

        current_list = first if hasattr(first, 'value') and isinstance(first.value, list) else None

        for referable in ref_iter:
            if current_list is not None:
                try:
                    idx = current_list.value.index(referable)
                    builder.append(f"[{idx}]")
                except ValueError:
                    pass
            else:
                builder.append(referable.id_short)

            if hasattr(referable, 'value') and isinstance(referable.value, list):
                current_list = referable
            else:
                current_list = None
                if referable != self._referable_stack[-1]:
                    builder.append(".")
        return "".join(builder)

    def get_id_short_path(self):
        stack_path = self._build_path_from_stack()
        if self.base_id_short_path:
            if not stack_path:
                return self.base_id_short_path
            else:
                return f"{self.base_id_short_path}.{stack_path}"
        else:
            return stack_path

    def offer(self, referable):
        self._referable_stack.append(referable)

    def pop(self):
        if self._referable_stack:
            self._referable_stack.pop()

    def repository(self):
        return self.repo

def process_element(path_info, el, sm_id):
    path_info.offer(el)
    if is_pdf(el):
        id_s = path_info.get_id_short_path()
        sm_element_path = path_info.get_id_short_path()
        ingest_from_url(el.get("value"), id_s, sm_id, sm_element_path)
    if "submodelElements" in el and el["submodelElements"]:
        for sub_el in el["submodelElements"]:
            process_element(path_info, sub_el, sm_id)
    path_info.pop()

def handle_create(event):
    sm_id, _ = get_ids(event)
    if "submodel" in event:
        path_info = DefaultStackSmePathInfo(repo=None, submodel_id=sm_id)
        for el in event["submodel"].get("submodelElements", []):
            process_element(path_info, el, sm_id)
    elif "smElement" in event:
        el = event["smElement"]
        if is_pdf(el):
            path_info = DefaultStackSmePathInfo(repo=None, submodel_id=sm_id, id_short_path=el.get("idShort"))
            sm_element_path = path_info.get_id_short_path()
            id_s = el.get("idShort")
            ingest_from_url(el.get("value"), id_s, sm_id, sm_element_path)

def handle_update(event):
    sm_id, id_s = get_ids(event)
    if "smElement" in event:
        el = event["smElement"]
        if is_pdf(el):
            path_info = DefaultStackSmePathInfo(repo=None, submodel_id=sm_id, id_short_path=el.get("idShort"))
            sm_element_path = path_info.get_id_short_path()
            delete_specific_document(sm_id, id_s)
            ingest_from_url(el.get("value"), id_s, sm_id, sm_element_path)
    elif "submodel" in event:
        delete_specific_document(sm_id)
        handle_create(event)

def handle_delete(event):
    sm_id, smElementPath = get_ids(event)
    delete_specific_document(sm_id, smElementPath)
