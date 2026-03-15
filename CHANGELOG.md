# Changelog

이 문서는 GitHub 버전 배포용 변경 이력을 기록합니다.

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
