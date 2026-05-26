import json
from pathlib import Path


SAMPLE_FILES = [
    Path("data/output/legal_body/SRC_0001_보험업감독규정_body.json"),
    Path("data/output/legal_body/SRC_0002_보험업감독업무시행세칙_body.json"),
]


def print_type_and_sample(name, value, depth=0):
    indent = "  " * depth
    print(f"{indent}- {name}: {type(value).__name__}")

    if isinstance(value, dict):
        print(f"{indent}  keys: {list(value.keys())[:30]}")
        for k, v in list(value.items())[:10]:
            print_type_and_sample(k, v, depth + 1)

    elif isinstance(value, list):
        print(f"{indent}  list length: {len(value)}")
        if value:
            print_type_and_sample("[0]", value[0], depth + 1)

    else:
        sample = str(value).replace("\n", " ")[:300]
        print(f"{indent}  sample: {sample}")


def main():
    for path in SAMPLE_FILES:
        print("\n" + "=" * 100)
        print(f"[파일] {path}")

        if not path.exists():
            print("파일 없음")
            continue

        data = json.loads(path.read_text(encoding="utf-8"))

        service = data.get("AdmRulService", {})
        print("[AdmRulService keys]")
        print(list(service.keys()))

        print("\n[조문내용 구조]")
        print_type_and_sample("조문내용", service.get("조문내용"))

        print("\n[부칙 구조]")
        print_type_and_sample("부칙", service.get("부칙"))

        print("\n[별표 구조]")
        print_type_and_sample("별표", service.get("별표"))


if __name__ == "__main__":
    main()