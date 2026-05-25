import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

print("[현재 작업 디렉터리]")
print(Path.cwd())

print("\n[예상 .env 경로]")
print(ENV_PATH)

print("\n[.env 존재 여부]")
print(ENV_PATH.exists())

load_dotenv(dotenv_path=ENV_PATH)

api_key = os.getenv("LAW_API_OC")

print("\n[LAW_API_OC 확인]")
if not api_key:
    print("LAW_API_OC: 없음")
elif api_key == "여기에_국가법령정보_API_KEY":
    print("LAW_API_OC: placeholder 상태")
else:
    masked = api_key[:2] + "*" * max(len(api_key) - 4, 0) + api_key[-2:]
    print("LAW_API_OC:", masked)
    print("길이:", len(api_key))