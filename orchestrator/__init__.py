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

# generation_agent 위치: 환경변수 GENERATION_AGENT_DIR을 우선 사용한다.
# 미지정 시에만 기존 기본 경로(~/Desktop/poact_agent_my/generation_agent)로 폴백한다.
_GEN_AGENT_DIR = os.environ.get("GENERATION_AGENT_DIR", "").strip()
if _GEN_AGENT_DIR:
    _AGENT_ROOT = os.path.dirname(_GEN_AGENT_DIR.rstrip(os.sep))
else:
    _AGENT_ROOT = os.path.join(os.path.expanduser("~"), "Desktop", "poact_agent_my")
    _GEN_AGENT_DIR = os.path.join(_AGENT_ROOT, "generation_agent")

for _path in (_AGENT_ROOT, _GEN_AGENT_DIR):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)
