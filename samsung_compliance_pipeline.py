from __future__ import annotations
import json
import os
import sys
from compliance_agent.models import DetectionInput, DetectionResult, SectionType

# 데이터셋 기본 경로 — 환경변수 > 현재 작업 디렉토리 순으로 탐색.
DEFAULT_DATASET_FILENAME = "samsung_insurance_clause_dataset.json"


def resolve_dataset_path(explicit_path: str | None = None) -> str:
    """데이터셋 경로 해석.

    우선순위: 인자 > SAMSUNG_DATA_PATH 환경변수 > 현재 디렉토리 default.
    """
    if explicit_path:
        return explicit_path
    env_path = os.environ.get("SAMSUNG_DATA_PATH")
    if env_path:
        return env_path
    return os.path.join(os.getcwd(), DEFAULT_DATASET_FILENAME)


class SamsungDataLoader:
    @staticmethod
    def load_from_json(json_path: str) -> list[dict]:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def convert_to_detection_input(item: dict, iteration: int = 1, session_id: str = "") -> DetectionInput:
        metadata = item.get('metadata', {})
        return DetectionInput(
            iteration=iteration,
            section_type=SectionType.TERMS.value,
            content=item.get('page_content', ''),
            session_id=session_id or metadata.get('company', 'samsung'),
            product_meta={
                'company': metadata.get('company', 'unknown'),
                'document_type': metadata.get('document_type', 'unknown'),
                'section': metadata.get('section', 'unknown'),
                'article': metadata.get('article', 'unknown'),
                'title': metadata.get('title', 'unknown'),
                'policy_type': 'medical_loss',
            }
        )

class CompliancePipeline:
    """약관 검토 파이프라인.

    core_detector: 기존 5 Rule(OVR/SUB/CON/FBD/MRQ) 통합 detector(ViolationDetector).
    legal/consumer: Samsung 데모용 도메인 특화 detector.
    """

    def __init__(
        self,
        core_detector=None,
        legal_detector=None,
        consumer_detector=None,
    ):
        self.core = core_detector
        self.legal = legal_detector
        self.consumer = consumer_detector

    def run(self, detection_input: DetectionInput) -> DetectionResult:
        result = DetectionResult()
        if self.core:
            core_result = self.core.detect(detection_input)
            result.violations.extend(core_result.violations)
        if self.legal:
            result.violations.extend(self.legal.detect(detection_input))
        if self.consumer:
            result.violations.extend(self.consumer.detect(detection_input))
        return result

    def run_batch(self, detection_inputs: list[DetectionInput]) -> dict:
        violations_by_clause = {}
        severity_count = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}

        for detection_input in detection_inputs:
            result = self.run(detection_input)
            article = detection_input.product_meta.get('article', 'unknown')
            if result.violations:
                violations_by_clause[article] = result.violations
                for violation in result.violations:
                    severity_count[violation.severity.value] += 1

        return {
            'total': len(detection_inputs),
            'violations_found': len(violations_by_clause),
            'violations_by_clause': violations_by_clause,
            'summary': severity_count,
        }

def main(data_path: str | None = None):
    print("="*80)
    print("Samsung 실손의료보험 약관 자동 검토 시스템")
    print("="*80)

    resolved_path = resolve_dataset_path(data_path)
    print(f"\n[1단계] Samsung 약관 데이터 로드... ({resolved_path})")
    if not os.path.exists(resolved_path):
        print(f"오류: 데이터 파일을 찾을 수 없습니다 - {resolved_path}")
        print(f"     인자로 경로를 전달하거나 SAMSUNG_DATA_PATH 환경변수를 설정하세요.")
        return None
    loader = SamsungDataLoader()
    raw_data = loader.load_from_json(resolved_path)
    print(f"로드 완료: {len(raw_data)}개 조항")

    print("\n[2단계] Detector 초기화...")
    from legal_review_detector import LegalReviewDetector
    from consumer_protection_detector import ConsumerProtectionDetector
    from compliance_agent.detection_engine.violation_detector import ViolationDetector

    llm_client = None
    core_detector = ViolationDetector()  # OVR/SUB/CON/FBD/MRQ 5 Rule 통합
    legal_detector = LegalReviewDetector(llm_client=llm_client)
    consumer_detector = ConsumerProtectionDetector(llm_client=llm_client)

    print("Core 5 Rule Detector 준비 (OVR/SUB/CON/FBD/MRQ)")
    print("Legal Review Detector 준비")
    print("Consumer Protection Detector 준비")

    print("\n[3단계] 파이프라인 구성...")
    pipeline = CompliancePipeline(
        core_detector=core_detector,
        legal_detector=legal_detector,
        consumer_detector=consumer_detector,
    )
    print("파이프라인 준비 완료")

    print("\n[4단계] 약관 검토 실행 중...")
    detection_inputs = [loader.convert_to_detection_input(item, session_id="samsung") for item in raw_data]
    batch_result = pipeline.run_batch(detection_inputs)

    print("\n" + "="*80)
    print("검토 결과 보고")
    print("="*80)
    print(f"\n종합 통계")
    print(f"  - 검토된 조항: {batch_result['total']}개")
    print(f"  - 위반 발견: {batch_result['violations_found']}개")
    print(f"\n심각도별 분류:")
    print(f"  - CRITICAL: {batch_result['summary']['CRITICAL']}개")
    print(f"  - HIGH: {batch_result['summary']['HIGH']}개")
    print(f"  - MEDIUM: {batch_result['summary']['MEDIUM']}개")
    print(f"  - LOW: {batch_result['summary']['LOW']}개")

    if batch_result['violations_by_clause']:
        print(f"\n위반 조항 상세 (처음 5개만 표시):")
        for i, (article, violations) in enumerate(batch_result['violations_by_clause'].items()):
            if i >= 5:
                print(f"  ... 외 {len(batch_result['violations_by_clause']) - 5}개 조항")
                break
            print(f"\n  [{article}]")
            for v in violations[:2]:
                print(f"    - {v.type.value} ({v.severity.value})")
                print(f"      사유: {v.reason[:50]}...")

    save_results_as_json(batch_result, "./samsung_review_results.json")
    print("\n" + "="*80)
    print("검토 완료!")
    print("="*80)
    return batch_result

def save_results_as_json(batch_result: dict, output_path: str) -> None:
    serializable_result = {
        'total': batch_result['total'],
        'violations_found': batch_result['violations_found'],
        'summary': batch_result['summary'],
        'violations_by_clause': {
            article: [
                {
                    'id': v.violation_id,
                    'type': v.type.value,
                    'severity': v.severity.value,
                    'original_text': v.original_text,
                    'regulation': v.regulation,
                    'reason': v.reason,
                }
                for v in violations
            ]
            for article, violations in batch_result['violations_by_clause'].items()
        }
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(serializable_result, f, ensure_ascii=False, indent=2)

    print(f"결과 저장: {output_path}")

if __name__ == "__main__":
    cli_path = sys.argv[1] if len(sys.argv) > 1 else None
    result = main(cli_path)
