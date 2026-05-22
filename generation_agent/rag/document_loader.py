import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_upstage import UpstageEmbeddings

load_dotenv()

DATA_PATH = Path(__file__).parent.parent / "data" / "samsung_insurance_clause_dataset.json"
CHROMA_PERSIST_DIR = str(Path(__file__).parent.parent / "chroma_db")

MAX_CHARS = 3000  # solar-embedding-1-large 4000토큰 한도에 맞춘 안전 마진

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=100,
)


def load_documents() -> list[Document]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"데이터 파일을 찾을 수 없습니다: {DATA_PATH}")

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        raw: list[dict] = json.load(f)

    return [
        Document(page_content=item["page_content"], metadata=item["metadata"])
        for item in raw
    ]


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
    print(f"[document_loader] {len(documents)}개 청크 임베딩 중...")
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
