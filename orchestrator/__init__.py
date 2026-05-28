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
from pathlib import Path
 
# 프로젝트 루트 = orchestrator의 부모 디렉토리
_PROJECT_ROOT = Path(__file__).parent.parent
 
# generation_agent 위치: 환경변수 GENERATION_AGENT_DIR을 우선 사용
_GEN_AGENT_DIR = os.environ.get("GENERATION_AGENT_DIR", "").strip()
if _GEN_AGENT_DIR:
    _gen_path = Path(_GEN_AGENT_DIR)
    _agent_root = _gen_path.parent
else:
    # 환경변수 없으면 프로젝트 루트 기준으로 자동 탐색(streamlit 연동을 위해 필요)
    _gen_path = _PROJECT_ROOT / "generation_agent"
    _agent_root = _PROJECT_ROOT
 
for _path in (str(_agent_root), str(_gen_path)):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)
 
