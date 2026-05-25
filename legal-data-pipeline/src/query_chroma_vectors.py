from pathlib import Path
import sys

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer


CHROMA_DIR = Path("data/vector_store/chroma")
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

COLLECTIONS = [
    "law_regulation_vectors",
    "law_attachment_vectors",
    "external_reference_vectors",
]


DEFAULT_QUERIES = [
    "비급여 치료비는 전액 보장합니다.",
    "실손의료보험 보험금 청구 서류 전송",
    "손해사정서 보정요청과 보험금 지급 금액",
    "금융상품 광고에서 소비자 오인 가능성",
]


def search_collection(client, model, collection_name, query, top_k=5):
    collection = client.get_collection(collection_name)

    query_embedding = model.encode(
        [query],
        normalize_embeddings=True,
    ).tolist()

    result = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    rows = []

    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    for idx, item_id in enumerate(ids):
        rows.append(
            {
                "collection": collection_name,
                "id": item_id,
                "distance": distances[idx],
                "metadata": metadatas[idx],
                "document": documents[idx],
            }
        )

    return rows


def print_results(query, rows):
    print("\n" + "=" * 100)
    print(f"[Vector 검색어] {query}")
    print(f"[결과 수] {len(rows)}")

    rows = sorted(rows, key=lambda x: x["distance"])

    for idx, row in enumerate(rows[:10], start=1):
        meta = row["metadata"]

        print("\n" + "-" * 100)
        print(f"[{idx}] distance={row['distance']:.4f}")
        print(f"collection      : {row['collection']}")
        print(f"registry_id     : {meta.get('registry_id')}")
        print(f"source_id       : {meta.get('source_id')}")
        print(f"document_title  : {meta.get('document_title')}")
        print(f"source_table    : {meta.get('source_table')}")
        print(f"chunk_type      : {meta.get('chunk_type')}")
        print(f"article_no      : {meta.get('article_no')}")
        print(f"article_title   : {meta.get('article_title')}")
        print(f"page_no         : {meta.get('page_no')}")
        print(f"preview         : {row['document'][:500]}")


def main():
    if len(sys.argv) >= 2:
        queries = [" ".join(sys.argv[1:])]
    else:
        queries = DEFAULT_QUERIES

    print("=" * 100)
    print("[Chroma Vector 검색 테스트 시작]")
    print(f"- Chroma path: {CHROMA_DIR}")
    print(f"- Model: {MODEL_NAME}")

    model = SentenceTransformer(MODEL_NAME)

    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False),
    )

    for query in queries:
        all_rows = []

        for collection_name in COLLECTIONS:
            try:
                rows = search_collection(
                    client=client,
                    model=model,
                    collection_name=collection_name,
                    query=query,
                    top_k=5,
                )
                all_rows.extend(rows)
            except Exception as e:
                print(f"[ERROR] {collection_name}: {e}")

        print_results(query, all_rows)


if __name__ == "__main__":
    main()