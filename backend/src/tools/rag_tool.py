import sys
from pathlib import Path

from langchain_core.tools import tool

# PoCat-project 루트: backend/src/tools/rag_tool.py 기준 4단계 상위
_ROOT = Path(__file__).parent.parent.parent.parent
_GEN_AGENT_DIR = _ROOT / "generation_agent"

for _p in [str(_ROOT), str(_GEN_AGENT_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


@tool
def search_rag_context(query: str) -> str:
    """ChromaDB에서 관련 보험 약관 예시를 검색합니다."""
    from rag.document_loader import get_vectorstore
    vectorstore = get_vectorstore()
    docs = vectorstore.similarity_search(query, k=5)
    return "\n\n---\n\n".join(d.page_content for d in docs)
