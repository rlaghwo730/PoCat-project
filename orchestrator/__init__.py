"""
orchestrator 패키지 초기화.
generation_agent, compliance_agent가 sys.path에 없는 경우 poact_agent_my 경로를 추가한다.

추가로 generation_agent/ 디렉토리 자체도 sys.path에 넣어야 한다.
이유: generation_agent/agents/generation_agent.py가
      `from rag.document_loader import get_vectorstore` (top-level absolute import)을
      사용하는데, 팀 원본은 generation_agent/ cwd에서 streamlit을 실행하는 전제로 동작한다.
      오케스트레이터에서 import할 때도 같은 검색 경로를 보장해야 ModuleNotFoundError가 안 난다.
"""
import sys
import os

_AGENT_ROOT = os.path.join(os.path.expanduser("~"), "Desktop", "poact_agent_my")
_GEN_AGENT_DIR = os.path.join(_AGENT_ROOT, "generation_agent")

if os.path.isdir(_AGENT_ROOT) and _AGENT_ROOT not in sys.path:
    sys.path.insert(0, _AGENT_ROOT)

if os.path.isdir(_GEN_AGENT_DIR) and _GEN_AGENT_DIR not in sys.path:
    sys.path.insert(0, _GEN_AGENT_DIR)
