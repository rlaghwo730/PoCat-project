import json
import re
from pathlib import Path


FILES = [
    Path("data/output/legal_body/SRC_0001_보험업감독규정_body.json"),
    Path("data/output/legal_body/SRC_0002_보험업감독업무시행세칙_body.json"),
]


def split_admrul_article_text(full_text):
    if not full_text:
        return []

    text_value = str(full_text).strip()

    pattern = re.compile(
        r"제\s*(?P<article_no>\d+(?:-\d+)?)\s*조"
        r"(?:\s*의\s*(?P<branch_no>\d+))?"
        r"\s*\((?P<title>[^)]{1,100})\)"
    )

    matches = list(pattern.finditer(text_value))

    article_items = []

    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text_value)

        article_text = text_value[start:end].strip()

        article_items.append(
            {
                "조문번호": match.group("article_no"),
                "조문가지번호": match.group("branch_no"),
                "조문제목": match.group("title"),
                "조문내용": article_text[:200],
            }
        )

    return article_items


def main():
    for path in FILES:
        print("\n" + "=" * 100)
        print("[파일]", path)

        data = json.loads(path.read_text(encoding="utf-8"))
        service = data.get("AdmRulService", {})
        text_value = service.get("조문내용")

        print("조문내용 타입:", type(text_value).__name__)
        print("조문내용 길이:", len(text_value) if isinstance(text_value, str) else None)
        print("앞부분:", str(text_value)[:300])

        articles = split_admrul_article_text(text_value)

        print("분리된 조문 수:", len(articles))

        print("\n[앞 10개 조문]")
        for item in articles[:10]:
            print(
                item["조문번호"],
                item["조문제목"],
                "|",
                item["조문내용"][:100],
            )


if __name__ == "__main__":
    main()