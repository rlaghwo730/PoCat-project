from pathlib import Path
import pandas as pd

EXCEL_PATH = Path("data/input/legal_inventory.xlsx")


def main():
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(
            f"엑셀 파일이 없습니다: {EXCEL_PATH}\n"
            "다음 경로에 파일을 넣었는지 확인하세요:\n"
            "C:\\Users\\wogns\\Documents\\silson-legal-data-pipeline\\data\\input\\legal_inventory.xlsx"
        )

    xls = pd.ExcelFile(EXCEL_PATH)

    print("[엑셀 시트 목록]")
    for sheet in xls.sheet_names:
        print(f"- {sheet}")

    print("\n[시트별 컬럼 및 샘플]")
    for sheet in xls.sheet_names:
        print("\n" + "=" * 80)
        print(f"[시트명] {sheet}")

        df = pd.read_excel(EXCEL_PATH, sheet_name=sheet)

        print(f"행 수: {len(df)}")
        print(f"컬럼 수: {len(df.columns)}")

        print("컬럼 목록:")
        for col in df.columns:
            print(f"  - {col}")

        print("\n상위 5행:")
        print(df.head(5).to_string(index=False))


if __name__ == "__main__":
    main()