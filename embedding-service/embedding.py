import os
import requests
from google import genai
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

GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
WEAVIATE_HOST = os.getenv("WEAVIATE_HOST", "weaviate") 
CLASS_NAME = "aas_documents"
UPLOAD_FOLDER = './pdfs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

client_gemini = genai.Client(api_key=GEMINI_API_KEY)

def is_pdf(el):
    return el.get("modelType") == "File" and "application/pdf" in str(el.get("contentType", "")).lower()

def get_ids(event, el=None):
    sm_id = event.get("id")
    id_s = el.get("idShort") if el else None
    if not id_s and "smElementPath" in event:
        id_s = event["smElementPath"].split('.')[-1]
    return sm_id, id_s

def handle_create(event):
    sm_id, _ = get_ids(event)
    if "submodel" in event:
        for el in event["submodel"].get("submodelElements", []):
            if is_pdf(el):
                _, id_s = get_ids(event, el)
                ingest_from_url(el.get("value"), id_s, sm_id)
    elif "smElement" in event:
        el = event["smElement"]
        if is_pdf(el):
            _, id_s = get_ids(event, el)
            ingest_from_url(el.get("value"), id_s, sm_id)

def handle_update(event):
    sm_id, id_s = get_ids(event)
    if "smElement" in event:
        el = event["smElement"]
        if is_pdf(el):
            delete_specific_document(sm_id, id_s)
            ingest_from_url(el.get("value"), id_s, sm_id)
    elif "submodel" in event:
        delete_specific_document(sm_id)
        handle_create(event)

def handle_delete(event):
    sm_id, id_s = get_ids(event)
    delete_specific_document(sm_id, id_s)

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
        
        response = client_gemini.models.embed_content(
            model="text-embedding-004",
            contents=batch,
            config={'task_type': 'RETRIEVAL_DOCUMENT'}
        )
        batch_embs = [[float(val) for val in e.values] for e in response.embeddings]
        embs.extend(batch_embs)
        
    
    return embs

def ingest_from_url(url, id_s, sm_id):
    if not url or not url.startswith("http"):
        return
    
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
                    "idShort": id_s
                },
                vector=v
            ) for t, v in zip(texts, embeddings)
        ]

        results = collection.data.insert_many(data_objects)

    except Exception:
        raise
    finally:
        if client:
            client.close()
        if os.path.exists(path):
            os.remove(path)

def delete_specific_document(sm_id, id_s=None):
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

        if id_s:
            where_filter = where_filter & wvf.Filter.by_property("idShort").equal(id_s)

        result = collection.data.delete_many(where=where_filter)

    except Exception:
        pass
    finally:
        if client:
            client.close()