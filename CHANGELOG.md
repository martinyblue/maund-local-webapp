# Changelog

이 문서는 GitHub 버전 배포용 변경 이력을 기록합니다.

## [0.1.5] - 2026-03-18

- heatmap HTML 오른쪽에 논문 스타일의 `Color Range` 범례 추가
- 색상 범례가 선택한 heatmap 범위 `0-1 / 0-5 / 0-100`를 자동으로 반영하도록 수정
- 범례에서 흰색이 `0`, 가장 진한 색이 최대값을 뜻하도록 방향 수정
- README 설명과 회귀 테스트를 범례 기준으로 갱신

## [0.1.4] - 2026-03-18

- heatmap 색상 범위 선택값에 `0-1` 옵션 추가
- 아주 낮은 편집율 차이를 강하게 보고 싶을 때 `0-1` 범위를 쓰도록 웹앱 안내 문구 보강
- README의 heatmap 사용 설명을 `0-1 / 0-5 / 0-100` 기준으로 정리
- 로컬 앱과 GitHub 릴리스 버전을 `0.1.4`로 함께 갱신

## [0.1.3] - 2026-03-15

- `68(wild type)` 같은 annotated sample ID를 기본 분석에서 정상적으로 읽도록 파서 수정
- `seq정보_260315.xlsx` 같은 flat xlsx로 68번 negative control 단일 분석을 실행할 수 있도록 수정
- 기본 분석 안내 문구와 README에 annotated sample ID 및 68번 single-target 사용법 설명 추가
- 68번 sample에 tail mapping이 없어도 경고만 남기고 분석은 계속 진행되도록 검증 경로 보강
- 로컬 앱과 GitHub 릴리스 버전이 `0.1.3`으로 함께 반영되도록 버전 파일 갱신

## [0.1.2] - 2026-03-15

- `입력 확인` 중 예외가 발생해도 페이지가 끊기지 않고 오류 메시지를 화면에 표시하도록 수정
- `run_maund_local_app.command` / `run_maund_local_app.sh` 실행 시 기존 8501 서버를 자동 종료하고 최신 프론트로 다시 시작하도록 수정
- 웹앱 상단 버전 배지가 현재 `VERSION` 파일 값을 즉시 반영하도록 수정
- 버전 업데이트 후 로컬 프론트 버전과 GitHub 릴리스 버전이 함께 맞도록 배포 흐름 보강

## [0.1.1] - 2026-03-15

- `heatmap 분석` 모드 추가
- block 구조 xlsx를 읽어 block별 HTML 리포트와 heatmap TSV 생성 기능 추가
- block별 HTML 안에 기존 MAUND 결과와 position heatmap을 함께 표시하도록 확장
- 결과 폴더 이름을 `maund_<YYMMDD>_<HHMMSS>` 형식으로 변경
- 기존 단일 target 분석과 구형 sequence xlsx 형식 호환 유지
- 웹앱 모드 이름과 안내 문구를 `기본 분석` / `heatmap 분석` 기준으로 정리
- README에 xlsx 형식 요구사항, block 1개 사용 가능 여부, heatmap 분석 사용법 설명 추가

## [0.1.0] - 2026-03-14

- MAUND 로컬 웹앱 첫 공개 버전 추가
- macOS `.command` 와 Windows `.bat` 실행기 추가
- 로컬 브라우저 UI, 폴더/파일 선택창, 결과 열기 기능 추가
- GitHub 업로드 및 버전 태그용 스크립트 추가
