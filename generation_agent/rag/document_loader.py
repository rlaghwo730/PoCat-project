import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_upstage import UpstageEmbeddings

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_FILES = [
    "일반_약관_3사통합.json",
    "일반_사업방법서_3사통합.json",
    "일반_상품요약서_3사통합.json",
]
CHROMA_PERSIST_DIR = str(Path(__file__).parent.parent / "chroma_db")

MAX_CHARS = 3000

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=100,
)


def load_documents() -> list[Document]:
    documents = []
    for filename in DATA_FILES:
        path = DATA_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"데이터 파일을 찾을 수 없습니다: {path}")
        with open(path, "r", encoding="utf-8") as f:
            raw: list[dict] = json.load(f)
        documents.extend([
            Document(page_content=item["page_content"], metadata=item["metadata"])
            for item in raw
        ])
    print(f"[document_loader] {filename}: {len(raw)}개 항목 로드")
    return documents


def _split_if_needed(documents: list[Document]) -> list[Document]:
    result: list[Document] = []
    for doc in documents:
        if len(doc.page_content) <= MAX_CHARS:
            result.append(doc)
        else:
            chunks = _splitter.split_documents([doc])
            for chunk in chunks:
                chunk.metadata = doc.metadata.copy()
            result.extend(chunks)
    return result


def get_vectorstore(force_reload: bool = False) -> Chroma:
    embeddings = UpstageEmbeddings(model="solar-embedding-1-large")

    chroma_path = Path(CHROMA_PERSIST_DIR)
    already_exists = chroma_path.exists() and any(chroma_path.iterdir())

    if already_exists and not force_reload:
        return Chroma(
            persist_directory=CHROMA_PERSIST_DIR,
            embedding_function=embeddings,
        )

    documents = load_documents()
    documents = _split_if_needed(documents)
    print(f"[document_loader] 총 {len(documents)}개 청크 임베딩 중...")
    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=CHROMA_PERSIST_DIR,
    )
    print("[document_loader] ChromaDB 저장 완료")
    return vectorstore


if __name__ == "__main__":
    vs = get_vectorstore(force_reload=True)
    print(f"벡터스토어 로드 완료. 컬렉션 크기: {vs._collection.count()}")
